"""Cheap, explainable measurements of a single PDF page.

Nothing here decides anything — `router.py` does that. These functions only
answer factual questions about a page: how much text came out, how much of the
page is covered by a raster image, and whether the text that came out looks like
language at all.

They are deliberately dependency-light and deterministic. Every number below is
something a person can check by eye against the page, which matters because the
routing decision is the one thing in the pipeline nobody can debug after the
fact — a page sent down the wrong branch just produces quietly wrong text.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass

import pymupdf

# Coverage is measured by marking cells of a grid laid over the page rather than
# by summing rectangle areas, because image rectangles overlap constantly —
# a scanned page is often one full-page raster with a smaller logo on top, and
# naive area summing reports 130% coverage.
_GRID = 48

#: Characters that mean the text layer is damaged rather than merely unusual:
#: the replacement character, C0/C1 controls other than whitespace, and the
#: private-use planes that subset fonts fall back to when they have no
#: ToUnicode map.
_BROKEN_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cn", "Cs"})

_VOWELS = frozenset("aeiouAEIOU")

#: Smallest image, in native pixels per side, that could carry readable text.
#: Several documents in this corpus are Word exports that place a 2x2-pixel
#: coloured image behind every line of text as a highlight fill. Drawn out to
#: line width they look like heavy raster coverage and would send a perfectly
#: clean digital page to OCR — so an image is only content if it has enough
#: pixels to hold any. A 64x64 image is already too small for a legible word.
_MIN_RASTER_PIXELS = 64


@dataclass(frozen=True, slots=True)
class TextQuality:
    """Why we do or do not believe a page's extracted text."""

    #: 0.0 = reads like language, 1.0 = certainly junk.
    score: float
    broken_ratio: float
    space_ratio: float
    vowel_ratio: float
    reason: str


@dataclass(frozen=True, slots=True)
class PageSignals:
    """Everything measured about one page, before any judgement is applied."""

    page_number: int  # 1-based, matching what a reader sees
    width: float
    height: float

    char_count: int
    #: Characters per square inch of page. Normalising by area matters because
    #: the corpus mixes A4 body pages with oversized fold-out tables, and a raw
    #: character count would call the fold-out sparse. For scale: A4 is 96.7 in²,
    #: so a full page of body prose lands around 28–35 and a heading-only page
    #: around 2–5.
    char_density: float

    image_count: int
    #: Images too small in native pixels to hold content, discarded before
    #: coverage was measured. Reported only so a surprising verdict can be
    #: traced back; nothing reads it.
    decorative_image_count: int
    #: Fraction of the page covered by raster images, overlap-corrected.
    raster_coverage: float
    #: Fraction of the page covered by text blocks.
    text_coverage: float
    #: True when a single image covers most of the page — the signature of a
    #: scan, as opposed to a digital page that merely contains figures.
    has_full_page_raster: bool
    #: Effective resolution of the largest image: its pixel width against the
    #: width it is drawn at. 300 is a clean scan, 150 is a photocopy, below 120
    #: is where OCR engines start to disagree with each other. 0 when there is
    #: no raster. Not used in routing — it is how the bench-off finds a
    #: genuinely poor scan without anyone paging through the corpus by eye.
    raster_dpi: float

    quality: TextQuality

    @property
    def garble(self) -> float:
        return self.quality.score


def _grid_coverage(rects: list[pymupdf.Rect], page: pymupdf.Rect) -> float:
    """Fraction of `page` covered by `rects`, counting overlaps only once."""
    if not rects or page.is_empty:
        return 0.0

    cell_w = page.width / _GRID
    cell_h = page.height / _GRID
    if cell_w <= 0 or cell_h <= 0:
        return 0.0

    filled: set[int] = set()
    for rect in rects:
        clipped = rect & page
        if clipped.is_empty:
            continue
        col0 = max(0, int((clipped.x0 - page.x0) / cell_w))
        col1 = min(_GRID - 1, int((clipped.x1 - page.x0 - 1e-6) / cell_w))
        row0 = max(0, int((clipped.y0 - page.y0) / cell_h))
        row1 = min(_GRID - 1, int((clipped.y1 - page.y0 - 1e-6) / cell_h))
        for row in range(row0, row1 + 1):
            base = row * _GRID
            filled.update(range(base + col0, base + col1 + 1))

    return len(filled) / (_GRID * _GRID)


