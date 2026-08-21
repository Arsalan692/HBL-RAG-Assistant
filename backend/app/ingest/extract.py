"""Turning routed pages into one markdown file per document.

This is the quality gate. Everything downstream — chunking, embedding,
retrieval, the answer a compliance officer reads — sees only what this
produces, never the PDF. So the output is written to be *read by a person*:
one file per document, pages in order, each page marked with its number and how
its text was obtained.

Two properties matter more than speed here.

**Resumable.** A full pass is roughly an hour of GPU time, and it runs
unattended on a workstation that may be needed for something else. Every page
is cached by content hash the moment it succeeds, so an interrupted run resumes
where it stopped rather than starting over. Re-running after adding one
document costs one document.

**Honest about failure.** A page that could not be read is written into the
markdown as an explicit marker, not silently omitted. A gap the reader can see
is recoverable; a gap they cannot is not.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

import pymupdf

from app.config import Settings
from app.errors import HblError
from app.ingest.render import render_page
from app.ingest.router import PageVerdict, classify_page
from app.ingest.signals import measure_page
from app.logging_config import get_logger
from app.providers.base import OCR, PageRef

log = get_logger(__name__)

#: Bumped when extraction changes in a way that invalidates cached pages —
#: a different OCR prompt, a fix to the text-layer reader. Cached entries from
#: an older version are ignored, so a fix actually takes effect instead of
#: being masked by a stale cache.
EXTRACTOR_VERSION = 1


@dataclass
class PageRecord:
    """One page's outcome. Written to the sidecar, read back on resume."""

    page: int
    kind: str
    strategy: str
    reason: str
    text: str = ""
    engine: str = ""
    seconds: float = 0.0
    characters: int = 0
    tables: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    #: True when the page needs OCR and no engine was loaded. Distinct from an
    #: error: nothing went wrong, the work simply has not been done yet. Kept
    #: separate so a `--no-ocr` pass on the laptop does not report 278 failures,
    #: and so those pages are neither cached nor written as damage markers.
    deferred: bool = False
    extractor_version: int = EXTRACTOR_VERSION

    @property
    def ok(self) -> bool:
        return not self.error and not self.deferred and self.strategy != "skip"


@dataclass
class DocumentRecord:
    document: str
    sha256: str
    pages: int
    extracted_at: str
    markdown_path: str
    duplicate_of: str = ""
    records: list[PageRecord] = field(default_factory=list)

    @property
    def failed(self) -> list[PageRecord]:
        return [r for r in self.records if r.error]

    @property
    def deferred(self) -> list[PageRecord]:
        return [r for r in self.records if r.deferred]

    @property
    def characters(self) -> int:
        return sum(r.characters for r in self.records)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


#: Table-of-contents dot leaders: "INTRODUCTION........... 4". Typographic
#: filler carrying no information, and every one of these documents opens with
#: a page of them. Left in, they dominate the token count of the chunk they
#: land in and drag its embedding toward every other contents page in the
#: corpus — so a question about introductions retrieves twenty tables of
#: contents. Collapsed rather than deleted, because the page number after the
#: dots is real and worth keeping.
_DOT_LEADER = re.compile(r"[ \t]*\.{4,}[ \t]*")

#: Runs of whitespace that survive joining hard-wrapped PDF lines.
_SPACES = re.compile(r"[ \t]{2,}")

#: The "(1)" a browser appends when the same file is downloaded twice.
_DOWNLOAD_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")


def canonical_first(paths: Iterable[Path]) -> list[Path]:
    """Order documents so the best-named copy of a duplicate is extracted first.

    Deduplication keeps whichever copy it meets first, and that copy's filename
    becomes the source shown in every citation. Plain alphabetical order gets
    this backwards: a space sorts before a full stop, so `Policy (1).pdf` beats
    `Policy.pdf` and the browser's download suffix ends up in front of a
    compliance officer.
    """
    def key(path: Path) -> tuple[int, int, str]:
        stem = path.stem
        return (
            1 if _DOWNLOAD_SUFFIX.search(stem) else 0,  # suffixed copies last
            len(stem),                                   # then the tersest name
            stem.lower(),                                # then stable
        )

    return sorted(paths, key=key)


def _slug(name: str) -> str:
    keep = [c if c.isalnum() or c in "-_" else "-" for c in Path(name).stem]
    return "".join(keep).strip("-")[:80] or "document"


