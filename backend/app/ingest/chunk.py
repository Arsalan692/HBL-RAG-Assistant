"""Splitting a document into the units retrieval actually returns.

A chunk is what gets embedded, what gets ranked, and what the model is handed
to answer from. Three properties follow from that, and they are what this
module is for:

**A chunk should answer a question by itself.** Retrieval returns it alone,
stripped of everything around it, so it carries its own breadcrumb — a reader
(and the model) can see it is clause 3.2 of the Business Continuity Policy
without the rest of the file.

**A chunk should not end mid-clause.** Splits follow section boundaries first
and sentence boundaries second. A size limit is a last resort, not the
organising principle.

**A table is never split.** Half a table of country risk classifications still
reads as a complete table — it simply omits the rows that would have
contradicted it. That is the most dangerous shape a chunk can take, so tables
are atomic even when they blow the size budget.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Callable, Sequence

from app.config import ChunkSettings
from app.ingest.metadata import DocumentIdentity
from app.ingest.structure import Block, breadcrumb

#: Sentence ends, kept conservative: an abbreviation or a clause number
#: ("3.2.") must not be mistaken for one, or overlap starts mid-sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'“])")


def estimate_tokens(text: str) -> int:
    """Roughly how many tokens `text` will become.

    Four characters per token is the usual English approximation and is what is
    used until Phase 03, when bge-m3's own tokenizer becomes available and can
    be passed in as `count_tokens`. The estimate only has to be good enough to
    pick split points — being 10% out moves a boundary by a sentence, which is
    invisible; being wrong about *where* to split is not.
    """
    return max(1, len(text) // 4)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One retrievable unit, with everything a citation needs."""

    chunk_id: str
    doc_id: str
    title: str
    policy_family: str
    year: int | None
    #: `3. Roles and Responsibilities > 3.2. Senior Management`
    section: str
    section_number: str
    #: Pages this chunk's text came from — usually one, two across a break.
    pages: tuple[int, ...]
    text: str
    tokens: int
    #: "prose" or "table". Tables are ranked and rendered differently later.
    kind: str = "prose"

    def to_payload(self) -> dict:
        """Flat form for the vector store payload and the keyword index."""
        payload = asdict(self)
        payload["pages"] = list(self.pages)
        payload["page"] = self.pages[0] if self.pages else 0
        return payload


#: Fewer real words than this and a prose chunk carries no answer. Residual
#: page furniture that fell below the repeat threshold in its own document
#: lands here -- "HABIB BANK", "Company Secretary", a stray "4". Embedding them
#: costs nothing but returns them as matches for short queries.
MIN_CONTENT_WORDS = 6


@dataclass
class ChunkStats:
    chunks: int = 0
    tables: int = 0
    oversized: int = 0
    merged_fragments: int = 0
    dropped_empty: int = 0
    sections: set[str] = field(default_factory=set)


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(text) if part.strip()]


def _tail(text: str, budget: int, count_tokens: Callable[[str], int]) -> str:
    """The last whole sentences of `text` fitting in `budget` tokens.

    Whole sentences, because the point of overlap is that a clause split across
    two chunks is answerable from either. Half a sentence at the head of a
    chunk is the "begins mid-sentence with no context" failure, arrived at by a
    different route.
    """
    if budget <= 0:
        return ""
    sentences = _split_sentences(text)
    taken: list[str] = []
    used = 0
    for sentence in reversed(sentences):
        cost = count_tokens(sentence)
        if used + cost > budget and taken:
            break
        taken.insert(0, sentence)
        used += cost
    return " ".join(taken)


def chunk_document(
    blocks: Sequence[Block],
    identity: DocumentIdentity,
    settings: ChunkSettings,
    *,
    count_tokens: Callable[[str], int] = estimate_tokens,
) -> tuple[list[Chunk], ChunkStats]:
    """Split one parsed document into chunks."""
    chunks: list[Chunk] = []
    stats = ChunkStats()

    stack: list[Block] = []
    buffer: list[Block] = []
    carried = ""

    def current_section() -> tuple[str, str]:
        # Empty before the first heading — front matter, approval sheets, the
        # cover. Left blank rather than filled with the document title, which
        # `_build` prefixes anyway and would otherwise print twice.
        if not stack:
            return "", ""
        return breadcrumb(stack), stack[-1].number

    def flush(*, force: bool = False) -> None:
        nonlocal buffer, carried
        if not buffer:
            return

        section, number = current_section()
        body = "\n\n".join(block.text for block in buffer).strip()
        if carried:
            body = f"{carried}\n\n{body}"
        if not body:
            buffer = []
            return

        tokens = count_tokens(body)
        # Too small to stand alone: keep accumulating rather than emitting a
        # fragment that matches on a stray word and answers nothing.
        if tokens < settings.min_tokens and not force:
            return

        pages = tuple(sorted({block.page for block in buffer}))
        kind = "table" if all(block.kind == "table" for block in buffer) else "prose"
        chunks.append(
            _build(identity, settings, section, number, pages, body, kind, count_tokens)
        )
        stats.chunks += 1
        stats.sections.add(section)
        if kind == "table":
            stats.tables += 1
        if tokens > settings.target_tokens * 1.5:
            stats.oversized += 1

        carried = _tail(body, settings.overlap_tokens, count_tokens) if kind == "prose" else ""
        buffer = []

    for block in blocks:
        if block.is_heading:
            # A heading closes whatever came before it: sections are the primary
            # boundary, and a chunk spanning two of them belongs to neither.
            flush(force=True)
            carried = ""
            while stack and stack[-1].level >= block.level:
                stack.pop()
            stack.append(block)
            continue

        if block.kind == "table":
            # Atomic. Emitted on its own so nothing can push it over a boundary,
            # and never merged with prose that might get split later.
            flush(force=True)
            carried = ""
            section, number = current_section()
            text = block.text
            chunks.append(
                _build(
                    identity, settings, section, number, (block.page,), text, "table", count_tokens
                )
            )
            stats.chunks += 1
            stats.tables += 1
            if count_tokens(text) > settings.max_table_tokens:
                stats.oversized += 1
            continue

        projected = count_tokens("\n\n".join(b.text for b in buffer + [block]))
        if buffer and projected > settings.target_tokens:
            flush(force=True)

        buffer.append(block)

    flush(force=True)

    # Fragments that survived because they ended a section: fold each into the
    # chunk before it where that stays within budget.
    merged = _merge_fragments(chunks, settings, stats, count_tokens)

    kept: list[Chunk] = []
    for chunk in merged:
        if chunk.kind == "prose" and len(_body_of(chunk).split()) < MIN_CONTENT_WORDS:
            stats.dropped_empty += 1
            stats.chunks -= 1
            continue
        kept.append(chunk)
    return kept, stats


