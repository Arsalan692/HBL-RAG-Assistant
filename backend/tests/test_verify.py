"""Tests for the extraction audit.

Every check exercised here corresponds to something the real corpus produced.
The fixtures are hand-written sidecars, so no PDFs and no engine are needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.ingest.verify import verify, warning_severity


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.paths.parsed_dir = tmp_path / "parsed"
    s.paths.documents_dir = tmp_path / "documents"
    s.paths.parsed_dir.mkdir(parents=True)
    s.paths.documents_dir.mkdir(parents=True)
    return s


def _sidecar(settings: Settings, name: str, *records: dict) -> None:
    base = {
        "page": 1,
        "kind": "digital",
        "strategy": "text-layer",
        "reason": "clean text layer",
        "text": "Enhanced due diligence applies to politically exposed persons.",
        "warnings": [],
        "error": "",
        "deferred": False,
        "characters": 60,
    }
    payload = {
        "document": name,
        "sha256": "abc",
        "records": [{**base, **r} for r in records],
    }
    stem = name.replace(".pdf", "").replace(" ", "-")
    (settings.paths.parsed_dir / f"{stem}.pages.json").write_text(  # type: ignore[operator]
        json.dumps(payload), encoding="utf-8"
    )


def _checks(report) -> set[str]:
    return {f.check for f in report.findings}


def test_a_clean_extraction_produces_no_findings(settings: Settings) -> None:
    _sidecar(settings, "Policy.pdf", {})
    report = verify(settings, compare_prior=False)
    assert report.findings == []
    assert report.pages == 1


def test_a_fabricated_image_is_an_error(settings: Settings) -> None:
    """Observed on a title page: the model invented an imgur URL instead of
    reading, discarding the document's own title."""
    _sidecar(settings, "Insider.pdf", {"text": "![](https://i.imgur.com/3Q5z5ZG.png)"})
    report = verify(settings, compare_prior=False)
    assert "fabricated-image" in _checks(report)
    assert report.errors


def test_a_real_url_in_the_text_is_not_flagged(settings: Settings) -> None:
    """These policies genuinely cite OFAC, OFSI and the EU sanctions map."""
    _sidecar(
        settings,
        "Sanctions.pdf",
        {"text": "Refer to https://sanctionsmap.eu/#/main and https://home.treasury.gov/x."},
    )
    report = verify(settings, compare_prior=False)
    assert report.findings == []


def test_a_lost_table_is_an_error(settings: Settings) -> None:
    """The check nothing else can make: the router knows the page held a table,
    the output knows whether one survived, and only this sees both."""
    _sidecar(
        settings,
        "Guidelines.pdf",
        {
            "kind": "digital",
            "strategy": "ocr",
            "reason": "clean text layer, but holds 1 table(s) the text-layer path would corrupt",
            "text": "Risk classifications are unacceptable, restricted and standard.",
        },
    )
    report = verify(settings, compare_prior=False)
    assert "table-lost" in _checks(report)


def test_a_surviving_table_is_not_flagged(settings: Settings) -> None:
    _sidecar(
        settings,
        "Guidelines.pdf",
        {
            "strategy": "ocr",
            "reason": "clean text layer, but holds 1 table(s) the text-layer path would corrupt",
            "text": "| S. No | Factor |\n| 1 | OFAC sanctions |",
        },
    )
    report = verify(settings, compare_prior=False)
    assert "table-lost" not in _checks(report)


def test_a_headerless_table_still_counts(settings: Settings) -> None:
    """The AML abbreviations glossary has no header row. Counting by the
    `|---|---|` separator reported it as having no table at all."""
    _sidecar(
        settings,
        "AML.pdf",
        {
            "strategy": "ocr",
            "reason": "clean text layer, but holds 1 table(s) the text-layer path would corrupt",
            "text": "| PEPCO | Pakistan Electric Power Company |\n| OGDC | Oil & Gas Development |",
        },
    )
    report = verify(settings, compare_prior=False)
    assert "table-lost" not in _checks(report)


def test_a_repetition_loop_warning_is_escalated_to_an_error(settings: Settings) -> None:
    _sidecar(
        settings,
        "Cover.pdf",
        {"warnings": ["looks like a repetition loop — one line occurs 115 times"]},
    )
    report = verify(settings, compare_prior=False)
    assert report.errors
    assert "engine-warning" in _checks(report)


def test_illegible_regions_are_only_a_warning(settings: Settings) -> None:
    """The model flagging what it cannot read is correct behaviour, not damage."""
    _sidecar(settings, "Scan.pdf", {"warnings": ["3 illegible region(s)"]})
    report = verify(settings, compare_prior=False)
    assert not report.errors
    assert report.warnings


def test_an_empty_page_that_was_not_blank_is_an_error(settings: Settings) -> None:
    _sidecar(settings, "Scan.pdf", {"text": "   ", "characters": 0})
    report = verify(settings, compare_prior=False)
    assert "no-text" in _checks(report)


def test_a_deferred_page_is_reported_as_never_extracted(settings: Settings) -> None:
    _sidecar(settings, "Scan.pdf", {"deferred": True, "strategy": "ocr", "text": ""})
    report = verify(settings, compare_prior=False)
    assert "never-extracted" in _checks(report)


def test_blank_pages_are_not_counted_or_flagged(settings: Settings) -> None:
    _sidecar(settings, "Policy.pdf", {"strategy": "skip", "kind": "empty", "text": ""})
    report = verify(settings, compare_prior=False)
    assert report.pages == 0
    assert report.findings == []


def test_encoding_damage_is_reported(settings: Settings) -> None:
    _sidecar(settings, "Scan.pdf", {"text": "Enhanced due diligence � applies."})
    report = verify(settings, compare_prior=False)
    assert "encoding-damage" in _checks(report)


# --- severity of engine warnings ---------------------------------------------


def test_a_recovery_is_not_an_error(settings: Settings) -> None:
    """The warning naming a recovery also names the failure it recovered from.
    Substring matching alone reported a page that came out fine as an error."""
    _sidecar(
        settings,
        "Insider.pdf",
        {"warnings": ["first attempt returned an image placeholder; recovered on retry"]},
    )
    report = verify(settings, compare_prior=False)
    assert not report.errors
    assert report.warnings


def test_an_unrecovered_placeholder_is_still_an_error(settings: Settings) -> None:
    _sidecar(settings, "Insider.pdf", {"warnings": ["returned only an image placeholder, no text"]})
    assert verify(settings, compare_prior=False).errors


@pytest.mark.parametrize(
    ("warning", "severity"),
    [
        ("returned only an image placeholder, no text", "error"),
        ("looks like a repetition loop — one line occurs 115 times", "error"),
        ("empty output", "error"),
        ("3 illegible region(s)", "warning"),
        ("first attempt returned nothing; recovered on retry", "warning"),
        ("hit the token limit — output is truncated", "warning"),
    ],
)
def test_warning_severities(warning: str, severity: str) -> None:
    assert warning_severity(warning) == severity
