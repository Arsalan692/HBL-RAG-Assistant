"""Runs every available OCR engine over the same pages and writes the output
somewhere a person can read it side by side.

The decision this feeds is not made here. There is no score, no ranking, no
winner — the harness renders identical inputs, runs whatever engines the
machine actually has, records what came out and what it cost, and stops. A
human reads the markdown and decides. That is deliberate: the failure that
matters on this corpus is an engine flattening a table into fluent prose, and
every automatic metric rates fluent prose highly.

What it *does* measure is the cheap, unambiguous stuff — seconds per page,
characters produced, tables detected, engine warnings — because those catch the
gross failures without anyone reading five files to notice them.

Designed to survive a partial install. On the air-gapped workstation some
engines will be missing and some will be missing only their weights. A run
records that as a result and continues to the next engine; it never aborts.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from app.config import Settings
from app.errors import HblError
from app.ingest.bench import BenchPick
from app.ingest.render import render_page
from app.logging_config import get_logger
from app.providers import registry
from app.providers.base import OcrResult, PageRef

log = get_logger(__name__)

#: Engines to try when none are named. The `vlm` entries come first because they
#: need nothing staged on the air-gapped machine — all three models are already
#: pulled — so they are the only ones guaranteed to produce a result on a first
#: run. Two sizes of the same model are included on purpose: if 3B reads these
#: pages as well as 7B it halves the OCR pass and frees 3 GB of VRAM.
DEFAULT_ENGINES: tuple[str, ...] = (
    "vlm=qwen2.5vl:7b",
    "vlm=qwen2.5vl:3b",
    "vlm=glm-ocr:latest",
    "docling",
    "surya",
    "mineru",
)


def parse_engine(spec: str) -> tuple[str, str]:
    """Split `vlm=qwen2.5vl:3b` into an engine name and a model override.

    The model has to be selectable per run, not just per `.env`, because the
    interesting comparison for the VLM candidates is between models rather than
    between engines — same code path, very different reading ability. Splitting
    on the first `=` keeps Ollama's own `name:tag` colons intact.
    """
    name, _, model = spec.partition("=")
    return name.strip(), model.strip()


@dataclass
class EngineRun:
    """One engine's attempt at one page. Failure is a result, not an exception."""

    engine: str
    document: str
    page_number: int
    ok: bool
    seconds: float = 0.0
    characters: int = 0
    tables: int = 0
    warnings: tuple[str, ...] = field(default=())
    error: str = ""
    output_path: str = ""


@dataclass
class BenchReport:
    started_at: str
    dpi: int
    pages: list[dict[str, object]]
    engines_attempted: list[str]
    engines_unavailable: dict[str, str]
    runs: list[EngineRun]
    output_dir: str


def _load_engine(name: str, model: str, settings: Settings):
    """Construct one engine, or explain in a sentence why it cannot be.

    Engines are selected by name rather than by `settings.ocr.provider` because
    the whole point of the bench is to run several in one pass, before anything
    has been chosen.
    """
    update: dict[str, object] = {"provider": name}
    if model:
        update["model"] = model
    scoped = settings.model_copy(update={"ocr": settings.ocr.model_copy(update=update)})
    return registry.load_ocr(scoped)


