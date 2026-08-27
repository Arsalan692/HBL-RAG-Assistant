"""The retrieval pipeline, end to end.

    query
      ├─ dense   top 30   (bge-m3 → Qdrant, cosine)
      └─ keyword top 30   (FTS5 BM25)
             ↓ RRF fusion
        top 30 candidates
             ↓ cross-encoder
        top 8, or a refusal

Hybrid is not an optimisation here. These documents are built on exact
identifiers — `A-INST-2025-01`, CDD, EDD, STR, PEP, numeric thresholds — and
dense search reliably misses them, because an embedding of a clause number is
an embedding of nothing in particular. Keyword search finds them and misses
every paraphrase. Neither half is optional.

Two behaviours are deliberate and easy to mistake for bugs:

**Refusal.** When nothing clears `min_rerank_score`, this returns no passages
rather than the best of a bad list. The alternative — handing the model whatever
ranked highest — is how a grounded system ends up citing a real document for a
claim it does not make.

**Superseded vintages are surfaced, not dropped.** AML/KYC and Sanctions each
exist here as a 2023 and a 2025 edition. Silently keeping only the newer one
would be wrong in both directions: the older clause may be what someone asked
about, and where the two genuinely differ, that difference is the answer. So
older vintages are marked, ranked below their newer sibling, and reported.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Sequence

from app.config import Settings
from app.logging_config import get_logger
from app.providers.base import Embedder, Reranker
from app.retrieve.fuse import Candidate, reciprocal_rank_fusion
from app.store.registry import Registry
from app.store.vectors import VectorStore

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DocumentFacts:
    """What the registry knows about a chunk's document, cached per query."""

    title: str
    year: int | None = None
    policy_family: str = ""
    circular: str = ""


@dataclass
class Passage:
    """One retrieved chunk, with everything a citation needs."""

    chunk_id: str
    doc_id: str
    title: str
    section: str
    page: int
    text: str
    score: float
    found_by: str
    year: int | None = None
    policy_family: str = ""
    #: The document's circular number, e.g. A-INST-2025-01. Printed on the
    #: covering instruction and in no clause, so it reaches a citation only by
    #: being carried here.
    circular: str = ""
    #: True when a newer vintage of the same policy is also indexed.
    superseded: bool = False


@dataclass
class RetrievalResult:
    query: str
    passages: list[Passage] = field(default_factory=list)
    #: Candidates considered at each stage, for the frontend's retrieval stepper.
    dense_found: int = 0
    keyword_found: int = 0
    fused: int = 0
    reranked: int = 0
    seconds: float = 0.0
    #: Set when nothing cleared the threshold. The answer must say so.
    refused: bool = False
    #: Families where both an older and a newer vintage survived reranking.
    vintage_conflicts: list[str] = field(default_factory=list)

    @property
    def document_count(self) -> int:
        return len({p.doc_id for p in self.passages})


