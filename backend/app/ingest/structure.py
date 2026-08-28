"""Reading parsed markdown back into a document's structure.

Extraction produced one markdown file per document, faithful to each page.
Chunking needs something else: the *sections*, in order, with page numbers
attached and the page furniture gone.

Three things stand between the two, all of them visible in the real corpus:

**Page furniture.** Every page repeats a header and footer — `HBL`,
`**BUSINESS CONTINUITY POLICY**`, `2024`, then `HABIB BANK LIMITED`,
`ATTESTED`, `Company Secretary`, `CONFIDENTIAL`, `PAGE 6 OF 11`. Only ~1.2% of
the corpus by character, so removing it is not a token saving worth boasting
about. It matters because it lands *between* the paragraphs of a section at
every page break, so a continuous argument arrives at the chunker interrupted
ten lines of noise at a time.

**Tables of contents.** These read exactly like section headings, because they
are section headings — listed rather than used. Left in, the chunker builds a
breadcrumb trail from the contents page and then attributes the whole document
to it. A contents entry is recognised by what follows it: nothing.

**Heading numbering that carries the hierarchy.** `1.`, `1.5.`, `2.6.1` — the
depth is in the number, so the breadcrumb comes free once the heading is found.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterator, Literal

BlockKind = Literal["heading", "paragraph", "table", "list"]

#: `<!-- page 7 | digital | text layer -->`, written by extraction.
_PAGE_MARKER = re.compile(r"<!--\s*page\s+(\d+)\s*\|([^|]*)\|([^>]*)-->")

#: `1.`, `1.5.`, `2.6.1` followed by a title. The trailing dot is optional
#: because both forms appear, sometimes in the same document.
_NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+){0,4})\.?\s+(\S.*)$")

_ATX = re.compile(r"^\s*(#{1,6})\s+(\S.*?)\s*#*\s*$")

#: A line that is nothing but bold text. Often a heading, often page furniture;
#: the caller decides which by looking at what follows.
_BOLD_ONLY = re.compile(r"^\s*\*\*(.+?)\*\*\s*$")

#: An annexure or appendix heading, which carries no section number.
_ANNEXURE = re.compile(r"^\s*(annexure|appendix|schedule|exhibit)\b[\s\-–:]*(.*)$", re.IGNORECASE)

_CONTENTS = re.compile(r"^\s*\**\s*(table of contents|contents|index)\s*\**\s*$", re.IGNORECASE)

#: A trailing page number on a contents line: "1.2 Purpose .... 6" or "1.2 Purpose 6".
_TRAILING_PAGE = re.compile(r"[\s.]+\d{1,4}\s*$")

#: Dot leaders followed by a page number — the unmistakable shape of a contents
#: entry: "Annexure 2 Donation Application Form - Internal...............12".
#:
#: Deliberately stricter than `_TRAILING_PAGE`, which would also match a real
#: heading like "Annexure 3" and reject it. Two or more dots are the signal.
_DOT_LEADER = re.compile(r"\.{2,}\s*\d{1,4}\s*$")


@dataclass(frozen=True, slots=True)
class Block:
    """One structural unit of a document."""

    kind: BlockKind
    text: str
    page: int
    #: Heading depth, from the numbering. 0 for non-headings.
    level: int = 0
    #: `2.6.1` where there is one.
    number: str = ""
    #: Heading text without its number.
    title: str = ""
    #: Body text the transcription ran onto the heading's own line. Emitted as
    #: a paragraph immediately after, so the words are kept and the breadcrumb
    #: stays a heading.
    trailing: str = ""

    @property
    def is_heading(self) -> bool:
        return self.kind == "heading"


@dataclass
class ParsedDocument:
    blocks: list[Block] = field(default_factory=list)
    #: Lines dropped as repeating page furniture, for reporting.
    furniture: list[str] = field(default_factory=list)
    #: Pages identified as a table of contents.
    contents_pages: set[int] = field(default_factory=set)


def _iter_page_segments(markdown: str) -> Iterator[tuple[int, str]]:
    """Split the document at its page markers, yielding (page number, text)."""
    matches = list(_PAGE_MARKER.finditer(markdown))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        yield int(match.group(1)), markdown[start:end]


def furniture_key(line: str) -> str:
    """A line with its numbers blanked, for recognising a repeating template.

    A running footer reads `PAGE 6 OF 11` on one page and `PAGE 7 OF 11` on the
    next, so counting lines verbatim never sees a repeat and the footer survives
    into every chunk. Blanking digits first collapses both to `PAGE # OF #`,
    which repeats ten times and is unmistakable.

    Applied only for *counting*. A line is still removed by exact identity, so
    blanking cannot cause a sentence to be dropped because some other page
    happened to contain the same sentence with a different figure in it.
    """
    return re.sub(r"\d+", "#", line).strip(" *")


def find_furniture(markdown: str, *, min_share: float = 0.4, min_pages: int = 4) -> set[str]:
    """Lines that repeat across most pages, and so belong to the page not the text."""
    pages = list(_iter_page_segments(markdown))
    if len(pages) < min_pages:
        return set()

    counts: Counter[str] = Counter()
    by_key: dict[str, set[str]] = {}
    for _, segment in pages:
        # Once per page, not once per occurrence: a line appearing three times
        # on one page is not thereby a header.
        seen: set[str] = set()
        for raw in segment.splitlines():
            line = raw.strip()
            if not line or line.startswith("|") or len(line) > 90:
                continue
            # Decoration stripped so `HBL`, `**HBL**` and `# HBL` count as one
            # header rather than three lines that each miss the threshold.
            bare = line.strip("#* ").strip()
            if not bare or bare in seen:
                continue
            seen.add(bare)
            key = furniture_key(bare)
            counts[key] += 1
            by_key.setdefault(key, set()).add(bare)

    threshold = max(3, int(len(pages) * min_share))
    furniture: set[str] = set()
    for key, count in counts.items():
        if count < threshold:
            continue
        # A key that is nothing but blanked numbers and punctuation is a bare
        # page number; a key with words in it is a header or footer template.
        if not re.search(r"[A-Za-z]", key) and count < max(3, len(pages) * 0.6):
            continue
        furniture.update(by_key[key])
    return furniture


def is_contents_table(body: str) -> bool:
    """True when a table is a table of contents rather than data.

    The Business Continuity policy renders its contents page as
    `| 1.1. INTRODUCTION | ... |`, which has the shape of a real table and none
    of the substance. The tell is that most rows are a section number and a
    title, with a page number or an ellipsis where a value should be.
    """
    rows = [
        row for row in body.splitlines()
        if row.strip().startswith("|") and not set(row.strip()) <= set("|-: ")
    ]
    if len(rows) < 3:
        return False

    listed = 0
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        rest = " ".join(cells[1:]).strip()
        numbered = bool(_NUMBERED.match(first)) or bool(_ANNEXURE.match(first))
        empty_value = rest in {"", "..."} or bool(re.fullmatch(r"[.\s]*\d{0,4}[.\s]*", rest))
        if numbered and empty_value:
            listed += 1

    return listed >= max(3, int(len(rows) * 0.6))


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def contents_index(markdown: str) -> dict[str, str]:
    """Section number to title, read off the document's own contents page.

    Worth the extra pass because it solves a problem nothing else can. The
    vision model frequently transcribes a heading and the sentence after it as
    one line:

        1.3 Risk Categories There are four risk-based categories that apply...

    Nothing in that line marks where the title stops. But the contents page
    says `1.3 Risk Categories 4`, so the title is known exactly, and the
    remainder is body text. Without this the breadcrumb becomes
    "1.3 Risk Categories There are four risk-based categories that apply" and
    every citation of that clause carries a sentence of prose in its section
    name.
    """
    index: dict[str, str] = {}
    for line in markdown.splitlines():
        stripped = line.strip().strip("|").strip()
        if not stripped:
            continue
        match = _NUMBERED.match(stripped)
        if not match:
            continue
        number, rest = match.group(1), match.group(2).strip()
        # A contents entry ends in the page number it points at. That trailing
        # figure is what distinguishes it from the same heading in the body.
        if not _TRAILING_PAGE.search(rest):
            continue
        title = _TRAILING_PAGE.sub("", rest).strip(" .…*")
        if not title or len(title) > 110:
            continue
        # First mention wins: contents pages come before bodies, and a repeated
        # number later in the document is a different thing.
        index.setdefault(number, title)
    return index


def split_runon_heading(number: str, rest: str, index: dict[str, str]) -> tuple[str, str]:
    """Separate a heading from body text transcribed onto the same line.

    Returns (title, trailing body). The body is empty when the line is a plain
    heading, which is the common case.
    """
    known = index.get(number)
    if known:
        marker = _normalise(known)
        flat = _normalise(rest)
        if marker and flat.startswith(marker) and len(flat) > len(marker):
            # Walk the raw string until the normalised prefix is consumed, so
            # the split lands on the original text with its punctuation intact.
            consumed = 0
            for position, character in enumerate(rest):
                if _normalise(character):
                    consumed += 1
                if consumed == len(marker):
                    return rest[: position + 1].strip(), rest[position + 1:].strip()
        if marker and flat == marker:
            return rest.strip(), ""

    return rest.strip(), ""


def _classify_line(line: str, index: dict[str, str] | None = None) -> Block | None:
    """Recognise a heading, or return None for ordinary text."""
    if match := _ATX.match(line):
        title = match.group(2).strip()
        if len(title.split()) > 14:
            return None
        inner = _NUMBERED.match(title)
        number = inner.group(1) if inner else ""
        return Block(
            kind="heading",
            text=title,
            page=0,
            level=number.count(".") + 1 if number else len(match.group(1)),
            number=number,
            title=(inner.group(2) if inner else title).strip(" *"),
        )

    if match := _NUMBERED.match(line):
        number, rest = match.group(1), match.group(2).strip()
        # `12 | Page` is a footer, not section 12. A heading's title begins with
        # a word; anything starting in punctuation is page furniture that
        # happens to lead with a number.
        if not re.match(r"^[\*\"'“(\[]*[A-Za-z]", rest):
            return None

        title, trailing = split_runon_heading(number, rest, index or {})

        # On the contents page itself the "body" after the title is the page
        # number the entry points at, not text. Emitting it would leave a
        # paragraph containing "4" behind every dropped contents entry.
        if re.fullmatch(r"[\s.…]*\d{1,4}[\s.]*", trailing or ""):
            trailing = ""

        # A numbered line still too long after splitting is a numbered
        # paragraph, not a heading — sub-clauses in these documents are written
        # as "4.1.2 The Bank shall ..." and are prose, however they are numbered.
        if len(title) > 110 or len(title.split()) > 14:
            return None

        return Block(
            kind="heading",
            text=line.strip(),
            page=0,
            level=number.count(".") + 1,
            number=number,
            title=title.strip(" *"),
            trailing=trailing,
        )

    if match := _ANNEXURE.match(line.strip(" *")):
        text = line.strip(" *")
        # A contents entry is not a heading, however much it looks like one.
        # "Annexure 2 Donation Application Form - Internal..............12" is
        # 79 characters and seven words, so it cleared both guards below and
        # became a level-1 heading — and then every clause under it inherited
        # that breadcrumb. The Donations Policy's approval thresholds were
        # filed under "Donation Application Form", which is a different
        # subject, in the source panel and in the prompt alike.
        if _DOT_LEADER.search(text):
            return None
        if len(text) <= 110 and len(text.split()) <= 14:
            return Block(kind="heading", text=text, page=0, level=1, number="", title=text)

    return None


def parse(markdown: str) -> ParsedDocument:
    """Turn extracted markdown into ordered blocks with pages attached."""
    furniture = find_furniture(markdown)
    index = contents_index(markdown)
    _blanked_furniture = {furniture_key(line) for line in furniture}
    document = ParsedDocument(furniture=sorted(furniture))

    raw_blocks: list[Block] = []

    for page, segment in _iter_page_segments(markdown):
        lines = segment.splitlines()
        buffer: list[str] = []
        table: list[str] = []

        def flush_paragraph() -> None:
            text = " ".join(buffer).strip()
            buffer.clear()
            if text:
                raw_blocks.append(Block(kind="paragraph", text=text, page=page))

        def flush_table() -> None:
            if not table:
                return
            body = "\n".join(table)
            table.clear()
            if is_contents_table(body):
                # A contents page typeset as a table. Indistinguishable from a
                # real table by shape, and useless to retrieve: it is a list of
                # section names with no section content behind them.
                document.contents_pages.add(page)
                return
            # Atomic by construction: a table becomes one block and is never
            # split, because half a table of risk classifications is worse
            # than none — it still reads as complete.
            raw_blocks.append(Block(kind="table", text=body, page=page))

        for raw in lines:
            line = raw.rstrip()
            stripped = line.strip()

            if stripped.startswith("|"):
                flush_paragraph()
                table.append(stripped)
                continue
            flush_table()

            # Compared with markdown decoration removed, because the same
            # running header arrives as `HBL` on one page and `# HBL` or
            # `**HBL**` on the next, depending on what the OCR model decided it
            # was looking at. Without this, the decorated copy survives and is
            # then promoted to a heading, giving every following chunk a
            # breadcrumb of `HBL`.
            bare = stripped.strip("#* ").strip()
            if bare in furniture or furniture_key(bare) in _blanked_furniture:
                flush_paragraph()
                continue

            if not stripped:
                flush_paragraph()
                continue

            if stripped in furniture:
                flush_paragraph()
                continue

            if _CONTENTS.match(stripped):
                flush_paragraph()
                document.contents_pages.add(page)
                continue

            if heading := _classify_line(stripped, index):
                flush_paragraph()
                raw_blocks.append(
                    Block(
                        kind="heading",
                        text=heading.text,
                        page=page,
                        level=heading.level,
                        number=heading.number,
                        title=heading.title,
                    )
                )
                if heading.trailing:
                    raw_blocks.append(Block(kind="paragraph", text=heading.trailing, page=page))
                continue

            if stripped.startswith(("- ", "* ", "• ")) or re.match(r"^[a-z]\)\s", stripped):
                flush_paragraph()
                raw_blocks.append(Block(kind="list", text=stripped, page=page))
                continue

            if _BOLD_ONLY.match(stripped):
                # Bold-only lines are ambiguous. Kept as paragraphs; a real
                # heading among them almost always carries a number too.
                flush_paragraph()
                raw_blocks.append(Block(kind="paragraph", text=stripped.strip("* "), page=page))
                continue

            buffer.append(stripped)

        flush_paragraph()
        flush_table()

    document.blocks = _drop_contents_listings(raw_blocks, document)
    return document


def _drop_contents_listings(blocks: list[Block], document: ParsedDocument) -> list[Block]:
    """Remove headings that are contents entries rather than sections.

    A contents entry is recognised by what follows it: nothing. `1.2. PURPOSE`
    on the contents page is followed immediately by `1.3. SCOPE`, while the
    same heading in the body is followed by a paragraph explaining the purpose.

    Trailing page numbers are a second signal, and the only one available for
    the last entry in a list, which is followed by whatever comes after the
    contents page.
    """
    kept: list[Block] = []
    for index, block in enumerate(blocks):
        if not block.is_heading:
            kept.append(block)
            continue

        body = 0
        for following in blocks[index + 1:]:
            if following.is_heading:
                break
            body += len(following.text)

        looks_listed = body < 40
        has_page_number = bool(_TRAILING_PAGE.search(block.text)) and block.number != ""

        if looks_listed and (has_page_number or block.page in document.contents_pages or _next_is_heading(blocks, index)):
            document.contents_pages.add(block.page)
            continue

        kept.append(block)
    return kept


def _next_is_heading(blocks: list[Block], index: int) -> bool:
    return index + 1 < len(blocks) and blocks[index + 1].is_heading


def breadcrumb(stack: list[Block]) -> str:
    """`3. Roles and Responsibilities > 3.2. Senior Management`.

    This becomes the section line of a citation, so it is written for a reader
    rather than for a machine: numbers kept, because compliance staff cite them.
    """
    parts = []
    for block in stack:
        number = f"{block.number} " if block.number else ""
        parts.append(f"{number}{block.title}".strip())
    return " > ".join(parts)
