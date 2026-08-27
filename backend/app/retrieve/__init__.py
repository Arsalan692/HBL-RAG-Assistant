"""Hybrid retrieval: dense + keyword, fused, reranked, cut to what fits a prompt."""

from app.retrieve.fuse import Candidate, reciprocal_rank_fusion
from app.retrieve.search import Retriever, RetrievalResult, Passage

__all__ = [
    "Candidate",
    "Passage",
    "RetrievalResult",
    "Retriever",
    "reciprocal_rank_fusion",
]