class Retriever:
    """Dense + keyword + fusion + rerank over the shared stores."""

    def __init__(
        self,
        *,
        registry: Registry,
        vectors: VectorStore,
        embedder: Embedder,
        reranker: Reranker | None,
        settings: Settings,
    ) -> None:
        self._registry = registry
        self._vectors = vectors
        self._embedder = embedder
        self._reranker = reranker
        self._settings = settings.retrieval
        self._doc_cache: dict[str, DocumentFacts] = {}
        # On CUDA the VRAM budget assumes all three models stay resident and
        # reloading would cost real time on every query. On CPU the same
        # simultaneity is what exhausts a 16 GB machine, and a few seconds of
        # reload is invisible beside a query that already takes a minute.
        self._release_between_stages = settings.runtime.device == "cpu"

    def search(self, query: str, *, top_k: int | None = None) -> RetrievalResult:
        started = time.perf_counter()
        result = RetrievalResult(query=query)
        limit = top_k or self._settings.rerank_top_k

        if not query.strip():
            result.refused = True
            return result

        dense = self._vectors.search(
            self._embedder.embed_query(query), limit=self._settings.dense_top_k
        )
        # The embedder's work is done — one query vector — and the reranker has
        # not loaded yet. Freeing 2.3 GB here is what keeps the two from ever
        # being resident together, which is the peak that killed a 16 GB
        # laptop mid-load with a segfault and no message.
        if self._release_between_stages:
            self.release_embedder()

        keyword = self._registry.search(query, limit=self._settings.keyword_top_k)
        result.dense_found = len(dense)
        result.keyword_found = len(keyword)

        candidates = reciprocal_rank_fusion(
            dense,
            keyword,
            k=self._settings.rrf_k,
            limit=self._settings.rerank_candidates,
        )
        result.fused = len(candidates)
        if not candidates:
            result.refused = True
            result.seconds = round(time.perf_counter() - started, 2)
            return result

        survivors = self._rerank(query, candidates, limit)
        result.reranked = len(survivors)

        result.passages = [self._to_passage(c) for c in survivors]
        self._mark_vintages(result)
        result.refused = not result.passages
        result.seconds = round(time.perf_counter() - started, 2)

        log.info(
            "retrieve.search",
            extra={
                "dense": result.dense_found,
                "keyword": result.keyword_found,
                "fused": result.fused,
                "kept": len(result.passages),
                "seconds": result.seconds,
                "refused": result.refused,
            },
        )
        return result

    def release_embedder(self) -> bool:
        """Drop the embedder's weights. Returns whether anything was freed.

        One query vector is all a search needs from it, and the reranker is
        about to want the same 2.3 GB.
        """
        return _unload(self._embedder, "retrieve.embedder_released")

    def release_reranker(self) -> bool:
        """Drop the cross-encoder's weights. Returns whether anything was freed.

        Reranking is finished the moment `search` returns, so holding ~2.3 GB
        through generation buys only the next query's load time. On a machine
        where that 2.3 GB is the difference between answering and dying, it is
        the wrong trade.
        """
        return _unload(self._reranker, "retrieve.reranker_released")

    # --- stages --------------------------------------------------------------

    def _rerank(
        self, query: str, candidates: Sequence[Candidate], limit: int
    ) -> list[Candidate]:
        """Cut to what actually reaches the model, or to nothing."""
        if self._reranker is None:
            # No cross-encoder available. Fusion order is a usable fallback for
            # development, but the refusal threshold is on the reranker's scale
            # and cannot be applied to RRF scores, so nothing is filtered here.
            log.warning("retrieve.no_reranker", extra={"detail": "returning fusion order"})
            for candidate in candidates[:limit]:
                candidate.rerank_score = candidate.fused_score
            return list(candidates[:limit])

        scored = self._reranker.rerank(query, [self._for_reranking(c) for c in candidates])
        kept: list[Candidate] = []
        for entry in scored:
            if entry.score < self._settings.min_rerank_score:
                # The list is descending, so the first failure ends it.
                break
            candidate = candidates[entry.index]
            candidate.rerank_score = entry.score
            kept.append(candidate)
            if len(kept) >= limit:
                break
        return kept

    def _for_reranking(self, candidate: Candidate) -> str:
        """The passage as the cross-encoder should see it: with its provenance.

        Raw chunk text alone loses the question badly. A chunk carries its
        document's circular number and its section breadcrumb in metadata, not
        in its prose, so a query naming either scores as if the passage were
        irrelevant — and the threshold then discards exactly the chunks keyword
        search was right to find.

        `A-INST-2025-01` is the case that proved it: keyword search surfaced all
        179 chunks of the two policies it names, and reranking dropped every one
        of them in favour of an unrelated chunk that happened to be *about*
        circulars. Titles and breadcrumbs also give the model something to
        anchor on when several policies use near-identical clause wording.
        """
        facts = self._document(candidate.doc_id)
        heading = " · ".join(part for part in (facts.title, facts.circular) if part)
        if candidate.section:
            heading = f"{heading} · {candidate.section}" if heading else candidate.section
        return f"{heading}\n{candidate.text}" if heading else candidate.text

    def _to_passage(self, candidate: Candidate) -> Passage:
        facts = self._document(candidate.doc_id)
        return Passage(
            chunk_id=candidate.chunk_id,
            doc_id=candidate.doc_id,
            title=facts.title,
            section=candidate.section,
            page=candidate.page,
            text=candidate.text,
            score=round(candidate.rerank_score, 4),
            found_by=candidate.found_by,
            year=facts.year,
            policy_family=facts.policy_family,
            circular=facts.circular,
        )

    def _document(self, doc_id: str) -> DocumentFacts:
        """What the registry knows about a document. Cached — a result set of
        eight passages is routinely eight rows from the same two documents."""
        if doc_id not in self._doc_cache:
            row = self._registry.get(doc_id)
            self._doc_cache[doc_id] = (
                DocumentFacts(row.title, row.year, row.policy_family, row.circular)
                if row
                else DocumentFacts(title=doc_id)
            )
        return self._doc_cache[doc_id]

    def _mark_vintages(self, result: RetrievalResult) -> None:
        """Flag passages from a policy that also has a newer edition indexed.

        Not a filter. Where the two vintages genuinely differ, that difference
        is usually the thing worth reporting, and dropping the older one would
        make the answer look unanimous when it is not.
        """
        if not self._settings.prefer_newest_vintage:
            return

        newest: dict[str, int] = {}
        for passage in result.passages:
            if passage.policy_family and passage.year is not None:
                newest[passage.policy_family] = max(
                    newest.get(passage.policy_family, passage.year), passage.year
                )

        conflicts: set[str] = set()
        for passage in result.passages:
            latest = newest.get(passage.policy_family)
            if latest is not None and passage.year is not None and passage.year < latest:
                passage.superseded = True
                conflicts.add(passage.policy_family)

        result.vintage_conflicts = sorted(conflicts)
        # Newer editions first within equal relevance, so a model reading the
        # passages in order meets the current rule before the superseded one.
        result.passages.sort(key=lambda p: (p.superseded, -p.score))


def _unload(provider: object | None, event: str) -> bool:
    """Release a provider's weights if it holds any. Optional by protocol —
    the hashing stand-in and the Ollama-served embedder have nothing to free."""
    unload = getattr(provider, "unload", None)
    if unload is None:
        return False
    unload()
    log.debug(event)
    return True
