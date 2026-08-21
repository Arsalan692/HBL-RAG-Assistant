"""Picks the handful of pages the OCR engines get judged on.

The bench-off compares candidate OCR engines by reading their output on real
pages, not by trusting published benchmarks — those are measured on academic
document sets that look nothing like a scanned Pakistani bank policy annexure.

The problem is choosing which pages. The corpus is ~1,300 pages and the
interesting ones are rare: engines all handle clean prose, and all differ
violently on a bad photocopy of a table. Picking by eye means paging through
the whole corpus, so this picks by measurement instead, one page per category:

``clean digital``  the control. Any engine that mangles this is disqualified.
``full scan``      an ordinary scanned page at reasonable resolution.
``mixed``          a page with both a real text layer and real raster content.
``dense table``    ruled, multi-column. Where engines differ most.
``poor scan``      lowest effective DPI available. The worst realistic case.

Each category scores every candidate page and takes the best, with documents
spread across categories where possible so the bench does not accidentally
test five pages of the same PDF.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.config import IngestSettings
from app.ingest.router import PageVerdict, classify_page
from app.ingest.signals import measure_page, table_likeness

#: The five slots, in the order a person would want to read them.
CATEGORIES: tuple[str, ...] = ("clean digital", "full scan", "mixed", "dense table", "poor scan")


@dataclass(frozen=True, slots=True)
class Candidate:
    """One page, measured, with its table score and routing verdict."""

    document: Path
    verdict: PageVerdict
    table_score: float

    @property
    def page_number(self) -> int:
        return self.verdict.page_number


@dataclass(frozen=True, slots=True)
class BenchPick:
    """The page chosen for one bench category, and why it won."""

    category: str
    document: Path
    page_number: int
    score: float
    rationale: str


def _score_clean_digital(c: Candidate) -> float:
    s = c.verdict.signals
    if c.verdict.kind != "digital" or s.garble > 0.0:
        return 0.0
    # Dense, unambiguous prose with nothing else on the page. A full A4 page of
    # body text measures about 30 characters per square inch.
    return min(s.char_density / 32.0, 1.0) * (1.0 - s.raster_coverage)


def _score_full_scan(c: Candidate) -> float:
    s = c.verdict.signals
    if c.verdict.kind != "scanned" or not s.has_full_page_raster:
        return 0.0
    # Prefer a normal, legible scan here — the degraded case has its own slot.
    resolution = min(s.raster_dpi / 300.0, 1.0) if s.raster_dpi else 0.3
    return s.raster_coverage * resolution


def _score_mixed(c: Candidate) -> float:
    """The most picture-and-text page available, whatever the router called it.

    Scored on signals rather than on a `hybrid` verdict because this corpus has
    almost no true hybrids — its documents are either born-digital exports or
    wholesale scans. The bench still wants the closest thing to a mixed page,
    since uploaded documents later will not be so tidy.
    """
    s = c.verdict.signals
    if s.raster_coverage < 0.03 or s.char_density < 8:
        return 0.0
    # Substantial amounts of *both*, so score the smaller of the two — a page
    # that is 95% text and 2% logo proves nothing.
    return min(min(s.char_density / 30.0, 1.0), min(s.raster_coverage * 3.0, 1.0))


def _score_dense_table(c: Candidate) -> float:
    if c.verdict.kind == "empty":
        return 0.0
    # Weighted toward table structure, with a nudge for having enough content
    # that a wrong cell boundary is actually visible in the output.
    density = min(c.verdict.signals.char_density / 30.0, 1.0)
    return c.table_score * (0.7 + 0.3 * density)


def _score_poor_scan(c: Candidate) -> float:
    s = c.verdict.signals
    if c.verdict.kind not in ("scanned", "hybrid") or not s.raster_dpi:
        return 0.0
    if s.raster_dpi >= 250:
        return 0.0
    # Lower resolution is *better* for this slot — we want the worst page in
    # the corpus, because that is the one that decides between engines.
    return (250.0 - s.raster_dpi) / 250.0 * min(s.raster_coverage * 1.5, 1.0)


_SCORERS = {
    "clean digital": _score_clean_digital,
    "full scan": _score_full_scan,
    "mixed": _score_mixed,
    "dense table": _score_dense_table,
    "poor scan": _score_poor_scan,
}

_RATIONALE = {
    "clean digital": lambda s: f"{s.char_density:.0f} chars/in2, no raster, text reads as language",
    "full scan": lambda s: f"full-page raster at {s.raster_dpi:.0f} dpi, {s.char_count} chars of prior text layer",
    "mixed": lambda s: f"{s.char_density:.0f} chars/in2 of good text plus {s.raster_coverage:.0%} raster",
    "dense table": lambda s: f"ruled and multi-column, {s.char_density:.0f} chars/in2",
    "poor scan": lambda s: f"raster at only {s.raster_dpi:.0f} dpi - the worst in the corpus",
}


def collect_candidates(pdf_paths: Iterable[Path], settings: IngestSettings) -> list[Candidate]:
    """Measure every page of every document. One pass, no rendering."""
    candidates: list[Candidate] = []
    for path in pdf_paths:
        with pymupdf.open(path) as doc:
            for page in doc:
                signals = measure_page(page)
                verdict = classify_page(signals, settings)
                if verdict.kind == "empty":
                    continue
                candidates.append(Candidate(path, verdict, table_likeness(page)))
    return candidates


def pick_bench_pages(candidates: list[Candidate]) -> list[BenchPick]:
    """Choose one page per category, preferring not to reuse a document.

    Categories are filled in order of how hard they are to satisfy, so the
    scarce ones (a genuinely poor scan, a real hybrid) get first refusal on
    their best page and the plentiful ones settle for a different document.
    """
    order = ("poor scan", "mixed", "full scan", "dense table", "clean digital")
    used_documents: set[Path] = set()
    picks: dict[str, BenchPick] = {}

    for category in order:
        scorer = _SCORERS[category]
        scored = [(scorer(c), c) for c in candidates]
        scored = [(s, c) for s, c in scored if s > 0]
        if not scored:
            continue
        scored.sort(key=lambda pair: pair[0], reverse=True)

        # Take the best page from a document not already spoken for; fall back
        # to the outright best if every strong candidate lives in one file.
        chosen = next((pair for pair in scored if pair[1].document not in used_documents), scored[0])
        score, candidate = chosen
        used_documents.add(candidate.document)
        picks[category] = BenchPick(
            category=category,
            document=candidate.document,
            page_number=candidate.page_number,
            score=round(score, 3),
            rationale=_RATIONALE[category](candidate.verdict.signals),
        )

    return [picks[c] for c in CATEGORIES if c in picks]