def _build(
    identity: DocumentIdentity,
    settings: ChunkSettings,
    section: str,
    number: str,
    pages: tuple[int, ...],
    body: str,
    kind: str,
    count_tokens: Callable[[str], int],
) -> Chunk:
    text = body
    if settings.prefix_breadcrumb:
        # Cheap, and it makes a chunk retrieved in isolation still say which
        # policy and clause it is. Also gives dense search the section title as
        # signal, which matters for questions phrased in a heading's words.
        # The year sits with the title, not after the section: this label is the
        # only place a reader — or the model — sees which vintage they are
        # looking at, and "Introduction (2023)" reads as if the section is dated
        # rather than the policy.
        name = f"{identity.title} ({identity.year})" if identity.year else identity.title
        label = f"{name} — {section}" if section else name
        text = f"[{label}]\n\n{body}"

    digest = hashlib.sha256(f"{identity.doc_id}|{section}|{pages}|{body}".encode()).hexdigest()[:16]
    return Chunk(
        chunk_id=f"{identity.doc_id}:{digest}",
        doc_id=identity.doc_id,
        title=identity.title,
        policy_family=identity.policy_family,
        year=identity.year,
        section=section,
        section_number=number,
        pages=pages,
        text=text,
        tokens=count_tokens(text),
        kind=kind,
    )


def _body_of(chunk: Chunk) -> str:
    """A chunk's text without the breadcrumb line `_build` prefixed."""
    head, separator, rest = chunk.text.partition("\n\n")
    return rest if separator and head.startswith("[") else chunk.text


def _joined(
    first: Chunk, second: Chunk, count_tokens: Callable[[str], int]
) -> Chunk:
    """`second` folded into `first`, keeping the first's identity and prefix."""
    body = f"{first.text}\n\n{_body_of(second)}"
    return Chunk(
        chunk_id=first.chunk_id,
        doc_id=first.doc_id,
        title=first.title,
        policy_family=first.policy_family,
        year=first.year,
        section=first.section,
        section_number=first.section_number,
        pages=tuple(sorted(set(first.pages) | set(second.pages))),
        text=body,
        tokens=count_tokens(body),
        kind="table" if "table" in (first.kind, second.kind) else "prose",
    )


def _merge_fragments(
    chunks: list[Chunk],
    settings: ChunkSettings,
    stats: ChunkStats,
    count_tokens: Callable[[str], int],
) -> list[Chunk]:
    """Fold undersized chunks into a neighbour.

    Forward first, then backward. Forward matters because the commonest
    fragment in this corpus is a caption — `Prepared by:`, `Reviewed by:` —
    sitting immediately above the table it introduces. Left alone it is a
    17-token chunk that matches the word "prepared" and answers nothing, while
    the table beneath it loses the only label saying what it is.

    A merge that would break the size budget is declined, and tables are never
    merged *into* prose in a way that could later be split: the result is
    marked as a table so it stays atomic.
    """
    merged: list[Chunk] = []
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        following = chunks[index + 1] if index + 1 < len(chunks) else None

        undersized = chunk.tokens < settings.min_tokens

        if (
            undersized
            and following is not None
            and following.section == chunk.section
            and chunk.tokens + following.tokens <= settings.target_tokens * 1.2
        ):
            merged.append(_joined(chunk, following, count_tokens))
            stats.merged_fragments += 1
            stats.chunks -= 1
            index += 2
            continue

        if (
            undersized
            and merged
            and merged[-1].section == chunk.section
            and merged[-1].tokens + chunk.tokens <= settings.target_tokens * 1.2
        ):
            merged[-1] = _joined(merged[-1], chunk, count_tokens)
            stats.merged_fragments += 1
            stats.chunks -= 1
            index += 1
            continue

        merged.append(chunk)
        index += 1

    return merged
