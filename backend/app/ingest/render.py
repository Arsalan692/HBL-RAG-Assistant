"""Turning a PDF page into an image an OCR engine can look at.

Kept separate from the engines because every engine wants the same thing and
they should all get *exactly* the same thing. If Surya rendered at 200 dpi and
the VLM at 300, the bench-off would be comparing renderers as much as readers.

Rendered pages are as confidential as the PDFs they come from. They land under
`data/page_images/`, which is gitignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.logging_config import get_logger

log = get_logger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: Never render a scan below this, however coarse the source. Recognisers are
#: trained on roughly this scale and small type falls apart under it.
MIN_DPI = 150


def effective_dpi(page: pymupdf.Page, requested: int, *, floor: int = MIN_DPI) -> int:
    """The highest resolution worth rendering this page at.

    A page whose content is a 100 dpi scan holds 100 dpi of information. Drawing
    it at 300 produces nine times the pixels and not one extra glyph — but a
    vision model is charged per pixel, so it pays nine times over for the
    interpolation. Measured on this corpus: a 100 dpi page rendered at 300 dpi
    is 8.7 megapixels carrying 1.0 megapixel of detail.

    Pages with no raster are left alone. Their text is vector, genuinely
    resolution-independent, and the requested dpi is real detail.
    """
    native = 0.0
    for info in page.get_image_info():
        bbox = info.get("bbox")
        width_px = info.get("width", 0)
        if not bbox or width_px < 64:
            continue
        drawn = pymupdf.Rect(bbox)
        # Only a page-covering raster describes the page's own resolution; a
        # logo says nothing about the body text beside it.
        if drawn.get_area() / max(page.rect.get_area(), 1e-6) >= 0.60 and drawn.width > 1:
            native = max(native, width_px / (drawn.width / 72.0))

    if native <= 0:
        return requested
    return max(floor, min(requested, int(round(native))))


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """One page as a PNG on disk, with what it came from."""

    pdf_path: Path
    page_number: int
    image_path: Path
    dpi: int
    width: int
    height: int


def _slug(name: str) -> str:
    """A filename-safe stem. Document names here contain spaces, commas and
    parentheses, which survive on Windows but make shell quoting miserable."""
    return _UNSAFE.sub("-", Path(name).stem).strip("-")[:60]


def image_path_for(pdf_path: Path, page_number: int, dpi: int, out_dir: Path) -> Path:
    """Deterministic, so re-running overwrites instead of accumulating."""
    return out_dir / f"{_slug(pdf_path.name)}_p{page_number:04d}_{dpi}dpi.png"


def render_page(
    pdf_path: Path,
    page_number: int,
    *,
    dpi: int,
    out_dir: Path,
    overwrite: bool = False,
    cap_to_native: bool = True,
) -> RenderedPage:
    """Rasterise one 1-based page to PNG.

    Greyscale is deliberately *not* used: these scans include coloured stamps
    and highlighted table headers, and at least one engine reads colour as a
    cue for structure. PNG rather than JPEG because JPEG artefacts around small
    type are exactly the thing that separates a good engine from a bad one, and
    introducing them in our own pipeline would be measuring the wrong variable.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    target = image_path_for(pdf_path, page_number, dpi, out_dir)

    with pymupdf.open(pdf_path) as doc:
        if not 1 <= page_number <= doc.page_count:
            raise ValueError(
                f"{pdf_path.name} has {doc.page_count} pages; asked for page {page_number}"
            )
        page = doc[page_number - 1]
        requested = dpi
        dpi = effective_dpi(page, dpi) if cap_to_native else dpi
        # The filename carries the dpi actually used, so a capped render never
        # collides with an uncapped one of the same page.
        target = image_path_for(pdf_path, page_number, dpi, out_dir)

        if target.exists() and not overwrite:
            pix = page.get_pixmap(dpi=dpi, alpha=False)  # for the dimensions only
            log.debug("render.reused", extra={"path": str(target)})
            return RenderedPage(pdf_path, page_number, target, dpi, pix.width, pix.height)

        pix = page.get_pixmap(dpi=dpi, alpha=False)
        pix.save(target)

    log.info(
        "render.page",
        extra={
            "document": pdf_path.name,
            "page": page_number,
            "dpi": dpi,
            "requested_dpi": requested,
            "capped": dpi < requested,
            "pixels": f"{pix.width}x{pix.height}",
            "megapixels": round(pix.width * pix.height / 1e6, 1),
        },
    )
    return RenderedPage(pdf_path, page_number, target, dpi, pix.width, pix.height)
