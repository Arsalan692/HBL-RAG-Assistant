"""Tests for extraction: the text-layer reader, caching, dedupe and output.

Built on PDFs constructed in memory and a fake OCR engine. Nothing needs the
corpus, a GPU, or Ollama.
"""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from app.config import Settings
from app.errors import ProviderUnavailable
from app.ingest.extract import (
    extract_corpus,
    extract_document,
    read_text_layer,
    sha256_of,
)
from app.providers.base import OcrResult, PageRef

PROSE = (
    "The Bank shall apply enhanced due diligence to any customer identified as a "
    "politically exposed person, and shall obtain senior management approval. "
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.paths.documents_dir = tmp_path / "documents"
    s.paths.parsed_dir = tmp_path / "parsed"
    s.paths.page_image_dir = tmp_path / "images"
    s.paths.documents_dir.mkdir(parents=True)
    return s


def _digital_pdf(path: Path, pages: int = 2) -> Path:
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), f"Clause {n + 1}. " + PROSE * 10, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def _scanned_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1240, 1755), False)
    pix.clear_with(210)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    doc.save(path)
    doc.close()
    return path


class _FakeOCR:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[PageRef] = []

    def recognise(self, page: PageRef) -> OcrResult:
        self.calls.append(page)
        return OcrResult(
            markdown="| Risk | Tier |\n|---|---|\n| High | 1 |",
            engine="fake:v1",
            page_number=page.page_number,
            table_count=1,
            duration_s=0.1,
        )


# --- the text-layer reader ---------------------------------------------------


def test_hard_wrapped_lines_are_joined_back_into_paragraphs(tmp_path: Path) -> None:
    """PDF line breaks fall at the typeset line, not the sentence."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(50, 50, 300, 400), PROSE * 3, fontsize=10)
    text = read_text_layer(page)
    doc.close()

    assert "politically exposed person" in text
    # Wrapping must not have split a word across a newline.
    assert "\n" not in text.split("politically")[0][-40:]


def test_table_of_contents_dot_leaders_are_collapsed(tmp_path: Path) -> None:
    """Left in, they dominate a chunk and pull its embedding toward every other
    contents page in the corpus."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        pymupdf.Rect(50, 50, 545, 300),
        "1. INTRODUCTION..................................................... 4",
        fontsize=10,
    )
    text = read_text_layer(page)
    doc.close()

    assert "...." not in text
    assert "INTRODUCTION" in text
    assert "4" in text  # the page number after the dots is real


