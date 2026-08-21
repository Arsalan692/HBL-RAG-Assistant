"""The headless entry point.

Every heavy operation hangs off this, because ingestion runs on the office GPU
workstation over a terminal and must never need a browser. Commands write
results to **stdout**; logs go to stderr, so `--json` output stays pipeable.

    python -m app.cli health
    python -m app.cli health --probe
    python -m app.cli providers
    python -m app.cli paths --create
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any, Sequence

from app import __version__
from app.config import ROOT_DIR, Settings, get_settings
from app.errors import HblError
from app.logging_config import configure_logging
from app.providers import registry
from app.providers.base import INTERFACES, ProviderStatus

# What each provider state looks like in the terminal. `declared` and
# `unchosen` are the expected answers right now, not failures — Phase 00 builds
# the contracts, later phases fill them in.
_STATE_LABEL = {
    "ready": "ready",
    "declared": "declared",
    "unchosen": "not chosen",
    "missing-deps": "missing deps",
    "unknown": "UNKNOWN",
}


def _table(rows: Sequence[Sequence[str]], indent: str = "  ") -> str:
    """Left-align every column but the last, which is free to be ragged."""
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [list(row) + [""] * (width - len(row)) for row in rows]
    sizes = [max(len(row[i]) for row in padded) for i in range(width)]
    lines = []
    for row in padded:
        cells = [row[i].ljust(sizes[i]) for i in range(width - 1)] + [row[-1]]
        lines.append(indent + "  ".join(cells).rstrip())
    return "\n".join(lines)


def _relative(path: Path) -> str:
    """Paths under the repository shown relative to it — shorter, and machine-neutral."""
    try:
        return "./" + path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return str(path)


def _path_rows(settings: Settings) -> list[list[str]]:
    """Every location the backend cares about, directories plus the registry file."""
    entries = dict(settings.paths.directories())
    entries["registry db"] = settings.paths.registry_db  # type: ignore[assignment]
    return [
        [label, _relative(path), "" if path.exists() else "missing"]
        for label, path in entries.items()
    ]


def _status_payload(status: ProviderStatus) -> dict[str, Any]:
    return {
        "interface": status.interface,
        "provider": status.name,
        "model": status.model or None,
        "state": status.state,
        "detail": status.detail,
        "target": status.target or None,
        "missing": list(status.missing),
    }


# --- health ------------------------------------------------------------------


def cmd_health(args: argparse.Namespace, settings: Settings) -> int:
    statuses = registry.status_all(settings)

    probes: dict[str, tuple[bool, str]] = {}
    if args.probe:
        probes = _probe(settings, statuses)

    if args.json:
        print(
            json.dumps(
                {
                    "version": __version__,
                    "python": platform.python_version(),
                    "root": str(ROOT_DIR),
                    "settings": json.loads(settings.model_dump_json()),
                    "providers": [_status_payload(s) for s in statuses],
                    "probes": {k: {"ok": ok, "detail": detail} for k, (ok, detail) in probes.items()},
                },
                indent=2,
                default=str,
            )
        )
        return 0 if all(ok for ok, _ in probes.values()) else 1

    runtime, paths = settings.runtime, settings.paths

    print(f"\nHBL RAG Assistant — backend {__version__}")
    print(
        _table(
            [
                ["python", f"{platform.python_version()} ({platform.python_implementation()}, {sys.platform})"],
                ["environment", runtime.app_env],
                ["device", runtime.device],
                ["log", f"{runtime.log_level} / {runtime.log_format}"],
                ["root", str(ROOT_DIR)],
            ]
        )
    )

    print("\nPaths")
    print(_table(_path_rows(settings)))

    print("\nProviders")
    print(
        _table(
            [
                [
                    status.interface,
                    status.name,
                    status.model or "—",
                    _STATE_LABEL.get(status.state, status.state),
                    status.detail,
                ]
                for status in statuses
            ]
        )
    )

    if probes:
        print("\nProbe")
        print(_table([[name, "ok" if ok else "FAILED", detail] for name, (ok, detail) in probes.items()]))

    r = settings.retrieval
    print("\nRetrieval")
    print(
        _table(
            [
                [
                    "pipeline",
                    f"dense {r.dense_top_k} + keyword {r.keyword_top_k} "
                    f"→ RRF(k={r.rrf_k}) → rerank → top {r.rerank_top_k}",
                ],
                ["refuse below", f"{r.min_rerank_score}"],
                ["collection", r.qdrant_collection],
                ["vintage", "prefer newest" if r.prefer_newest_vintage else "no preference"],
            ]
        )
    )

    print("\nAPI")
    print(_table([["bind", f"http://{settings.api.host}:{settings.api.port}"], ["cors", ", ".join(settings.api.origin_list)]]))
    print()

    if unknown := [s for s in statuses if s.state == "unknown"]:
        for status in unknown:
            print(f"error: {status.detail}", file=sys.stderr)
        return 1
    return 0 if all(ok for ok, _ in probes.values()) else 1


def _probe(settings: Settings, statuses: Sequence[ProviderStatus]) -> dict[str, tuple[bool, str]]:
    """Actually contact whatever is live. Only the LLM has anything to contact in Phase 00."""
    results: dict[str, tuple[bool, str]] = {}
    for status in statuses:
        if not status.ok:
            continue
        try:
            provider = {"llm": registry.load_llm}[status.interface](settings)
        except KeyError:
            continue
        except HblError as exc:
            results[status.interface] = (False, str(exc))
            continue
        probe = getattr(provider, "probe", None)
        results[status.interface] = probe() if probe else (True, "loaded")
    return results


# --- providers ---------------------------------------------------------------


def cmd_providers(args: argparse.Namespace, settings: Settings) -> int:
    selected = {
        "llm": settings.llm.provider,
        "embedder": settings.embedding.provider,
        "reranker": settings.reranker.provider,
        "ocr": settings.ocr.provider,
    }

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "interface": spec.interface,
                        "name": spec.name,
                        "active": selected.get(spec.interface) == spec.name,
                        "summary": spec.summary,
                        "phase": spec.phase,
                        "requires": list(spec.requires),
                        "missing": list(registry.missing_requirements(spec)),
                    }
                    for spec in registry.specs()
                ],
                indent=2,
            )
        )
        return 0

    print("\nRegistered providers.  * marks the one .env selects.\n")
    for interface in INTERFACES:
        print(f"{interface}")
        rows = []
        for spec in registry.specs(interface):
            missing = registry.missing_requirements(spec)
            if spec.phase:
                note = f"Phase {spec.phase}"
            elif missing:
                note = "missing: " + ", ".join(missing)
            else:
                note = "installed"
            rows.append(
                [
                    ("* " if selected.get(interface) == spec.name else "  ") + spec.name,
                    note,
                    spec.summary,
                ]
            )
        print(_table(rows))
        print()
    return 0


# --- classify ----------------------------------------------------------------


def _corpus(settings: Settings, given: Sequence[str]) -> list[Path]:
    """The PDFs to work on: whatever was named, else everything in documents/."""
    if given:
        paths = [Path(item) for item in given]
        if missing := [p for p in paths if not p.exists()]:
            raise HblError(f"no such file: {missing[0]}")
        return paths
    documents = settings.paths.documents_dir
    assert documents is not None  # filled by PathSettings._derive
    found = sorted(p for p in documents.glob("*.pdf") if p.is_file())
    if not found:
        raise HblError(f"no PDFs in {_relative(documents)} — put the corpus there or name files explicitly")
    return found


def cmd_classify(args: argparse.Namespace, settings: Settings) -> int:
    from app.ingest import KINDS, summarise_document
    from app.ingest.bench import collect_candidates, pick_bench_pages

    paths = _corpus(settings, args.paths)

    if args.pick_bench:
        picks = pick_bench_pages(collect_candidates(paths, settings.ingest))
        if args.json:
            print(json.dumps([{**p.__dict__, "document": p.document.name} for p in picks], indent=2, default=str))
            return 0
        print("\nBench pages for the OCR comparison\n")
        print(
            _table(
                [[p.category, p.document.name, f"p.{p.page_number}", p.rationale] for p in picks],
            )
        )
        print()
        return 0

    summaries = [summarise_document(path, settings.ingest) for path in paths]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "document": s.path.name,
                        "pages": s.page_count,
                        "counts": s.counts,
                        "dominant": s.dominant,
                        "verdicts": [
                            {
                                "page": v.page_number,
                                "kind": v.kind,
                                "reason": v.reason,
                                "char_density": round(v.signals.char_density, 1),
                                "raster_coverage": round(v.signals.raster_coverage, 3),
                                "raster_dpi": v.signals.raster_dpi,
                                "garble": round(v.signals.garble, 3),
                            }
                            for v in s.verdicts
                        ]
                        if args.explain
                        else [],
                    }
                    for s in summaries
                ],
                indent=2,
            )
        )
        return 0

    print("\nPage routing\n")
    rows = [["document", "pages", *KINDS]]
    for summary in summaries:
        rows.append(
            [
                summary.path.name[:52],
                str(summary.page_count),
                *[str(summary.counts[kind]) or "·" for kind in KINDS],
            ]
        )
    totals = {kind: sum(s.counts[kind] for s in summaries) for kind in KINDS}
    rows.append(["", "", "", "", "", ""])
    rows.append(["TOTAL", str(sum(s.page_count for s in summaries)), *[str(totals[k]) for k in KINDS]])
    print(_table(rows))

    ocr_pages = totals["scanned"] + totals["hybrid"]
    indexable = sum(s.page_count for s in summaries) - totals["empty"]
    print(f"\n  {ocr_pages} of {indexable} indexable pages need OCR ({ocr_pages / max(indexable, 1):.0%}).")
    print("  Run with --explain to see per-page reasoning, --pick-bench to choose comparison pages.\n")

    if args.explain:
        for summary in summaries:
            print(f"\n{summary.path.name}")
            print(
                _table(
                    [
                        [
                            f"p.{v.page_number}",
                            v.kind,
                            f"{v.signals.char_density:.0f} c/in²",
                            f"{v.signals.raster_coverage:.0%} raster",
                            f"{v.signals.raster_dpi:.0f} dpi" if v.signals.raster_dpi else "—",
                            f"garble {v.signals.garble:.2f}",
                            v.reason,
                        ]
                        for v in summary.verdicts
                    ]
                )
            )
        print()

    return 0


# --- extract -----------------------------------------------------------------


def cmd_extract(args: argparse.Namespace, settings: Settings) -> int:
    from app.ingest.extract import DocumentRecord, PageRecord, extract_corpus

    paths = _corpus(settings, args.paths)

    ocr = None
    if not args.no_ocr:
        try:
            ocr = registry.load_ocr(settings)
        except HblError as exc:
            raise HblError(
                f"{exc}\n\nRun with --no-ocr to extract only the digital pages, "
                "or fix the OCR engine first (`hbl health --probe`)."
            ) from exc

    print(f"\nExtracting {len(paths)} document(s) to {_relative(settings.paths.parsed_dir)}")  # type: ignore[arg-type]
    print(f"OCR engine: {settings.ocr.provider}/{settings.ocr.model}" if ocr else "OCR: disabled")
    print("Pages are cached as they succeed — stopping and re-running resumes.\n")

    state = {"pages": 0, "ocr_pages": 0, "seconds": 0.0, "failed": 0, "deferred": 0}

    def on_page(record: PageRecord, total: int) -> None:
        state["pages"] += 1
        state["seconds"] += record.seconds
        if record.strategy in ("ocr", "both"):
            state["ocr_pages"] += 1
        if record.error:
            state["failed"] += 1
        if record.deferred:
            state["deferred"] += 1
        # One line per page to stderr: an hour-long run needs to look alive, and
        # stdout must stay clean for --json.
        print(
            f"  p.{record.page:>4}/{total:<4} {record.kind:<8} {record.strategy:<10} "
            f"{record.seconds:>6.1f}s {record.characters:>6} chars"
            + (f"  ERROR {record.error[:60]}" if record.error else ""),
            file=sys.stderr,
            flush=True,
        )

    def on_document(record: DocumentRecord) -> None:
        if record.duplicate_of:
            print(f"  {record.document[:60]}  duplicate of {record.duplicate_of[:40]} — skipped")
        else:
            print(
                f"  {record.document[:60]:62} {record.pages:>4} pages  "
                f"{record.characters:>7} chars"
                + (f"  {len(record.deferred)} awaiting OCR" if record.deferred else "")
                + (f"  {len(record.failed)} FAILED" if record.failed else "")
            )

    documents = extract_corpus(
        paths, settings, ocr, force=args.force, on_page=on_page, on_document=on_document
    )

    if args.json:
        from dataclasses import asdict

        print(json.dumps([asdict(d) for d in documents], indent=2, default=str))
        return 1 if any(d.failed for d in documents) else 0

    duplicates = [d for d in documents if d.duplicate_of]
    failed = [r for d in documents for r in d.failed]

    print(f"\n  {state['pages']} pages, {state['ocr_pages']} through OCR, "
          f"{state['seconds'] / 60:.1f} minutes of work")
    if duplicates:
        print(f"  {len(duplicates)} duplicate document(s) skipped by content hash")
    if state["deferred"]:
        print(
            f"  {state['deferred']} page(s) still need OCR — re-run without --no-ocr\n"
            "  on the GPU machine. Nothing about them was cached, so that run\n"
            "  picks them up and leaves the rest alone."
        )
    if failed:
        print(f"  {len(failed)} page(s) FAILED — they appear as markers in the markdown")
        for record in failed[:5]:
            print(f"      p.{record.page}: {record.error[:90]}")
        return 1

    print(f"\n  Read {_relative(settings.paths.parsed_dir)} before trusting any of it.")  # type: ignore[arg-type]
    print("  That markdown is what everything downstream sees — not the PDFs.\n")
    return 0


# --- verify ------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace, settings: Settings) -> int:
    from app.ingest.verify import verify

    report = verify(settings, compare_prior=not args.fast)

    if args.json:
        from dataclasses import asdict

        print(json.dumps(asdict(report), indent=2, default=str))
        return 1 if report.errors else 0

    print(
        f"\nChecked {report.pages} pages across {report.documents} documents "
        f"({report.ocr_pages} through OCR, {report.characters:,} characters)\n"
    )

    if not report.findings:
        print("  Nothing to flag.\n")
        return 0

    by_check: dict[str, list] = {}
    for finding in report.findings:
        by_check.setdefault(f"{finding.severity}:{finding.check}", []).append(finding)

    for key in sorted(by_check, reverse=True):  # errors before warnings
        severity, check = key.split(":", 1)
        items = by_check[key]
        label = "ERROR" if severity == "error" else "warn "
        print(f"  {label} {check}  ({len(items)})")
        for finding in items[: args.limit]:
            print(f"        {finding.document[:44]:46} p.{finding.page:<4} {finding.detail[:78]}")
        if len(items) > args.limit:
            print(f"        ... and {len(items) - args.limit} more")
        print()

    if report.errors:
        print(f"  {len(report.errors)} error(s). Re-extract the affected documents:")
        names = sorted({f.document for f in report.errors})
        for name in names[:5]:
            print(f'      hbl extract --force "data/documents/{name}"')
        return 1

    print("  Warnings only — worth a look, not necessarily wrong.\n")
    return 0


# --- bench -------------------------------------------------------------------


def cmd_bench(args: argparse.Namespace, settings: Settings) -> int:
    from app.ingest.bench import BenchPick, collect_candidates, pick_bench_pages
    from app.ingest.benchmark import DEFAULT_ENGINES, run_bench

    if args.page:
        picks: list[BenchPick] = []
        for item in args.page:
            document, _, number = item.rpartition(":")
            if not document or not number.isdigit():
                raise HblError(f"--page wants DOCUMENT:PAGE, got {item!r}")
            path = Path(document)
            if not path.exists():
                path = (settings.paths.documents_dir or Path()) / document  # type: ignore[operator]
            if not path.exists():
                raise HblError(f"no such document: {document}")
            picks.append(BenchPick("chosen", path, int(number), 0.0, "named on the command line"))
    else:
        documents = _corpus(settings, [])
        # Measuring 500-odd pages takes a few seconds and prints nothing, which
        # reads as a hang on a machine that is about to be busy for an hour.
        print(f"\nMeasuring {len(documents)} documents to choose comparison pages...", flush=True)
        picks = pick_bench_pages(collect_candidates(documents, settings.ingest))
        if not picks:
            raise HblError("found no pages to bench — is data/documents/ populated?")

    engines = args.engines or list(DEFAULT_ENGINES)

    print(f"\nBenching {len(engines)} engine(s) over {len(picks)} page(s) at {args.dpi or settings.ingest.render_dpi} dpi.")
    print("Rendering once, so every engine reads identical input.\n")
    print(_table([[p.category, p.document.name[:46], f"p.{p.page_number}"] for p in picks]))
    print(
        "\nThis is the slow part. A vision model reads a dense page in roughly "
        "20-60s on the\nRTX 4060 Ti, so expect a few minutes per engine. Progress "
        "goes to stderr.\n",
        flush=True,
    )

    report = run_bench(
        picks,
        settings,
        engines=engines,
        dpi=args.dpi,
        out_dir=Path(args.out) if args.out else None,
        overwrite=args.overwrite,
    )

    if args.json:
        from dataclasses import asdict

        print(json.dumps(asdict(report), indent=2, default=str))
        return 0 if report.runs else 1

    for name, reason in report.engines_unavailable.items():
        print(f"skipped {name}: {reason}")
    if report.engines_unavailable:
        print()

    if not report.runs:
        print("No engine produced anything. Nothing to compare.\n")
        return 1

    print("Results\n")
    print(
        _table(
            [["engine", "page", "seconds", "chars", "tables", "notes"]]
            + [
                [
                    run.engine,
                    f"p.{run.page_number}",
                    f"{run.seconds:.1f}" if run.ok else "—",
                    str(run.characters) if run.ok else "—",
                    str(run.tables) if run.ok else "—",
                    ("; ".join(run.warnings) if run.ok else f"FAILED: {run.error[:80]}") or "",
                ]
                for run in report.runs
            ]
        )
    )

    print(f"\n  Markdown written to {_relative(Path(report.output_dir))}")
    print("  Read the files for one page side by side, then pick the engine.")
    print("  Watch the dense table especially — a flattened table still reads as fact.\n")
    return 0


# --- paths -------------------------------------------------------------------


def cmd_paths(args: argparse.Namespace, settings: Settings) -> int:
    if args.create:
        created = settings.paths.create()
        for path in created:
            print(f"created  {_relative(path)}")
        if not created:
            print("nothing to create — every directory already exists")
        return 0

    print(_table(_path_rows(settings), indent=""))
    return 0


# --- wiring ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="HBL RAG Assistant backend. Everything runs locally; nothing leaves the machine.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    health = sub.add_parser("health", help="resolved configuration and the provider behind each interface")
    health.add_argument("--json", action="store_true", help="machine-readable output on stdout")
    health.add_argument("--probe", action="store_true", help="also contact live providers (Ollama)")
    health.set_defaults(handler=cmd_health)

    providers = sub.add_parser("providers", help="every registered provider and whether it can run here")
    providers.add_argument("--json", action="store_true")
    providers.set_defaults(handler=cmd_providers)

    classify = sub.add_parser(
        "classify",
        help="route every page to digital / scanned / hybrid, without extracting anything",
    )
    classify.add_argument("paths", nargs="*", help="PDFs to inspect (default: everything in documents/)")
    classify.add_argument("--explain", action="store_true", help="per-page numbers and reasoning")
    classify.add_argument(
        "--pick-bench",
        action="store_true",
        help="nominate one page per category for the OCR comparison",
    )
    classify.add_argument("--json", action="store_true")
    classify.set_defaults(handler=cmd_classify)

    extract = sub.add_parser(
        "extract",
        help="read every page into one markdown file per document (the quality gate)",
    )
    extract.add_argument("paths", nargs="*", help="PDFs (default: everything in documents/)")
    extract.add_argument(
        "--force", action="store_true", help="re-extract pages already cached"
    )
    extract.add_argument(
        "--no-ocr",
        action="store_true",
        help="digital pages only — useful on a machine with no GPU",
    )
    extract.add_argument("--json", action="store_true")
    extract.set_defaults(handler=cmd_extract)

    verify = sub.add_parser(
        "verify",
        help="check extracted markdown for pages that succeeded but came out wrong",
    )
    verify.add_argument("--limit", type=int, default=6, help="findings shown per check")
    verify.add_argument(
        "--fast",
        action="store_true",
        help="skip comparing scans against their own prior OCR layer (needs the PDFs)",
    )
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(handler=cmd_verify)

    bench = sub.add_parser(
        "bench",
        help="run every available OCR engine over the same pages and write the output to compare",
    )
    bench.add_argument(
        "--engines",
        nargs="+",
        metavar="NAME",
        help="engines to try (default: vlm docling surya mineru). Missing ones are skipped, not fatal.",
    )
    bench.add_argument(
        "--page",
        action="append",
        metavar="DOC:PAGE",
        help="bench a specific page instead of the automatic picks; repeatable",
    )
    bench.add_argument("--dpi", type=int, help="render resolution (default: HBL_INGEST_RENDER_DPI)")
    bench.add_argument("--out", help="where to write the markdown (default: data/parsed/bench)")
    bench.add_argument("--overwrite", action="store_true", help="re-render pages already on disk")
    bench.add_argument("--json", action="store_true")
    bench.set_defaults(handler=cmd_bench)

    paths = sub.add_parser("paths", help="where documents and indexes live")
    paths.add_argument("--create", action="store_true", help="create any missing directory")
    paths.set_defaults(handler=cmd_paths)

    return parser


def _force_utf8_output() -> None:
    """Stop Windows' legacy code page from crashing the CLI.

    Python on Windows defaults stdout to cp1252, which cannot encode the arrows
    and superscripts used in this output — printing them raises
    UnicodeEncodeError and takes the whole command down. Both machines are
    Windows, so this is not a corner case. `errors="replace"` keeps a genuinely
    ancient console readable-but-mangled rather than fatal.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # a stream that cannot be reconfigured
                pass


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)
    try:
        settings = get_settings()
    except HblError as exc:
        configure_logging()
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings.runtime.log_level, settings.runtime.log_format)
    try:
        return args.handler(args, settings)
    except HblError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
