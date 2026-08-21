"""Tests for rendering and the OCR bench harness.

No engine is installed in CI and none should need to be. What is tested here is
the harness's own behaviour: that it renders identical input once, that a
missing engine is a recorded result rather than a crash, and that its output
lands somewhere legal on Windows.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.config import Settings
from app.errors import ProviderUnavailable
from app.ingest.bench import BenchPick
from app.ingest.benchmark import parse_engine, run_bench
from app.ingest.render import effective_dpi, image_path_for, render_page
from app.providers.base import OcrResult, PageRef


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    """A two-page PDF with an awkward filename, as the real corpus has."""
    path = tmp_path / "Compliance Risk  Policy & Program (2).pdf"
    doc = pymupdf.open()
    for text in ("Clause 2.1.3 Enhanced due diligence", "Annexure B"):
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 300), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.paths.page_image_dir = tmp_path / "images"
    s.paths.parsed_dir = tmp_path / "parsed"
    s.paths.documents_dir = tmp_path
    return s


# --- rendering ---------------------------------------------------------------


def test_rendering_produces_a_png_named_for_document_page_and_dpi(pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "images"
    rendered = render_page(pdf, 2, dpi=150, out_dir=out)

    assert rendered.image_path.exists()
    assert rendered.image_path.suffix == ".png"
    assert "p0002" in rendered.image_path.name
    assert "150dpi" in rendered.image_path.name
    assert rendered.page_number == 2


def test_render_filenames_survive_windows(pdf: Path, tmp_path: Path) -> None:
    """Corpus names contain spaces, ampersands and parentheses."""
    name = image_path_for(pdf, 1, 300, tmp_path).name
    assert not set(name) & set(' &()<>:"|?*')


def test_higher_dpi_produces_a_bigger_image(pdf: Path, tmp_path: Path) -> None:
    low = render_page(pdf, 1, dpi=100, out_dir=tmp_path)
    high = render_page(pdf, 1, dpi=300, out_dir=tmp_path)
    assert high.width > low.width * 2


def test_a_vector_page_is_rendered_at_the_dpi_asked_for(pdf: Path) -> None:
    """No raster means the text is vector, so the requested dpi is real detail."""
    with pymupdf.open(pdf) as doc:
        assert effective_dpi(doc[0], 300) == 300


def test_a_coarse_scan_is_not_rendered_beyond_its_own_resolution(tmp_path: Path) -> None:
    """A 100 dpi scan drawn at 300 dpi is nine times the pixels and no more detail.

    Vision models are charged per pixel, so the interpolation is paid for nine
    times over. Measured on the real corpus, a 100 dpi page rendered at 300 is
    8.7 megapixels carrying 1.0 megapixel of information.
    """
    path = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # 826 pixels across a 595pt page = 826 / (595/72) = 100 dpi.
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 826, 1169), False)
    pix.clear_with(200)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    doc.save(path)
    doc.close()

    with pymupdf.open(path) as scanned:
        assert effective_dpi(scanned[0], 300) == 150  # the floor, not 300
        assert effective_dpi(scanned[0], 300, floor=100) == 100


def test_a_page_number_outside_the_document_is_refused(pdf: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="has 2 pages"):
        render_page(pdf, 99, dpi=72, out_dir=tmp_path)


# --- engine specs ------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("vlm", ("vlm", "")),
        ("docling", ("docling", "")),
        # Ollama tags contain colons, so only the first `=` may be split on.
        ("vlm=qwen2.5vl:7b", ("vlm", "qwen2.5vl:7b")),
        ("vlm=glm-ocr:latest", ("vlm", "glm-ocr:latest")),
    ],
)
def test_engine_specs_split_on_the_first_equals(spec: str, expected: tuple[str, str]) -> None:
    assert parse_engine(spec) == expected


# --- the harness -------------------------------------------------------------


class _FakeEngine:
    """Stands in for a real engine. Records what it was asked to read."""

    name = "fake"

    def __init__(self) -> None:
        self.seen: list[PageRef] = []

    def recognise(self, page: PageRef) -> OcrResult:
        self.seen.append(page)
        return OcrResult(
            markdown="# Clause 2.1.3\n\n| Risk | Tier |\n|---|---|\n| High | 1 |",
            engine="fake",
            page_number=page.page_number,
            table_count=1,
            duration_s=0.5,
        )


def test_a_missing_engine_is_recorded_not_raised(pdf: Path, settings: Settings) -> None:
    """The workstation will have some engines and not others. A run must finish."""
    picks = [BenchPick("full scan", pdf, 1, 1.0, "test")]

    report = run_bench(picks, settings, engines=["surya", "mineru"])

    assert report.runs == []
    assert set(report.engines_unavailable) == {"surya", "mineru"}
    assert Path(report.output_dir, "bench-report.json").exists()


def test_every_engine_reads_the_same_rendered_file(
    pdf: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The comparison is between readers, so the input must not vary."""
    engines = {"a": _FakeEngine(), "b": _FakeEngine()}
    monkeypatch.setattr(
        "app.ingest.benchmark._load_engine", lambda name, model, s: engines[name]
    )

    picks = [BenchPick("dense table", pdf, 1, 1.0, "test")]
    report = run_bench(picks, settings, engines=["a", "b"], dpi=100)

    read_by_a = engines["a"].seen[0].image_path
    read_by_b = engines["b"].seen[0].image_path
    assert read_by_a == read_by_b
    assert read_by_a is not None and read_by_a.exists()
    assert len(report.runs) == 2
    assert all(run.ok and run.tables == 1 for run in report.runs)


