"""Hybrid retrieval: fusion, reranking, refusal and vintage handling.

These run on the laptop with no weights loaded. The reranker is faked, because
what needs testing here is the pipeline's behaviour around it — what it keeps,
what it refuses, and how it treats two editions of the same policy — not
whether a cross-encoder can read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import EmbeddingSettings, Settings
from app.ingest.chunk import Chunk
from app.providers.base import Scored
from app.providers.embedding.hashing import HashingEmbedder
from app.retrieve import Retriever, reciprocal_rank_fusion
from app.store.index import index_document
from app.store.registry import KeywordHit, Registry
from app.store.vectors import VectorHit, VectorStore

DIMENSION = 64


# --- fusion, with no stores involved -----------------------------------------


def _dense(*chunk_ids: str) -> list[VectorHit]:
    return [
        VectorHit(chunk_id=c, doc_id="d", section="", page=1, text=c, score=0.9 - i * 0.1)
        for i, c in enumerate(chunk_ids)
    ]


def _keyword(*chunk_ids: str) -> list[KeywordHit]:
    return [
        KeywordHit(chunk_id=c, doc_id="d", section="", page=1, text=c, score=10.0 - i)
        for i, c in enumerate(chunk_ids)
    ]


def test_agreement_beats_a_single_strong_opinion() -> None:
    """The property RRF is chosen for: a chunk both retrievers rank second
    outranks one that only dense search put first.

    That is the shape of a good hit in this corpus — a clause that reads on
    topic *and* contains the identifier that was asked about."""
    fused = reciprocal_rank_fusion(_dense("solo", "agreed"), _keyword("other", "agreed"))
    assert fused[0].chunk_id == "agreed"
    assert fused[0].found_by == "both"


def test_a_chunk_only_keyword_search_found_still_survives() -> None:
    """Identifiers like A-INST-2025-01 embed to nothing in particular, so dense
    search misses them entirely. Fusion must not require agreement."""
    fused = reciprocal_rank_fusion(_dense("a"), _keyword("identifier"))
    assert {c.chunk_id for c in fused} == {"a", "identifier"}
    assert [c.found_by for c in fused if c.chunk_id == "identifier"] == ["keyword"]


def test_fusion_ignores_the_incomparable_score_scales() -> None:
    """BM25 is unbounded and cosine is not. Only positions may matter, so
    inflating one list's scores must change nothing."""
    dense = _dense("x", "y")
    keyword = [
        KeywordHit(chunk_id="y", doc_id="d", section="", page=1, text="y", score=9_999.0),
        KeywordHit(chunk_id="x", doc_id="d", section="", page=1, text="x", score=0.0001),
    ]
    order = [c.chunk_id for c in reciprocal_rank_fusion(dense, keyword)]
    assert order == ["x", "y"]  # each is 1st once and 2nd once; dense breaks the tie


def test_fusion_is_deterministic_under_ties() -> None:
    first = reciprocal_rank_fusion(_dense("a", "b", "c"), _keyword("c", "b", "a"))
    second = reciprocal_rank_fusion(_dense("a", "b", "c"), _keyword("c", "b", "a"))
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


# --- the pipeline ------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.paths.registry_db = tmp_path / "registry.sqlite"
    s.paths.qdrant_dir = tmp_path / "qdrant"
    s.paths.parsed_dir = tmp_path / "parsed"
    s.paths.page_image_dir = tmp_path / "images"
    s.embedding = EmbeddingSettings(_env_file=None, dimension=DIMENSION)  # type: ignore[call-arg]
    return s


@pytest.fixture
def stores(settings: Settings):
    registry = Registry(settings.paths.registry_db)  # type: ignore[arg-type]
    vectors = VectorStore(settings.paths.qdrant_dir, "test_chunks", DIMENSION)  # type: ignore[arg-type]
    yield registry, vectors
    registry.close()
    vectors.close()


class FakeReranker:
    """Scores by keyword overlap. Crude, deterministic, and enough to test the
    pipeline's decisions rather than a model's judgement."""

    name = "fake"
    model = "fake"

    def rerank(self, query: str, passages, *, top_k=None) -> list[Scored]:
        wanted = set(query.lower().split())
        scored = []
        for i, passage in enumerate(passages):
            words = set(passage.lower().split())
            overlap = len(wanted & words) / max(len(wanted), 1)
            scored.append(Scored(index=i, score=overlap))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k] if top_k else scored