def assess_text(text: str) -> TextQuality:
    """Judge whether extracted text is language or a broken glyph mapping.

    The failure this exists to catch: a PDF whose fonts are subset without a
    ToUnicode map extracts *something* for every glyph, so character count looks
    healthy, but the characters are wrong. Such a page must be OCR'd despite
    having a text layer, and character count alone will never say so.

    Three independent signals, combined by taking the worst. Any one of them
    firing is enough — they fail in different ways and rarely fire together.
    """
    stripped = text.strip()
    if len(stripped) < 40:
        # Too little to judge. Say "clean" and let the density test decide;
        # calling a near-empty page garbled would send every cover sheet to OCR.
        return TextQuality(0.0, 0.0, 0.0, 0.0, "too short to assess")

    broken = sum(1 for ch in stripped if unicodedata.category(ch) in _BROKEN_CATEGORIES and not ch.isspace())
    broken += stripped.count("�")
    broken_ratio = broken / len(stripped)

    spaces = sum(1 for ch in stripped if ch.isspace())
    space_ratio = spaces / len(stripped)

    letters = [ch for ch in stripped if ch.isalpha()]
    vowel_ratio = (sum(1 for ch in letters if ch in _VOWELS) / len(letters)) if letters else 0.0

    # Undecodable glyphs are conclusive — there is no legitimate document that
    # is 5% control characters.
    broken_penalty = min(1.0, broken_ratio * 20.0)

    # English prose runs 12–20% whitespace. Broken CID extraction typically
    # produces a single unbroken run with no spaces at all.
    space_penalty = 0.0 if space_ratio >= 0.08 else min(1.0, (0.08 - space_ratio) / 0.08)

    # English is ~38% vowels among letters. Wrong glyph mappings scatter this.
    # The band is generous because tables of codes and abbreviations legitimately
    # run vowel-poor, and we would rather miss a garbled page than OCR a table.
    if not letters:
        vowel_penalty = 0.0
    else:
        deviation = abs(vowel_ratio - 0.38)
        vowel_penalty = 0.0 if deviation <= 0.18 else min(1.0, (deviation - 0.18) / 0.18)

    score = max(broken_penalty, space_penalty, vowel_penalty)
    if score == broken_penalty and score > 0:
        reason = f"{broken_ratio:.1%} undecodable characters"
    elif score == space_penalty and score > 0:
        reason = f"only {space_ratio:.1%} whitespace"
    elif score > 0:
        reason = f"vowel ratio {vowel_ratio:.0%} is unlike English"
    else:
        reason = "reads as language"

    return TextQuality(score, broken_ratio, space_ratio, vowel_ratio, reason)


def measure_page(page: pymupdf.Page) -> PageSignals:
    """Measure one page. No I/O beyond what PyMuPDF already has in memory."""
    rect = page.rect
    text = page.get_text("text")

    # 72 PostScript points to the inch, so area in square inches.
    area_in2 = max((rect.width / 72.0) * (rect.height / 72.0), 1e-6)

    image_rects: list[pymupdf.Rect] = []
    decorative = 0
    largest_area = 0.0
    raster_dpi = 0.0
    for info in page.get_image_info():
        bbox = info.get("bbox")
        if not bbox:
            continue
        pixels_w, pixels_h = info.get("width", 0), info.get("height", 0)
        if pixels_w < _MIN_RASTER_PIXELS or pixels_h < _MIN_RASTER_PIXELS:
            decorative += 1
            continue
        drawn = pymupdf.Rect(bbox)
        image_rects.append(drawn)
        area = drawn.get_area()
        if area > largest_area and drawn.width > 1:
            largest_area = area
            raster_dpi = pixels_w / (drawn.width / 72.0)

    text_rects = [
        pymupdf.Rect(block[:4])
        for block in page.get_text("blocks")
        if len(block) > 6 and block[6] == 0
    ]

    raster_coverage = _grid_coverage(image_rects, rect)
    page_area = max(rect.get_area(), 1e-6)
    has_full_page_raster = any((r & rect).get_area() / page_area >= 0.60 for r in image_rects)

    return PageSignals(
        page_number=page.number + 1,
        width=rect.width,
        height=rect.height,
        char_count=len(text.strip()),
        char_density=len(text.strip()) / area_in2,
        image_count=len(image_rects),
        decorative_image_count=decorative,
        raster_coverage=raster_coverage,
        text_coverage=_grid_coverage(text_rects, rect),
        has_full_page_raster=has_full_page_raster,
        raster_dpi=round(raster_dpi, 1),
        quality=assess_text(text),
    )


def table_likeness(page: pymupdf.Page) -> float:
    """A rough 0–1 score for "this page is mostly a table".

    Used only to pick representative pages for the OCR bench-off, never in
    routing. Tables are where OCR engines differ most, so the bench needs a
    dense one, and finding it by eye across 1,300 pages is not reasonable.

    Two structural signals: how many horizontal and vertical rules the page
    draws, and how strongly text blocks align into shared columns.
    """
    rect = page.rect
    if rect.is_empty:
        return 0.0

    horizontal = vertical = 0
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] == "l":  # a line
                start, end = item[1], item[2]
                if abs(start.y - end.y) < 1.0 and abs(start.x - end.x) > 30:
                    horizontal += 1
                elif abs(start.x - end.x) < 1.0 and abs(start.y - end.y) > 30:
                    vertical += 1
            elif item[0] == "re":  # a rectangle: contributes both
                box = item[1]
                if box.width > 30 and box.height > 30:
                    horizontal += 2
                    vertical += 2

    rule_score = min(1.0, math.log1p(horizontal + vertical) / math.log(60))

    # Column alignment: bucket text-block left edges and see how concentrated
    # they are. Prose has one or two left edges; a table has several, each used
    # by many rows.
    lefts: dict[int, int] = {}
    blocks = [b for b in page.get_text("blocks") if len(b) > 6 and b[6] == 0]
    for block in blocks:
        bucket = int(block[0] / 6)  # ~6pt tolerance
        lefts[bucket] = lefts.get(bucket, 0) + 1

    repeated_columns = sum(1 for count in lefts.values() if count >= 3)
    column_score = min(1.0, repeated_columns / 5.0)

    return round(0.6 * rule_score + 0.4 * column_score, 3)
