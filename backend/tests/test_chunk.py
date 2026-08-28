"""Tests for identity, structure and chunking.

Fixtures are hand-written markdown in the shape extraction actually produces —
page markers, run-on headings, repeated furniture — because every rule under
test exists because of something the real corpus did.
"""

from __future__ import annotations

import pytest

from app.config import ChunkSettings
from app.ingest.chunk import chunk_document, estimate_tokens
from app.ingest.metadata import group_by_family, identify
from app.ingest.structure import contents_index, find_furniture, is_contents_table, parse

SETTINGS = ChunkSettings(_env_file=None)  # type: ignore[call-arg]

SENTENCE = (
    "The Bank shall apply enhanced due diligence to any customer identified as a "
    "politically exposed person and obtain senior management approval. "
)


def _page(number: int, body: str) -> str:
    return f"<!-- page {number} | digital | text layer -->\n\n{body}\n"


# --- identity ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "year", "circular"),
    [
        ("A-INST-2025-01- Encl. Sanctions Compliance Policy.pdf", 2025, "A-INST-2025-01"),
        ("Sanctions Compliance Policy - 2023.pdf", 2023, ""),
        ("Business Continuity Policy 2024.pdf", 2024, ""),
        ("HBL Data Privacy Policy.pdf", None, ""),
    ],
)
def test_year_and_circular_come_off_the_filename(filename: str, year: int | None, circular: str) -> None:
    identity = identify(filename)
    assert identity.year == year
    assert identity.circular == circular


def test_the_two_vintages_of_a_policy_share_a_family() -> None:
    """The failure this prevents: retrieval returns a superseded clause and the
    model states it as current, because nothing knew the two were rivals."""
    new = identify("A-INST-2025-01- Encl. Sanctions Compliance Policy.pdf")
    old = identify("Sanctions Compliance Policy - 2023.pdf")
    assert new.policy_family == old.policy_family
    assert new.year == 2025 and old.year == 2023


def test_unrelated_documents_do_not_share_a_family() -> None:
    assert identify("Donations Policy 2024.pdf").policy_family != identify(
        "Equity Investment Policy 2023.pdf"
    ).policy_family


def test_an_faq_is_not_a_vintage_of_the_policy_it_explains() -> None:
    """`AFPAD` and `AFPAD - Frequently Asked Questions` are different documents.
    Grouped together, "prefer newest" would suppress the FAQ entirely."""
    assert identify("AFPAD 2025.pdf").policy_family != identify(
        "AFPAD - Frequently Asked Questions (FAQs).pdf"
    ).policy_family


def test_families_are_ordered_newest_first() -> None:
    families = group_by_family(
        ["Sanctions Compliance Policy - 2023.pdf", "A-INST-2025-01- Encl. Sanctions Compliance Policy.pdf"]
    )
    members = next(iter(families.values()))
    assert [m.year for m in members] == [2025, 2023]


def test_the_download_suffix_is_not_part_of_the_title() -> None:
    assert "(1)" not in identify("Compliance Program 2023 - Portal version (1).pdf").title


# --- page furniture ----------------------------------------------------------


def test_a_running_header_is_detected() -> None:
    markdown = "".join(_page(n, f"HBL\n\n**POLICY**\n\n{SENTENCE}") for n in range(1, 7))
    furniture = find_furniture(markdown)
    assert "HBL" in furniture
    assert "POLICY" in furniture


def test_a_footer_whose_number_changes_is_still_detected() -> None:
    """Counted verbatim, `PAGE 1 OF 9` never repeats and survives into every
    chunk. Blanking digits first collapses them all to one template."""
    markdown = "".join(_page(n, f"{SENTENCE}\n\nPAGE {n} OF 9") for n in range(1, 10))
    assert any(line.startswith("PAGE") for line in find_furniture(markdown))