def _add(registry, vectors, embedder, settings, *, name, year, family, texts):
    from app.ingest.metadata import DocumentIdentity

    doc_id = f"{family}-{year}"
    identity = DocumentIdentity(
        doc_id=doc_id, title=name, source_name=f"{name}.pdf",
        policy_family=family, year=year, circular="",
    )
    chunks = [
        Chunk(
            chunk_id=f"{doc_id}:{n:04d}", doc_id=doc_id, title=name, policy_family=family,
            year=year, section=f"{n}. Clause", section_number=str(n), pages=(n,),
            text=text, tokens=len(text) // 4,
        )
        for n, text in enumerate(texts, 1)
    ]
    index_document(
        identity, chunks, sha256=f"hash-{doc_id}", pages=len(texts),
        registry=registry, vectors=vectors, embedder=embedder,
    )


def _retriever(stores, settings, reranker=FakeReranker()):
    registry, vectors = stores
    return Retriever(
        registry=registry, vectors=vectors,
        embedder=HashingEmbedder(settings.embedding),
        reranker=reranker, settings=settings,
    )


def test_nothing_relevant_is_a_refusal_not_a_best_guess(stores, settings: Settings) -> None:
    """The failure mode this prevents: handing the model the least-bad passage,
    which is how a grounded system ends up citing a real document for a claim it
    does not make."""
    registry, vectors = stores
    _add(registry, vectors, HashingEmbedder(settings.embedding), settings,
         name="Donations Policy", year=2024, family="donations",
         texts=["Donations require approval from the committee."])

    result = _retriever(stores, settings).search("submarine propulsion turbine metallurgy")
    assert result.refused
    assert result.passages == []


def test_an_empty_query_refuses_without_touching_the_stores(stores, settings: Settings) -> None:
    result = _retriever(stores, settings).search("   ")
    assert result.refused and result.dense_found == 0


def test_both_vintages_are_returned_and_the_older_is_marked(stores, settings) -> None:
    """Dropping the superseded edition would make the answer look unanimous when
    it is not, and the difference between the two is often the actual answer."""
    registry, vectors = stores
    embedder = HashingEmbedder(settings.embedding)
    for year in (2023, 2025):
        _add(registry, vectors, embedder, settings,
             name=f"Sanctions Compliance Policy {year}", year=year, family="sanctions",
             texts=[f"Sanctions screening threshold rules for {year}."])

    result = _retriever(stores, settings).search("sanctions screening threshold rules")

    assert len(result.passages) == 2
    assert result.vintage_conflicts == ["sanctions"]
    # Newest first, so a model reading in order meets the current rule first.
    assert result.passages[0].year == 2025
    assert result.passages[0].superseded is False
    assert result.passages[1].year == 2023
    assert result.passages[1].superseded is True


def test_a_single_vintage_is_never_marked_superseded(stores, settings) -> None:
    registry, vectors = stores
    _add(registry, vectors, HashingEmbedder(settings.embedding), settings,
         name="Donations Policy", year=2024, family="donations",
         texts=["Donations require approval from the committee."])

    result = _retriever(stores, settings).search("donations require approval committee")
    assert result.passages
    assert not any(p.superseded for p in result.passages)
    assert result.vintage_conflicts == []


def test_top_k_caps_what_reaches_the_model(stores, settings: Settings) -> None:
    registry, vectors = stores
    _add(registry, vectors, HashingEmbedder(settings.embedding), settings,
         name="Compliance Program", year=2023, family="compliance",
         texts=[f"Compliance monitoring control number {n} applies." for n in range(1, 15)])

    result = _retriever(stores, settings).search("compliance monitoring control applies", top_k=3)
    assert len(result.passages) <= 3