def test_one_markdown_file_per_engine_per_page_with_a_legal_name(
    pdf: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.ingest.benchmark._load_engine", lambda name, model, s: _FakeEngine()
    )

    picks = [BenchPick("poor scan", pdf, 1, 1.0, "test")]
    report = run_bench(picks, settings, engines=["vlm=qwen2.5vl:7b"], dpi=100)

    written = sorted(Path(report.output_dir).glob("*.md"))
    assert len(written) == 1
    # `vlm=qwen2.5vl:7b` is a legal label and an illegal Windows filename.
    assert not set(written[0].name) & set('=:<>"|?*')
    body = written[0].read_text(encoding="utf-8")
    assert "Clause 2.1.3" in body
    assert "engine:" in body  # provenance header


def test_an_engine_that_throws_mid_page_is_reported_and_the_run_continues(
    pdf: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Broken:
        name = "broken"

        def recognise(self, page: PageRef) -> OcrResult:
            raise ProviderUnavailable("weights were never staged")

    built = {"broken": _Broken(), "working": _FakeEngine()}
    monkeypatch.setattr(
        "app.ingest.benchmark._load_engine", lambda name, model, s: built[name]
    )

    picks = [BenchPick("mixed", pdf, 1, 1.0, "test")]
    report = run_bench(picks, settings, engines=["broken", "working"], dpi=100)

    assert len(report.runs) == 2
    broken, working = report.runs
    assert not broken.ok and "never staged" in broken.error
    assert working.ok


def test_an_engine_failing_its_probe_is_skipped_before_wasting_five_timeouts(
    pdf: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _NotPulled(_FakeEngine):
        def probe(self) -> tuple[bool, str]:
            return False, "'qwen2.5vl:7b' is not pulled"

    engine = _NotPulled()
    monkeypatch.setattr("app.ingest.benchmark._load_engine", lambda name, model, s: engine)

    picks = [BenchPick(c, pdf, 1, 1.0, "test") for c in ("full scan", "poor scan")]
    report = run_bench(picks, settings, engines=["vlm"], dpi=100)

    assert report.runs == []
    assert engine.seen == []
    assert "not pulled" in report.engines_unavailable["vlm"]