# --- the text-layer path -----------------------------------------------------


def read_text_layer(page: pymupdf.Page) -> str:
    """Extract a digital page's own text, in reading order.

    Deliberately plain. Pages that hold a table never reach here — the router
    sends those to OCR, because PyMuPDF's table reconstruction corrupts them —
    so this only has to handle prose, headings and lists, and the least
    inventive extraction is the most faithful one.

    Blocks are sorted top-to-bottom then left-to-right rather than trusting the
    PDF's internal order, which follows the order a generator emitted content
    and is frequently not the order a human reads it.
    """
    blocks = [b for b in page.get_text("blocks") if len(b) > 6 and b[6] == 0]
    blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))

    parts: list[str] = []
    for block in blocks:
        text = (block[4] or "").strip()
        if not text:
            continue
        # PDF text carries hard line breaks at the typeset line, not the
        # sentence. Joining them back gives chunking something coherent to
        # split on; a blank line still separates real paragraphs.
        joined = " ".join(line.strip() for line in text.splitlines() if line.strip())
        joined = _SPACES.sub(" ", _DOT_LEADER.sub(" ", joined)).strip()
        if joined:
            parts.append(joined)

    return "\n\n".join(parts).strip()


# --- one page ----------------------------------------------------------------


def extract_page(
    page: pymupdf.Page,
    verdict: PageVerdict,
    pdf_path: Path,
    settings: Settings,
    ocr: OCR | None,
) -> PageRecord:
    """Extract one page by whatever route the router chose."""
    record = PageRecord(
        page=verdict.page_number,
        kind=verdict.kind,
        strategy=verdict.strategy,
        reason=verdict.reason,
    )
    if verdict.strategy == "skip":
        return record

    started = time.perf_counter()
    pieces: list[str] = []

    try:
        if verdict.needs_text_layer:
            pieces.append(read_text_layer(page))

        if verdict.needs_ocr:
            if ocr is None:
                record.deferred = True
                record.text = ""
                return record
            image_dir = settings.paths.page_image_dir
            assert image_dir is not None
            rendered = render_page(
                pdf_path,
                verdict.page_number,
                dpi=settings.ingest.render_dpi,
                out_dir=image_dir,
            )
            result = ocr.recognise(
                PageRef(
                    pdf_path=pdf_path,
                    page_number=verdict.page_number,
                    image_path=rendered.image_path,
                    dpi=rendered.dpi,
                    languages=tuple(settings.ocr.language_list),
                )
            )
            pieces.append(result.markdown)
            record.engine = result.engine
            record.tables = result.table_count
            record.warnings = list(result.warnings)

    except Exception as exc:
        record.error = str(exc)[:400]
        record.seconds = round(time.perf_counter() - started, 2)
        log.warning(
            "extract.page_failed",
            extra={"document": pdf_path.name, "page": verdict.page_number, "error": record.error},
        )
        return record

    record.text = "\n\n".join(p for p in pieces if p).strip()
    record.characters = len(record.text)
    record.seconds = round(time.perf_counter() - started, 2)
    if not record.text:
        record.warnings.append("produced no text")
    return record


# --- one document ------------------------------------------------------------


def extract_document(
    pdf_path: Path,
    settings: Settings,
    ocr: OCR | None,
    *,
    force: bool = False,
    seen_hashes: dict[str, str] | None = None,
    on_page: Callable[[PageRecord, int], None] | None = None,
) -> DocumentRecord:
    """Extract every page of one PDF, writing markdown and a provenance sidecar."""
    parsed_dir = settings.paths.parsed_dir
    assert parsed_dir is not None
    parsed_dir.mkdir(parents=True, exist_ok=True)

    stem = _slug(pdf_path.name)
    markdown_path = parsed_dir / f"{stem}.md"
    sidecar_path = parsed_dir / f"{stem}.pages.json"

    digest = sha256_of(pdf_path)

    # Byte-identical duplicates exist in this corpus and must not be extracted
    # twice: doing so would double their weight in retrieval, so the same clause
    # would out-rank a unique one purely for being filed twice.
    if seen_hashes is not None:
        if original := seen_hashes.get(digest):
            log.info("extract.duplicate", extra={"document": pdf_path.name, "of": original})
            return DocumentRecord(
                document=pdf_path.name,
                sha256=digest,
                pages=0,
                extracted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                markdown_path="",
                duplicate_of=original,
            )
        seen_hashes[digest] = pdf_path.name

    cached = _load_cache(sidecar_path, digest) if not force else {}

    records: list[PageRecord] = []
    with pymupdf.open(pdf_path) as doc:
        total = doc.page_count
        for page in doc:
            number = page.number + 1
            if (hit := cached.get(number)) is not None:
                records.append(hit)
                if on_page:
                    on_page(hit, total)
                continue

            verdict = classify_page(measure_page(page), settings.ingest)
            record = extract_page(page, verdict, pdf_path, settings, ocr)
            records.append(record)
            if on_page:
                on_page(record, total)

            # Written after every page, not at the end. An hour-long run that is
            # interrupted keeps everything it had already read.
            _write_sidecar(sidecar_path, pdf_path, digest, len(doc), records)

    document = DocumentRecord(
        document=pdf_path.name,
        sha256=digest,
        pages=len(records),
        extracted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        markdown_path=str(markdown_path),
        records=records,
    )
    markdown_path.write_text(_render_markdown(document), encoding="utf-8")
    _write_sidecar(sidecar_path, pdf_path, digest, len(records), records)
    return document