def test_without_a_reranker_the_pipeline_still_answers(stores, settings: Settings) -> None:
    """Development on a machine with no torch has to be possible. Fusion order
    is a usable fallback — but the refusal threshold lives on the reranker's
    scale, so nothing may be filtered by it here."""
    registry, vectors = stores
    _add(registry, vectors, HashingEmbedder(settings.embedding), settings,
         name="Donations Policy", year=2024, family="donations",
         texts=["Donations require approval from the committee."])

    result = _retriever(stores, settings, reranker=None).search("donations approval")
    assert not result.refused
    assert result.passages


def test_a_passage_records_which_half_of_retrieval_found_it(stores, settings) -> None:
    """`found_by` is diagnostic, not decoration: `keyword` on every result means
    the embedder is not doing its job, and that is otherwise invisible."""
    registry, vectors = stores
    _add(registry, vectors, HashingEmbedder(settings.embedding), settings,
         name="Donations Policy", year=2024, family="donations",
         texts=["Donations require approval from the committee."])

    result = _retriever(stores, settings).search("donations require approval")
    assert result.passages[0].found_by in {"both", "dense", "keyword"}


# --- the reranker provider, without loading 2.3 GB of weights ----------------


def test_scores_outside_zero_to_one_are_squashed_before_the_threshold() -> None:
    """`min_rerank_score` is a probability threshold and this model's head emits
    a single unbounded logit. sentence-transformers applies a sigmoid for a
    one-label cross-encoder, but that default has moved between versions — and
    if it ever stops, raw logits sail past the threshold and the system answers
    confidently from passages it should have refused on."""
    from app.providers.reranker.bge_reranker import _as_probabilities

    raw = _as_probabilities([8.2, -3.1, 0.0])
    assert raw.applied_sigmoid
    assert all(0.0 <= value <= 1.0 for value in raw.values)
    assert raw.values[0] > raw.values[2] > raw.values[1]  # order is preserved

    already = _as_probabilities([0.9, 0.1])
    assert not already.applied_sigmoid
    assert already.values == [0.9, 0.1]

    assert _as_probabilities([]).values == []


def test_the_reranker_is_registered_as_written_not_declared() -> None:
    """It was a Phase 04 placeholder. If this reverts to `declared`, the spec
    lost its target and `load_reranker` will refuse with a phase message."""
    from app.providers import registry as provider_registry

    spec = provider_registry.spec_for("reranker", "bge-reranker-v2-m3")
    assert spec.phase is None
    assert spec.target == "app.providers.reranker.bge_reranker:BgeRerankerV2M3"
    # No Ollama route exists for reranking, so torch is not optional here.
    assert set(spec.requires) == {"torch", "sentence_transformers"}


def test_reranking_sees_the_document_and_section_not_only_the_prose(
    stores, settings: Settings
) -> None:
    """A chunk carries its circular number and breadcrumb in metadata, never in
    its text. Reranking on the raw text alone therefore scored exactly the
    chunks keyword search was right to find as if they were irrelevant, and the
    threshold discarded them — the identifier query returned an unrelated chunk
    that happened to be *about* circulars instead."""
    from app.ingest.metadata import DocumentIdentity
    from app.providers.embedding.hashing import HashingEmbedder as _H

    registry, vectors = stores
    identity = DocumentIdentity(
        doc_id="sanctions-2025", title="Sanctions Compliance Policy",
        source_name="S.pdf", policy_family="sanctions", year=2025,
        circular="A-INST-2025-01",
    )
    chunk = Chunk(
        chunk_id="sanctions-2025:0001", doc_id="sanctions-2025",
        title=identity.title, policy_family="sanctions", year=2025,
        section="1. Scope", section_number="1", pages=(2,),
        text="Screening is performed against the list.", tokens=8,
    )
    index_document(identity, [chunk], sha256="h", pages=1, registry=registry,
                   vectors=vectors, embedder=_H(settings.embedding))

    retriever = _retriever(stores, settings)
    context = retriever._for_reranking(
        reciprocal_rank_fusion(
            [], [KeywordHit(chunk_id=chunk.chunk_id, doc_id="sanctions-2025",
                            section="1. Scope", page=2, text=chunk.text, score=1.0)]
        )[0]
    )

    assert "A-INST-2025-01" in context   # nowhere in the chunk's own text
    assert "Sanctions Compliance Policy" in context
    assert "1. Scope" in context
    assert chunk.text in context
