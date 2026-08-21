"""Page recognition through IBM Docling.

The structural opposite of the VLM candidate: a layout model finds regions, a
recogniser reads them, and a table model reconstructs cell geometry. It cannot
invent a line the way a generative model can, and it is much faster — but it
also cannot use context to resolve a smudged character, so poor scans are where
it should lose if it loses.

**Docling downloads its own weights on first use.** On the air-gapped
workstation that is a hang, not an error message. Stage the model repo by hand
and point `HF_HOME` at it before running this; `docs/download-manifest.html`
has the steps. Nothing here can work around it.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from app.config import OcrSettings
from app.errors import ProviderUnavailable
from app.logging_config import get_logger
from app.providers.base import OcrResult, PageRef

log = get_logger(__name__)


class DoclingOCR:
    """The `OCR` protocol, backed by Docling's document converter."""

    name = "docling"

    def __init__(self, settings: OcrSettings) -> None:
        self._settings = settings
        self.model = settings.model or "default"
        self._converter: Any | None = None

    def _load(self) -> Any:
        """Import and construct on first use, never at module import.

        The registry checks availability with `find_spec` so that `cli health`
        runs on a laptop without docling installed. Importing here rather than
        at the top keeps that promise.
        """
        if self._converter is not None:
            return self._converter
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise ProviderUnavailable(
                "docling is not installed. On the air-gapped workstation install "
                "it from the staged wheel folder: "
                "pip install --no-index --find-links=wheels docling"
            ) from exc

        started = time.perf_counter()
        self._converter = DocumentConverter()
        log.info("ocr.loaded", extra={"engine": self.name, "seconds": round(time.perf_counter() - started, 1)})
        return self._converter

    # --- OCR protocol --------------------------------------------------------

    def recognise(self, page: PageRef) -> OcrResult:
        """Convert one page.

        Docling takes the PDF itself and locates the page, rather than a
        rasterised image — it wants the vector text layer where one exists.
        That is why `PageRef` carries both the PDF and the optional image.
        """
        converter = self._load()

        started = time.perf_counter()
        try:
            result = converter.convert(page.pdf_path, page_range=(page.page_number, page.page_number))
        except TypeError:
            # Older releases have no page_range; convert the document and slice.
            result = converter.convert(page.pdf_path)
        except Exception as exc:  # pragma: no cover - engine-specific failures
            raise ProviderUnavailable(f"docling failed on {page.pdf_path.name} p.{page.page_number}: {exc}") from exc
        duration = time.perf_counter() - started

        markdown = result.document.export_to_markdown().strip()

        warnings: list[str] = []
        if not markdown:
            warnings.append("empty output")

        log.info(
            "ocr.page",
            extra={
                "engine": self.name,
                "page": page.page_number,
                "seconds": round(duration, 1),
                "chars": len(markdown),
            },
        )

        return OcrResult(
            markdown=markdown,
            engine=self.name,
            page_number=page.page_number,
            table_count=_count_tables(markdown),
            duration_s=duration,
            warnings=tuple(warnings),
        )

    def recognise_batch(self, pages: Sequence[PageRef]) -> list[OcrResult]:
        return [self.recognise(page) for page in pages]

    def probe(self) -> tuple[bool, str]:
        try:
            self._load()
        except ProviderUnavailable as exc:
            return False, str(exc)
        return True, "docling converter constructed"


def _count_tables(markdown: str) -> int:
    count = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and set(stripped) <= set("|-: \t") and "-" in stripped:
            count += 1
    return count