def _load_cache(sidecar: Path, digest: str) -> dict[int, PageRecord]:
    """Pages already extracted from *this* version of *this* file."""
    if not sidecar.exists():
        return {}
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if payload.get("sha256") != digest:
        return {}  # the file changed; nothing cached about it is trustworthy

    out: dict[int, PageRecord] = {}
    for entry in payload.get("records", []):
        if entry.get("extractor_version") != EXTRACTOR_VERSION:
            continue  # a fix must not be masked by a stale cache
        if entry.get("error") or entry.get("deferred"):
            # Failures are retried, because caching one would make a transient
            # outage permanent. Deferred pages are retried because the whole
            # point of deferring is to do them on the machine that can.
            continue
        if entry.get("strategy") != "skip" and not entry.get("characters"):
            # A page that was not blank and yielded nothing did fail — it simply
            # did not raise. Caching that outcome makes it permanent, and the
            # next run would never revisit it however much the engine improved.
            continue
        entry.setdefault("warnings", [])
        out[entry["page"]] = PageRecord(**entry)
    return out


def _write_sidecar(
    sidecar: Path, pdf_path: Path, digest: str, pages: int, records: Sequence[PageRecord]
) -> None:
    sidecar.write_text(
        json.dumps(
            {
                "document": pdf_path.name,
                "sha256": digest,
                "pages": pages,
                "extractor_version": EXTRACTOR_VERSION,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "records": [asdict(r) for r in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _render_markdown(document: DocumentRecord) -> str:
    """The human-readable artefact. Page markers are load-bearing.

    Every chunk later carries a page number so an answer can cite one, and this
    file is where that number comes from. It is also what a reviewer scrolls
    through to decide whether ingestion worked, which is why a failed page
    appears here as a visible marker rather than as silence.
    """
    lines = [
        f"# {Path(document.document).stem}",
        "",
        f"<!-- source: {document.document} | sha256: {document.sha256[:16]} "
        f"| {document.pages} pages | extracted {document.extracted_at} -->",
        "",
    ]
    for record in document.records:
        if record.strategy == "skip":
            continue
        note = record.engine or "text layer"
        lines.append(f"<!-- page {record.page} | {record.kind} | {note} -->")
        lines.append("")
        if record.deferred:
            lines.append(f"> _[page {record.page} awaiting OCR — re-run on a machine with the engine]_")
        elif record.error:
            lines.append(f"> **[page {record.page} could not be read: {record.error}]**")
        elif not record.text:
            lines.append(f"> **[page {record.page} produced no text]**")
        else:
            lines.append(record.text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --- the corpus --------------------------------------------------------------


def extract_corpus(
    pdf_paths: Iterable[Path],
    settings: Settings,
    ocr: OCR | None,
    *,
    force: bool = False,
    on_page: Callable[[PageRecord, int], None] | None = None,
    on_document: Callable[[DocumentRecord], None] | None = None,
) -> list[DocumentRecord]:
    """Extract several documents, deduplicating by content hash as it goes."""
    seen: dict[str, str] = {}
    out: list[DocumentRecord] = []
    for path in canonical_first(pdf_paths):
        record = extract_document(
            path, settings, ocr, force=force, seen_hashes=seen, on_page=on_page
        )
        out.append(record)
        if on_document:
            on_document(record)
    return out