def test_decorated_and_plain_copies_of_a_header_count_as_one() -> None:
    """OCR emits `HBL` on one page and `**HBL**` on the next, depending on what
    it thought it was looking at."""
    body = [f"{'**HBL**' if n % 2 else 'HBL'}\n\n{SENTENCE}" for n in range(1, 9)]
    markdown = "".join(_page(n, b) for n, b in enumerate(body, 1))
    assert "HBL" in find_furniture(markdown)


def test_a_sentence_appearing_twice_is_not_furniture() -> None:
    markdown = "".join(_page(n, SENTENCE) for n in range(1, 9))
    assert SENTENCE.strip() not in find_furniture(markdown)


# --- contents pages ----------------------------------------------------------


def test_a_contents_table_is_recognised() -> None:
    body = (
        "| 1. OBJECTIVE AND SCOPE | ... |\n| --- | --- |\n"
        "| 1.1. INTRODUCTION | ... |\n| 1.2. PURPOSE | ... |\n| 1.3. SCOPE | ... |"
    )
    assert is_contents_table(body)


def test_a_real_table_is_not_mistaken_for_contents() -> None:
    body = (
        "| S. No | Overriding Factors | Risk Classification |\n| --- | --- | --- |\n"
        "| 1 | OFAC Comprehensive Country Sanctions | Unacceptable |\n"
        "| 2 | FATF Blacklist | Unacceptable |\n"
        "| 3 | FATF Grey List | Restricted |"
    )
    assert not is_contents_table(body)


def test_contents_entries_are_not_kept_as_sections() -> None:
    markdown = _page(1, "Table of Contents\n\n1. SCOPE 4\n\n2. ROLES 5\n\n3. ANNEXURES 9") + _page(
        2, f"1. SCOPE\n\n{SENTENCE * 3}"
    )
    document = parse(markdown)
    headings = [b for b in document.blocks if b.is_heading]
    assert [h.number for h in headings] == ["1"]


# --- run-on headings ---------------------------------------------------------


def test_the_contents_page_supplies_the_true_title() -> None:
    markdown = _page(1, "1.3 Risk Categories 4") + _page(
        2, "1.3 Risk Categories There are four risk-based categories that apply to countries."
    )
    assert contents_index(markdown)["1.3"] == "Risk Categories"


def test_a_heading_run_together_with_its_body_is_split() -> None:
    """The vision model transcribes both onto one line. Left joined, the
    breadcrumb of every clause in the section carries a sentence of prose."""
    markdown = _page(1, "1.3 Risk Categories 4") + _page(
        2, "1.3 Risk Categories There are four risk-based categories that apply to countries."
    )
    document = parse(markdown)
    heading = next(b for b in document.blocks if b.is_heading and b.number == "1.3")
    assert heading.title == "Risk Categories"
    body = next(b for b in document.blocks if b.kind == "paragraph")
    assert body.text.startswith("There are four")


def test_a_numbered_paragraph_is_not_promoted_to_a_heading() -> None:
    long_clause = "4.1.2 " + SENTENCE * 2
    document = parse(_page(1, long_clause))
    assert not [b for b in document.blocks if b.is_heading]


def test_a_footer_that_starts_with_a_number_is_not_a_heading() -> None:
    """`12 | Page` was becoming section 12, and every chunk after it inherited
    the breadcrumb."""
    document = parse(_page(1, f"12 | Page\n\n{SENTENCE}"))
    assert not [b for b in document.blocks if b.is_heading]


# --- chunking ----------------------------------------------------------------


def _chunks(markdown: str, name: str = "Sanctions Compliance Policy - 2023.pdf"):
    document = parse(markdown)
    return chunk_document(document.blocks, identify(name), SETTINGS)


def test_a_table_is_never_split() -> None:
    """Half a table of risk classifications still reads as a complete table —
    it simply omits the rows that would have contradicted it."""
    rows = "\n".join(f"| {n} | Country {n} | Restricted |" for n in range(120))
    chunks, stats = _chunks(_page(1, f"3. Sanctions\n\n| S | Country | Risk |\n| --- | --- | --- |\n{rows}"))

    tables = [c for c in chunks if c.kind == "table"]
    assert len(tables) == 1
    # 120 data rows, all of them, in one chunk.
    assert tables[0].text.count("| Restricted |") == 120
    # Well past the 700-token target and still one piece: size never splits a table.
    assert tables[0].tokens > SETTINGS.target_tokens


