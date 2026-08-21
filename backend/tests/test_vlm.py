"""Tests for the chosen OCR engine's output handling.

No Ollama is contacted. What is tested is the post-processing, which exists
because of specific things the benched models actually did on real pages.
"""

from __future__ import annotations

from app.providers.ocr.vlm import _count_tables, _degenerate_repeat, _unfence

TABLE = "| S. No | Factor |\n|---|---|\n| 1 | OFAC Comprehensive Country Sanctions |"


# --- code fences -------------------------------------------------------------


def test_a_fence_wrapping_the_whole_page_is_removed() -> None:
    """Every model benched did this: asked for markdown, returns it inside
    ```markdown, because that is what markdown looks like in training data."""
    assert _unfence(f"```markdown\n{TABLE}\n```") == TABLE


def test_an_unlabelled_outer_fence_is_removed_too() -> None:
    assert _unfence(f"```\n{TABLE}\n```") == TABLE


def test_a_fence_around_part_of_the_page_survives() -> None:
    """Real content. These documents quote system messages and code."""
    body = f"Configure the service as follows:\n\n```\nHBL_LLM_THINK=false\n```\n\nThen restart."
    assert _unfence(body) == body


def test_two_separate_fenced_blocks_survive() -> None:
    body = "```\nfirst\n```\n\nprose between\n\n```\nsecond\n```"
    assert _unfence(body) == body


def test_ordinary_markdown_is_untouched() -> None:
    assert _unfence(TABLE) == TABLE


# --- repetition loops --------------------------------------------------------


def test_a_repetition_loop_is_detected() -> None:
    """Benched on a title page, one candidate emitted the same four lines 115
    times until it exhausted its token budget. Every word was really on the
    page, so nothing downstream would have questioned it."""
    looped = "\n".join(["Compliance Training, Assurance & Projects (CTAP)"] * 40)
    assert _degenerate_repeat(looped) == 40


def test_normal_prose_is_not_flagged() -> None:
    prose = "\n".join(
        f"Clause {n}.1 requires enhanced due diligence for this category."
        for n in range(30)
    )
    assert _degenerate_repeat(prose) == 0


def test_repeated_table_scaffolding_is_not_a_loop() -> None:
    """Rules and separators legitimately repeat down a long table."""
    rows = "\n".join(["|---|---|"] * 30)
    assert _degenerate_repeat(f"| A | B |\n{rows}") == 0


def test_a_short_page_is_never_flagged() -> None:
    # A cover page with a genuinely repeated line is not evidence of a loop.
    assert _degenerate_repeat("Global Compliance Group\nGlobal Compliance Group") == 0


# --- table counting ----------------------------------------------------------


def test_tables_are_counted_by_their_header_separator() -> None:
    assert _count_tables(TABLE) == 1
    assert _count_tables(f"{TABLE}\n\nprose\n\n{TABLE}") == 2


def test_prose_reports_no_tables() -> None:
    """The signal that matters: an engine reporting zero tables on a page of
    tables has flattened them into prose, which still reads as fact."""
    assert _count_tables("The Bank shall apply enhanced due diligence.") == 0