def run_bench(
    picks: Sequence[BenchPick],
    settings: Settings,
    *,
    engines: Sequence[str] = DEFAULT_ENGINES,
    dpi: int | None = None,
    out_dir: Path | None = None,
    overwrite: bool = False,
) -> BenchReport:
    """Render the chosen pages once, then read them with each engine in turn."""
    dpi = dpi or settings.ingest.render_dpi
    image_dir = settings.paths.page_image_dir
    assert image_dir is not None  # filled by PathSettings._derive
    out_dir = out_dir or (settings.paths.parsed_dir / "bench")  # type: ignore[operator]
    out_dir.mkdir(parents=True, exist_ok=True)

    # Render first, and once. Every engine must see byte-identical input or the
    # comparison measures the renderer.
    refs: list[tuple[BenchPick, PageRef]] = []
    for pick in picks:
        rendered = render_page(
            pick.document, pick.page_number, dpi=dpi, out_dir=image_dir, overwrite=overwrite
        )
        refs.append(
            (
                pick,
                PageRef(
                    pdf_path=pick.document,
                    page_number=pick.page_number,
                    image_path=rendered.image_path,
                    # The render may have been capped to the page's own
                    # resolution; report what was actually produced.
                    dpi=rendered.dpi,
                    languages=tuple(settings.ocr.language_list),
                ),
            )
        )

    runs: list[EngineRun] = []
    unavailable: dict[str, str] = {}

    for spec in engines:
        name, model = parse_engine(spec)
        label = spec if model else name
        try:
            engine = _load_engine(name, model, settings)
        except HblError as exc:
            unavailable[label] = str(exc)
            log.warning("bench.engine_unavailable", extra={"engine": label, "reason": str(exc)})
            continue

        # A model that is not pulled fails identically on all five pages and
        # wastes a timeout each time. Ask once, up front, if the engine can say.
        probe = getattr(engine, "probe", None)
        if probe is not None:
            ok, detail = probe()
            if not ok:
                unavailable[label] = detail
                log.warning("bench.engine_unavailable", extra={"engine": label, "reason": detail})
                continue

        log.info("bench.engine_start", extra={"engine": label, "pages": len(refs)})
        for pick, ref in refs:
            runs.append(_run_one(label, engine, pick, ref, out_dir))

    report = BenchReport(
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        dpi=dpi,
        pages=[
            {
                "category": p.category,
                "document": p.document.name,
                "page": p.page_number,
                "why": p.rationale,
            }
            for p in picks
        ],
        engines_attempted=list(engines),
        engines_unavailable=unavailable,
        runs=runs,
        output_dir=str(out_dir),
    )
    _write_report(report, out_dir)
    return report


def _run_one(name: str, engine, pick: BenchPick, ref: PageRef, out_dir: Path) -> EngineRun:
    started = time.perf_counter()
    try:
        result: OcrResult = engine.recognise(ref)
    except Exception as exc:  # engines fail in library-specific ways
        log.warning(
            "bench.page_failed",
            extra={"engine": name, "page": ref.page_number, "error": str(exc)},
        )
        return EngineRun(
            engine=name,
            document=pick.document.name,
            page_number=ref.page_number,
            ok=False,
            seconds=round(time.perf_counter() - started, 2),
            error=str(exc)[:400],
        )

    path = _write_page(name, pick, result, out_dir)
    return EngineRun(
        engine=name,
        document=pick.document.name,
        page_number=ref.page_number,
        ok=True,
        seconds=round(result.duration_s or (time.perf_counter() - started), 2),
        characters=len(result.markdown),
        tables=result.table_count,
        warnings=result.warnings,
        output_path=path.name,
    )


def _write_page(name: str, pick: BenchPick, result: OcrResult, out_dir: Path) -> Path:
    """One markdown file per engine per page, named so they sort together.

    Sorted by category first so the five files for a single page sit adjacent in
    a directory listing — the comparison is between engines on one page, not
    between pages for one engine.
    """
    # `vlm=qwen2.5vl:7b` is a fine label and an illegal Windows filename — both
    # `=` and `:` have to go, and `:` silently truncates rather than erroring.
    safe_engine = name.replace("=", "-").replace(":", "-").replace("/", "-")
    stem = f"{pick.category.replace(' ', '-')}_p{pick.page_number:04d}_{safe_engine}"
    path = out_dir / f"{stem}.md"
    header = (
        f"<!-- engine: {result.engine} | {pick.document.name} p.{pick.page_number} "
        f"| {result.duration_s:.1f}s | {len(result.markdown)} chars "
        f"| {result.table_count} table(s) -->\n\n"
    )
    if result.warnings:
        header += "<!-- warnings: " + "; ".join(result.warnings) + " -->\n\n"
    path.write_text(header + result.markdown + "\n", encoding="utf-8")
    return path


def _write_report(report: BenchReport, out_dir: Path) -> None:
    (out_dir / "bench-report.json").write_text(
        json.dumps(asdict(report), indent=2, default=str), encoding="utf-8"
    )