def test_blocks_are_read_top_to_bottom_not_in_pdf_order(tmp_path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # Inserted bottom-first, deliberately.
    page.insert_textbox(pymupdf.Rect(50, 500, 545, 700), "SECOND paragraph here.", fontsize=11)
    page.insert_textbox(pymupdf.Rect(50, 100, 545, 300), "FIRST paragraph here.", fontsize=11)
    text = read_text_layer(page)
    doc.close()

    assert text.index("FIRST") < text.index("SECOND")


# --- routing through extraction ----------------------------------------------


def test_a_digital_document_never_calls_ocr(settings: Settings) -> None:
    pdf = _digital_pdf(settings.paths.documents_dir / "Policy.pdf")  # type: ignore[operator]
    ocr = _FakeOCR()

    record = extract_document(pdf, settings, ocr)

    assert ocr.calls == []
    assert record.pages == 2
    assert all(r.strategy == "text-layer" for r in record.records)


def test_a_scanned_page_goes_through_ocr(settings: Settings) -> None:
    pdf = _scanned_pdf(settings.paths.documents_dir / "Scan.pdf")  # type: ignore[operator]
    ocr = _FakeOCR()

    record = extract_document(pdf, settings, ocr)

    assert len(ocr.calls) == 1
    assert ocr.calls[0].image_path is not None and ocr.calls[0].image_path.exists()
    assert record.records[0].engine == "fake:v1"
    assert record.records[0].tables == 1


# --- the markdown artefact ---------------------------------------------------


def test_markdown_carries_a_page_marker_for_every_page(settings: Settings) -> None:
    """Every chunk later cites a page number, and this file is where it comes from."""
    pdf = _digital_pdf(settings.paths.documents_dir / "Policy.pdf", pages=3)  # type: ignore[operator]

    record = extract_document(pdf, settings, _FakeOCR())
    body = Path(record.markdown_path).read_text(encoding="utf-8")

    for n in (1, 2, 3):
        assert f"<!-- page {n} |" in body
    assert "sha256:" in body


def test_a_failed_page_is_visible_in_the_markdown_not_silently_dropped(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gap the reader can see is recoverable. One they cannot is not."""

    class _Broken:
        name = "broken"

        def recognise(self, page: PageRef) -> OcrResult:
            raise ProviderUnavailable("Ollama is not running")

    pdf = _scanned_pdf(settings.paths.documents_dir / "Scan.pdf")  # type: ignore[operator]
    record = extract_document(pdf, settings, _Broken())

    assert len(record.failed) == 1
    body = Path(record.markdown_path).read_text(encoding="utf-8")
    assert "could not be read" in body
    assert "Ollama is not running" in body


# --- resume and dedupe -------------------------------------------------------


def test_a_second_run_reuses_cached_pages(settings: Settings) -> None:
    """A full pass is an hour of GPU time; an interrupted one must not restart."""
    pdf = _scanned_pdf(settings.paths.documents_dir / "Scan.pdf")  # type: ignore[operator]
    ocr = _FakeOCR()

    extract_document(pdf, settings, ocr)
    assert len(ocr.calls) == 1

    extract_document(pdf, settings, ocr)
    assert len(ocr.calls) == 1  # not re-read


def test_force_re_extracts(settings: Settings) -> None:
    pdf = _scanned_pdf(settings.paths.documents_dir / "Scan.pdf")  # type: ignore[operator]
    ocr = _FakeOCR()

    extract_document(pdf, settings, ocr)
    extract_document(pdf, settings, ocr, force=True)

    assert len(ocr.calls) == 2


def test_an_edited_document_invalidates_its_cache(settings: Settings) -> None:
    path = settings.paths.documents_dir / "Scan.pdf"  # type: ignore[operator]
    _scanned_pdf(path)
    ocr = _FakeOCR()
    extract_document(path, settings, ocr)

    _scanned_pdf(path)  # rewritten: different bytes, different hash
    extract_document(path, settings, ocr)

    assert len(ocr.calls) == 2


def test_failed_pages_are_retried_on_the_next_run(settings: Settings) -> None:
    """Caching a failure would make a transient outage permanent."""

    class _FlakyOCR(_FakeOCR):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def recognise(self, page: PageRef) -> OcrResult:
            if self.fail:
                self.fail = False
                raise ProviderUnavailable("Ollama is not running")
            return super().recognise(page)

    pdf = _scanned_pdf(settings.paths.documents_dir / "Scan.pdf")  # type: ignore[operator]
    ocr = _FlakyOCR()

    first = extract_document(pdf, settings, ocr)
    assert len(first.failed) == 1

    second = extract_document(pdf, settings, ocr)
    assert second.failed == []


def test_a_byte_identical_duplicate_is_extracted_only_once(settings: Settings) -> None:
    """This corpus contains one. Extracting it twice would double its weight in
    retrieval, so the same clause would outrank a unique one for being filed twice."""
    documents = settings.paths.documents_dir
    assert documents is not None
    original = _digital_pdf(documents / "Policy.pdf")
    copy = documents / "Policy (1).pdf"
    copy.write_bytes(original.read_bytes())

    assert sha256_of(original) == sha256_of(copy)

    records = extract_corpus(sorted(documents.glob("*.pdf")), settings, _FakeOCR())

    duplicates = [r for r in records if r.duplicate_of]
    assert len(duplicates) == 1
    # The clean name must be the survivor: it becomes the source in every
    # citation, and alphabetical order would have kept "Policy (1).pdf",
    # because a space sorts before a full stop.
    assert duplicates[0].document == "Policy (1).pdf"
    assert duplicates[0].duplicate_of == "Policy.pdf"


def test_the_sidecar_records_why_each_page_was_routed_as_it_was(settings: Settings) -> None:
    pdf = _digital_pdf(settings.paths.documents_dir / "Policy.pdf")  # type: ignore[operator]
    extract_document(pdf, settings, _FakeOCR())

    sidecar = settings.paths.parsed_dir / "Policy.pages.json"  # type: ignore[operator]
    payload = json.loads(sidecar.read_text(encoding="utf-8"))

    assert payload["sha256"]
    assert len(payload["records"]) == 2
    assert all(r["reason"] for r in payload["records"])


def test_a_page_that_yielded_nothing_is_retried_next_run(settings: Settings) -> None:
    """It did fail, it simply did not raise. Caching that makes it permanent —
    the Insider Trading title page would have stayed unread forever."""

    class _EmptyThenWorking(_FakeOCR):
        def __init__(self) -> None:
            super().__init__()
            self.empty = True

        def recognise(self, page: PageRef) -> OcrResult:
            if self.empty:
                self.empty = False
                self.calls.append(page)
                return OcrResult(markdown="", engine="fake", page_number=page.page_number)
            return super().recognise(page)

    pdf = _scanned_pdf(settings.paths.documents_dir / "Scan.pdf")  # type: ignore[operator]
    ocr = _EmptyThenWorking()

    first = extract_document(pdf, settings, ocr)
    assert first.records[0].characters == 0

    second = extract_document(pdf, settings, ocr)
    assert second.records[0].characters > 0
    assert len(ocr.calls) == 2
