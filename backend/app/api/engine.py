"""The long-lived objects an API process holds, and the lock around them.

Loading bge-m3 takes 20 seconds and 2.3 GB. Doing that per request would make
the first token arrive a minute late, so the models, the registry and the
vector store are opened once at startup and shared.

**Requests are serialised, deliberately.** There is one GPU, or on the laptop
one set of CPU cores, and a second concurrent question would not run twice as
fast — it would run both half as fast while doubling peak memory, which on a
16 GB machine is how the ingest pipeline segfaulted. A lock makes the queueing
explicit instead of leaving it to whichever allocation fails first.

Two things are also true of the stores themselves: SQLite refuses to be used
from a thread other than the one that opened it unless told otherwise, and
FastAPI runs synchronous endpoints on a thread pool. `check_same_thread=False`
plus this lock is the honest combination — the flag alone would just move the
failure somewhere harder to see.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from app.config import Settings
from app.errors import ProviderError
from app.generate.answer import Answerer
from app.logging_config import get_logger
from app.providers import registry as providers
from app.retrieve.search import Retriever
from app.store.index import ensure_same_embedder
from app.store.registry import Registry
from app.store.vectors import VectorStore

log = get_logger(__name__)


class Engine:
    """Everything a request needs, opened once and guarded by one lock."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()

        self.registry = Registry(settings.paths.registry_db, same_thread=False)  # type: ignore[arg-type]
        self.vectors = VectorStore(
            settings.paths.qdrant_dir,  # type: ignore[arg-type]
            settings.retrieval.qdrant_collection,
            settings.embedding.dimension,
        )

        self.embedder = providers.load_embedder(settings)
        self.llm = providers.load_llm(settings)

        self.reranker = None
        try:
            self.reranker = providers.load_reranker(settings)
        except ProviderError as exc:
            # Answerable without it, but not well: the refusal threshold lives
            # on the reranker's scale, so nothing can be filtered by relevance.
            log.warning("api.no_reranker", extra={"detail": str(exc)[:200]})

        # Refuse to serve an index built by a different embedder. Doing this at
        # startup rather than per request means the process fails to boot
        # instead of answering nonsense confidently.
        ensure_same_embedder(self.registry, self.vectors, self.embedder)

        self.retriever = Retriever(
            registry=self.registry,
            vectors=self.vectors,
            embedder=self.embedder,
            reranker=self.reranker,
            settings=settings,
        )
        self.answerer = Answerer(retriever=self.retriever, llm=self.llm, settings=settings)

        log.info(
            "api.engine_ready",
            extra={
                "embedder": self.embedder.fingerprint,
                "reranker": getattr(self.reranker, "name", "none"),
                "llm": self.llm.model,
                "documents": len(self.registry.documents()),
            },
        )

    @contextmanager
    def exclusive(self) -> Iterator[Engine]:
        """Hold the models for the duration of one operation.

        Every route that touches a model or a store goes through this. It is a
        plain lock rather than a queue because the waiting is the point: a
        client that sends two questions at once should get them one after the
        other, not both slowly.
        """
        with self._lock:
            yield self

    def close(self) -> None:
        self.registry.close()
        self.vectors.close()
        for model in (self.embedder, self.reranker, self.llm):
            unload = getattr(model, "unload", None)
            if unload is not None:
                unload()
        log.info("api.engine_closed")
