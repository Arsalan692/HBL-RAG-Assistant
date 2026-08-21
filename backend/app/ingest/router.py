"""Decides, for one page, how its text should be obtained.

This is the first real decision in the pipeline and the least recoverable one.
A page routed to the text layer when the text layer is wrong yields confident
nonsense downstream: it embeds, it retrieves, it gets cited, and nothing later
in the chain can tell that the words were never on the page. So the router
errs toward OCR, records the numbers behind every verdict, and explains itself.

Four outcomes:

``DIGITAL``   the embedded text layer is complete and trustworthy — use it.
``SCANNED``   there is no usable text layer — rasterise the page and OCR it.
``HYBRID``    both, in different regions: a digital page with a scanned table
              pasted in, or a scan with a digital header. Extract the text layer
              *and* OCR the raster regions, then merge with overlap detection.
``EMPTY``     nothing on the page worth indexing. Skipped.

The decision is per *page*, never per file. Several documents in this corpus
bind a scanned annexure into an otherwise digital policy, and at least one
opens with a digitally-generated cover on a scanned body. Classifying whole
files would be wrong for a large minority of pages in either direction.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pymupdf

from app.config import IngestSettings
from app.ingest.signals import PageSignals, measure_page

PageKind = Literal["digital", "scanned", "hybrid", "empty"]

KINDS: tuple[PageKind, ...] = ("digital", "scanned", "hybrid", "empty")


@dataclass(frozen=True, slots=True)
class PageVerdict:
    """One page's routing decision, with the evidence that produced it."""

    page_number: int
    kind: PageKind
    #: A sentence a human can check against the page. Written for the person
    #: reviewing the parsed markdown, who needs to know why a page came out
    #: badly without reading this module.
    reason: str
    signals: PageSignals
    #: True when a scanned page arrived with a text layer already on it —
    #: somebody else's OCR, of unknown quality. Not used for routing; carried so
    #: the extraction phase can diff its own output against it and flag pages
    #: where the two disagree, which is a cheap accuracy check for free.
    has_prior_text: bool = False

    @property
    def needs_ocr(self) -> bool:
        return self.kind in ("scanned", "hybrid")

    @property
    def needs_text_layer(self) -> bool:
        return self.kind in ("digital", "hybrid")


def classify_page(signals: PageSignals, settings: IngestSettings) -> PageVerdict:
    """Route one page from its measurements.

    Order matters. Each test below can only be trusted once the ones above it
    have been ruled out, and they are arranged cheapest-and-most-certain first.
    """
    sparse = signals.char_density < settings.min_char_density
    rastered = signals.raster_coverage >= settings.raster_threshold
    garbled = signals.garble >= settings.max_garble
    has_text = signals.char_density >= settings.empty_char_density

    # 1. Blank. Nothing to route, and every later test would misread it —
    #    an empty page is trivially "sparse" and would look scanned.
    if not has_text and not rastered:
        return PageVerdict(
            signals.page_number,
            "empty",
            f"no content ({signals.char_count} characters, no raster)",
            signals,
        )

    # 2. One image covers the page. Then the image *is* the page, and whatever
    #    text sits alongside it was produced by somebody else's OCR — it is a
    #    copy of the picture, not an independent source. Checked before the
    #    text tests precisely because that prior layer can look perfectly
    #    healthy: in this corpus it renders the HBL logo as "MBL HA.aH3GANK"
    #    while the surrounding paragraph extracts cleanly, so no text-quality
    #    measure would catch it.
    if signals.has_full_page_raster:
        if has_text and settings.trust_prior_ocr:
            return PageVerdict(
                signals.page_number,
                "digital",
                f"scan with a prior text layer, trusted by configuration "
                f"({signals.raster_dpi:.0f} dpi image)",
                signals,
                has_prior_text=True,
            )
        note = " (a prior text layer is present and will be diffed against)" if has_text else ""
        return PageVerdict(
            signals.page_number,
            "scanned",
            f"full-page image at {signals.raster_dpi:.0f} dpi{note}",
            signals,
            has_prior_text=has_text,
        )

    # 3. A text layer we do not believe. The dangerous case: character count
    #    looks healthy, so nothing else in the pipeline would ever question it.
    if garbled:
        return PageVerdict(
            signals.page_number,
            "scanned",
            f"text layer present but unreliable - {signals.quality.reason}",
            signals,
            has_prior_text=True,
        )

    # 4. Thin text over a partial raster: the picture holds most of the content.
    if sparse and rastered:
        return PageVerdict(
            signals.page_number,
            "scanned",
            f"{signals.raster_coverage:.0%} raster, only {signals.char_density:.0f} chars/in2 of text",
            signals,
        )

    # 5. Little text and no raster either. Not blank (test 1 passed), so this is
    #    a title page, a divider, or a page whose content is vector line art.
    #    Rasterising costs one page of OCR and settles it; guessing does not.
    if sparse:
        return PageVerdict(
            signals.page_number,
            "scanned",
            f"sparse text ({signals.char_density:.0f} chars/in2) with no raster to explain it",
            signals,
        )

    # 6. Plenty of trustworthy text *and* a substantial raster that does not
    #    cover the page. Both carry content and neither contains the other.
    if rastered:
        return PageVerdict(
            signals.page_number,
            "hybrid",
            f"good text layer plus {signals.raster_coverage:.0%} raster carrying separate content",
            signals,
        )

    # 7. Plenty of trustworthy text, nothing else going on.
    return PageVerdict(
        signals.page_number,
        "digital",
        f"clean text layer ({signals.char_density:.0f} chars/in2)",
        signals,
    )


def classify_document(
    pdf_path: Path, settings: IngestSettings
) -> Iterator[PageVerdict]:
    """Route every page of one PDF, lazily.

    Yields rather than returning a list: the corpus is ~1,300 pages and the
    caller usually wants to stream progress or stop early.
    """
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            yield classify_page(measure_page(page), settings)


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    """What routing found across one document."""

    path: Path
    page_count: int
    counts: dict[PageKind, int]
    verdicts: list[PageVerdict]

    @property
    def ocr_pages(self) -> int:
        return self.counts.get("scanned", 0) + self.counts.get("hybrid", 0)

    @property
    def dominant(self) -> PageKind:
        """The kind most of the document is — for reporting only, never routing."""
        indexable = {k: v for k, v in self.counts.items() if k != "empty" and v}
        if not indexable:
            return "empty"
        return max(indexable, key=lambda k: indexable[k])


def summarise_document(pdf_path: Path, settings: IngestSettings) -> DocumentSummary:
    verdicts = list(classify_document(pdf_path, settings))
    counts: dict[PageKind, int] = {kind: 0 for kind in KINDS}
    for verdict in verdicts:
        counts[verdict.kind] += 1
    return DocumentSummary(pdf_path, len(verdicts), counts, verdicts)
