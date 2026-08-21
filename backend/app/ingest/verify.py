"""Checking extracted markdown for the ways it goes quietly wrong.

Extraction reports its own failures honestly — a page that raised is recorded
as an error and appears in the markdown as a marker. This module is for the
other kind: pages that *succeeded* and are wrong anyway.

Every check here was written because the corpus actually produced it. None is
speculative:

- A title page came back as `![](https://i.imgur.com/...)`. The model invented
  a URL instead of reading, and dropped the document's own title — the single
  most valuable line in the file for retrieval.
- A candidate engine emitted the same four lines 115 times on a sparse page.
- A page routed to OCR *because it holds a table* can come back without one,
  meaning the table was flattened into prose that still reads as fact.

The last of those is the reason this is a separate pass rather than a warning
inside the engine. Whether a page should have had a table is known by the
router, and whether it did is known by the output; nothing sees both until now.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pymupdf

from app.config import Settings
from app.logging_config import get_logger

log = get_logger(__name__)

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_WORDS = re.compile(r"[^a-z0-9 ]+")

#: Below this word-level agreement with a scan's own prior OCR layer, two
#: independent readings of the same page disagree enough to be worth a look.
#: The corpus median is 0.96, so this is far into the tail.
AGREEMENT_FLOOR = 0.55


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing worth a person's attention, and where to look."""

    severity: str  # "error" | "warning"
    check: str
    document: str
    page: int
    detail: str


@dataclass
class Report:
    documents: int = 0
    pages: int = 0
    ocr_pages: int = 0
    characters: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]


def _words(text: str) -> list[str]:
    return _WORDS.sub(" ", text.lower()).split()


def _sidecars(parsed_dir: Path) -> Iterator[dict]:
    for path in sorted(parsed_dir.glob("*.pages.json")):
        try:
            yield json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("verify.unreadable_sidecar", extra={"path": str(path), "error": str(exc)})


def verify(settings: Settings, *, compare_prior: bool = True) -> Report:
    """Read every provenance sidecar and report what looks wrong."""
    parsed_dir = settings.paths.parsed_dir
    documents_dir = settings.paths.documents_dir
    assert parsed_dir is not None and documents_dir is not None

    report = Report()

    for payload in _sidecars(parsed_dir):
        name = payload.get("document", "?")
        report.documents += 1
        records = payload.get("records", [])

        source = documents_dir / name
        doc = None
        if compare_prior and source.exists():
            try:
                doc = pymupdf.open(source)
            except Exception:  # a missing or unreadable PDF is not fatal here
                doc = None

        for record in records:
            strategy = record.get("strategy", "")
            if strategy == "skip":
                continue

            report.pages += 1
            text = record.get("text", "")
            page = record.get("page", 0)
            report.characters += len(text)
            if strategy in ("ocr", "both"):
                report.ocr_pages += 1

            def add(severity: str, check: str, detail: str) -> None:
                report.findings.append(Finding(severity, check, name, page, detail))

            if record.get("error"):
                add("error", "extraction-failed", record["error"][:160])
                continue
            if record.get("deferred"):
                add("error", "never-extracted", "needs OCR; run without --no-ocr")
                continue

            if not text.strip():
                add("error", "no-text", "page produced nothing but was not blank")

            if _IMAGE.search(text):
                add(
                    "error",
                    "fabricated-image",
                    "output contains an image link the engine invented rather than "
                    "text it read",
                )

            if "�" in text:
                add("warning", "encoding-damage", f"{text.count(chr(0xFFFD))} replacement character(s)")

            for warning in record.get("warnings", []):
                severity = "error" if ("repetition" in warning or "placeholder" in warning) else "warning"
                add(severity, "engine-warning", warning)

            # The check nothing else can make: the router said this page holds a
            # table, so the output must contain one. If it does not, the table
            # became prose — and prose that used to be a table still reads as
            # fact once retrieved and cited.
            reason = record.get("reason", "")
            if "holds" in reason and "table" in reason and _count_table_blocks(text) == 0:
                add("error", "table-lost", "routed to OCR for holding a table; none in the output")

            # Two independent readings of the same scan. Cheap corroboration
            # where they agree, and a pointer to the interesting pages where
            # they do not.
            if doc is not None and record.get("kind") == "scanned" and strategy == "ocr":
                try:
                    prior = doc[page - 1].get_text("text")
                except Exception:
                    prior = ""
                theirs, ours = _words(prior), _words(text)
                if len(theirs) >= 60 and ours:
                    ratio = difflib.SequenceMatcher(None, theirs, ours).ratio()
                    if ratio < AGREEMENT_FLOOR:
                        add(
                            "warning",
                            "disagrees-with-prior-ocr",
                            f"{ratio:.0%} word agreement with the page's own text layer "
                            f"({len(theirs)} words there, {len(ours)} here)",
                        )

        if doc is not None:
            doc.close()

    return report


def _count_table_blocks(markdown: str) -> int:
    """Runs of adjacent pipe-delimited rows.

    Not counted by the `|---|---|` separator: several real tables here have no
    header row, and counting separators reported the AML policy's abbreviations
    glossary as having no table at all. A check that cries wolf gets ignored.
    """
    count = 0
    run = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            run += 1
            if run == 2:
                count += 1
        else:
            run = 0
    return count