def test_each_chunk_carries_its_breadcrumb_and_vintage() -> None:
    markdown = _page(1, f"3. Roles\n\n{SENTENCE * 4}\n\n3.2 Senior Management\n\n{SENTENCE * 4}")
    chunks, _ = _chunks(markdown)

    deepest = [c for c in chunks if "3.2" in c.section]
    assert deepest
    assert deepest[0].section == "3 Roles > 3.2 Senior Management"
    assert deepest[0].text.startswith("[Sanctions Compliance Policy (2023) — 3 Roles > 3.2")
    assert deepest[0].year == 2023


def test_a_chunk_records_the_page_it_came_from() -> None:
    chunks, _ = _chunks(_page(7, f"1. Scope\n\n{SENTENCE * 4}"))
    assert chunks[0].pages == (7,)
    assert chunks[0].to_payload()["page"] == 7


def test_a_section_boundary_ends_a_chunk() -> None:
    markdown = _page(1, f"1. Scope\n\n{SENTENCE}\n\n2. Roles\n\n{SENTENCE}")
    chunks, _ = _chunks(markdown)
    sections = {c.section for c in chunks}
    assert "1 Scope" in sections and "2 Roles" in sections
    for chunk in chunks:
        assert not ("1 Scope" in chunk.section and "2 Roles" in chunk.section)


def test_a_long_section_splits_with_sentence_overlap() -> None:
    markdown = _page(1, f"1. Scope\n\n" + "\n\n".join(SENTENCE * 3 for _ in range(14)))
    chunks, _ = _chunks(markdown)
    assert len(chunks) > 1
    # Overlap is whole sentences, so no chunk opens mid-sentence.
    for chunk in chunks[1:]:
        body = chunk.text.split("\n\n", 1)[-1].lstrip()
        assert body[:1].isupper() or body.startswith("|")


def test_content_free_chunks_are_dropped() -> None:
    """Residual furniture below its document's repeat threshold: `HABIB BANK`
    on its own answers nothing and matches short queries."""
    chunks, stats = _chunks(_page(1, "HABIB BANK"))
    assert chunks == []
    assert stats.dropped_empty == 1


def test_a_caption_is_merged_into_the_table_it_introduces() -> None:
    markdown = _page(1, "Prepared by:\n\n| Prepared by: | A. Ahmed |\n| --- | --- |")
    chunks, stats = _chunks(markdown)
    assert len(chunks) == 1
    assert "Prepared by:" in chunks[0].text
    assert stats.merged_fragments == 1


def test_chunk_ids_are_stable_across_runs() -> None:
    markdown = _page(1, f"1. Scope\n\n{SENTENCE * 4}")
    first, _ = _chunks(markdown)
    second, _ = _chunks(markdown)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_token_estimates_track_length() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("x" * 400) == 100


def test_a_contents_entry_is_not_a_heading() -> None:
    """Observed on the Donations Policy: the contents line

        Annexure 2 Donation Application Form - Internal...............12

    is 79 characters and seven words, so it cleared the annexure heading's
    length guards and became a level-1 heading. Every clause after it inherited
    that breadcrumb, so the approval thresholds — who signs off a PKR 30m
    donation — were filed under "Donation Application Form", both in the source
    panel and in the text handed to the reranker.
    """
    from app.ingest.structure import _classify_line

    assert _classify_line("Annexure 2 Donation Application Form - Internal.................12") is None
    assert _classify_line("Appendix A Country Risk Ratings .... 7") is None

    # The real headings those entries point at must still be headings.
    for real in ("Annexure 2 Donation Application Form - Internal", "Annexure 3", "Appendix A"):
        block = _classify_line(real)
        assert block is not None and block.kind == "heading", real
