"""Ingestion: turning PDFs into indexable, attributable text.

Phase 01 covers the first step only — deciding, per page, where the text should
come from. Nothing here extracts or OCRs yet.
"""

from app.ingest.router import (
    KINDS,
    DocumentSummary,
    PageKind,
    PageVerdict,
    classify_document,
    classify_page,
    summarise_document,
)
from app.ingest.signals import PageSignals, TextQuality, measure_page, table_likeness

__all__ = [
    "KINDS",
    "DocumentSummary",
    "PageKind",
    "PageSignals",
    "PageVerdict",
    "TextQuality",
    "classify_document",
    "classify_page",
    "measure_page",
    "summarise_document",
    "table_likeness",
]
