"""Reciprocal Rank Fusion: combining two rankings that share no score scale.

Dense search returns cosine similarities, roughly 0.3–0.9 and clustered near the
top. FTS5 returns BM25, unbounded and dependent on corpus statistics. Averaging
them, or normalising each to 0..1 first, both quietly let one list dominate
whenever its spread happens to be wider on a given query.

RRF ignores the scores entirely and uses only positions:

    score(d) = sum over lists of 1 / (k + rank(d))

`k` (60 by default) flattens the curve near the top, so first place is worth
1/61 and second 1/62 — close enough that a document ranked 2nd by both methods
beats one ranked 1st by a single method. That is the behaviour this corpus
needs: a chunk that dense search likes for its meaning *and* keyword search
likes for containing `A-INST-2025-01` is the one that should win.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from app.store.registry import KeywordHit
from app.store.vectors import VectorHit


@dataclass
class Candidate:
    """One chunk, with where each retriever placed it and why it survived."""

    chunk_id: str
    doc_id: str
    section: str
    page: int
    text: str
    #: 1-based positions. None means that retriever did not return it at all.
    dense_rank: int | None = None
    keyword_rank: int | None = None
    fused_score: float = 0.0
    rerank_score: float = 0.0

    @property
    def found_by(self) -> str:
        """Which halves of retrieval agreed. Shown in `hbl search`, and useful
        when a result is surprising: `both` and `keyword` mean very different
        things about why a chunk is here."""
        if self.dense_rank and self.keyword_rank:
            return "both"
        return "dense" if self.dense_rank else "keyword"


def reciprocal_rank_fusion(
    dense: Sequence[VectorHit],
    keyword: Sequence[KeywordHit],
    *,
    k: int = 60,
    limit: int | None = None,
) -> list[Candidate]:
    """Fuse two ranked lists into one, by position rather than by score."""
    merged: dict[str, Candidate] = {}

    for rank, hit in enumerate(dense, start=1):
        candidate = _ensure(merged, hit.chunk_id, hit.doc_id, hit.section, hit.page, hit.text)
        candidate.dense_rank = rank
        candidate.fused_score += 1.0 / (k + rank)

    for rank, hit in enumerate(keyword, start=1):
        candidate = _ensure(merged, hit.chunk_id, hit.doc_id, hit.section, hit.page, hit.text)
        candidate.keyword_rank = rank
        candidate.fused_score += 1.0 / (k + rank)

    ranked = sorted(
        merged.values(),
        # Ties are broken toward whatever dense search put first, so the order
        # is deterministic rather than dictionary insertion order.
        key=lambda c: (-c.fused_score, c.dense_rank or 10**6, c.chunk_id),
    )
    return ranked[:limit] if limit else ranked


def _ensure(
    merged: dict[str, Candidate], chunk_id: str, doc_id: str, section: str, page: int, text: str
) -> Candidate:
    if chunk_id not in merged:
        merged[chunk_id] = Candidate(
            chunk_id=chunk_id, doc_id=doc_id, section=section, page=page, text=text
        )
    return merged[chunk_id]
