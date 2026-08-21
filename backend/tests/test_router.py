"""Tests for per-page routing.

Every fixture here is a PDF built in memory. Nothing reads the real corpus:
those are confidential bank policies, and a test suite that only passes on the
one machine holding them is not a test suite.
"""

from __future__ import annotations

import pymupdf
import pytest

from app.config import IngestSettings
from app.ingest.router import classify_page
from app.ingest.signals import assess_text, measure_page

PROSE = (
    "The Bank shall apply enhanced due diligence to any customer identified as a "
    "politically exposed person, and shall obtain senior management approval before "
    "establishing or continuing the relationship. Records are retained for five years "
    "after the relationship ends. "
)


def _settings(**overrides: object) -> IngestSettings:
    return IngestSettings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _page(build) -> pymupdf.Page:
    """Build a one-page PDF in memory and hand back the page."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 in points
    build(page)
    return page


def _fill_with_text(page: pymupdf.Page, repeats: int = 12) -> None:
    page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), PROSE * repeats, fontsize=10)


def _tiny_image_bytes() -> bytes:
    """A 2x2 pixel PNG — the Word-export highlight fill this corpus is full of."""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), False)
    pix.clear_with(200)
    return pix.tobytes("png")


def _photo_bytes(side: int = 800) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, side, side), False)
    pix.clear_with(128)
    return pix.tobytes("png")


# --- text quality ------------------------------------------------------------


def test_ordinary_prose_is_not_garbled() -> None:
    assert assess_text(PROSE * 3).score == 0.0


def test_undecodable_characters_are_garbled() -> None:
    quality = assess_text("Global AML Policy \x03\x04\x05\x06\x07\x0e\x0f\x10\x11 " * 6)
    assert quality.score > 0.45
    assert "undecodable" in quality.reason


def test_text_with_no_spaces_is_garbled() -> None:
    # The signature of a subset font extracted without a ToUnicode map.
    quality = assess_text("GlobalAMLCFTCPFandKYCPolicyapprovedbytheBoardofDirectors" * 3)
    assert quality.score > 0.45
    assert "whitespace" in quality.reason


def test_a_short_fragment_is_never_called_garbled() -> None:
    # A heading-only page must not be sent to OCR for lacking evidence.
    assert assess_text("Annexure B").score == 0.0


# --- measurement -------------------------------------------------------------


def test_a_full_page_of_prose_measures_as_dense_digital() -> None:
    signals = measure_page(_page(_fill_with_text))
    assert signals.char_density > 20
    assert signals.raster_coverage == 0.0
    assert signals.garble == 0.0


def test_two_pixel_highlight_fills_are_not_counted_as_raster() -> None:
    """The bug that called every clean Word export a scan.

    Some producers place a 2x2-pixel coloured image behind each line of text.
    Stretched to line width they cover most of the page, but they carry no
    content and must not trigger OCR.
    """
    tiny = _tiny_image_bytes()

    def build(page: pymupdf.Page) -> None:
        _fill_with_text(page)
        for row in range(30):
            top = 50 + row * 25
            page.insert_image(pymupdf.Rect(50, top, 545, top + 20), stream=tiny)

    signals = measure_page(_page(build))
    assert signals.decorative_image_count >= 30
    assert signals.image_count == 0
    assert signals.raster_coverage == 0.0
    assert classify_page(signals, _settings()).kind == "digital"


def test_effective_resolution_is_reported_for_a_real_image() -> None:
    def build(page: pymupdf.Page) -> None:
        # 800 pixels drawn across 400 points = 800 / (400/72) = 144 dpi.
        page.insert_image(pymupdf.Rect(50, 50, 450, 450), stream=_photo_bytes(800))

    signals = measure_page(_page(build))
    assert 140 < signals.raster_dpi < 150


# --- routing -----------------------------------------------------------------


def test_a_blank_page_is_empty() -> None:
    verdict = classify_page(measure_page(_page(lambda p: None)), _settings())
    assert verdict.kind == "empty"


def test_a_prose_page_is_digital() -> None:
    verdict = classify_page(measure_page(_page(_fill_with_text)), _settings())
    assert verdict.kind == "digital"
    assert not verdict.needs_ocr
    assert verdict.needs_text_layer


def test_a_full_page_image_with_no_text_is_scanned() -> None:
    def build(page: pymupdf.Page) -> None:
        page.insert_image(page.rect, stream=_photo_bytes())

    verdict = classify_page(measure_page(_page(build)), _settings())
    assert verdict.kind == "scanned"
    assert verdict.needs_ocr
    assert not verdict.has_prior_text


def test_a_scan_carrying_a_prior_ocr_layer_is_still_scanned() -> None:
    """The case that matters most, and the one nothing downstream could catch.

    A scanned page arrives with a text layer someone else's OCR produced. The
    text can measure perfectly healthy while being wrong, so the picture — not
    the text — has to decide.
    """

    def build(page: pymupdf.Page) -> None:
        page.insert_image(page.rect, stream=_photo_bytes())
        _fill_with_text(page)

    verdict = classify_page(measure_page(_page(build)), _settings())
    assert verdict.kind == "scanned"
    assert verdict.has_prior_text
    assert "prior text layer" in verdict.reason


def test_prior_ocr_can_be_trusted_by_configuration() -> None:
    def build(page: pymupdf.Page) -> None:
        page.insert_image(page.rect, stream=_photo_bytes())
        _fill_with_text(page)

    verdict = classify_page(measure_page(_page(build)), _settings(trust_prior_ocr=True))
    assert verdict.kind == "digital"
    assert verdict.has_prior_text


def test_a_partial_image_beside_good_text_is_hybrid() -> None:
    def build(page: pymupdf.Page) -> None:
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 500), PROSE * 8, fontsize=10)
        page.insert_image(pymupdf.Rect(50, 520, 545, 800), stream=_photo_bytes())

    verdict = classify_page(measure_page(_page(build)), _settings())
    assert verdict.kind == "hybrid"
    assert verdict.needs_ocr and verdict.needs_text_layer


def test_a_healthy_looking_but_garbled_text_layer_goes_to_ocr() -> None:
    def build(page: pymupdf.Page) -> None:
        page.insert_textbox(
            pymupdf.Rect(50, 50, 545, 800),
            "GlobalAMLCFTCPFandKYCPolicyapprovedbytheBoardofDirectors" * 40,
            fontsize=10,
        )

    signals = measure_page(_page(build))
    assert signals.char_density > 12  # plenty of text, so density alone says digital
    assert classify_page(signals, _settings()).kind == "scanned"


def test_thresholds_come_from_settings_not_constants() -> None:
    signals = measure_page(_page(_fill_with_text))
    assert classify_page(signals, _settings()).kind == "digital"
    # Demand more text than any page could carry and the same page reroutes.
    assert classify_page(signals, _settings(min_char_density=10_000)).kind == "scanned"


@pytest.mark.parametrize("density", [0.0, 2.9])
def test_the_empty_threshold_is_respected(density: float) -> None:
    verdict = classify_page(measure_page(_page(lambda p: None)), _settings(empty_char_density=density))
    # A truly blank page has zero density, so a threshold at or below it means
    # the page is no longer "empty" and must be looked at instead of skipped.
    assert verdict.kind == ("empty" if density > 0 else "scanned")
