"""The dense half of retrieval: a local Qdrant collection.

Embedded mode — Qdrant runs inside this process against a directory on disk,
with no server and no Docker. That is not a compromise for development: adding
a container runtime to a locked-down bank workstation is a permission request,
while a directory is a directory.

Payload indexes are created explicitly rather than left to Qdrant's defaults,
because every one of them backs a filter the system actually applies:
`doc_id` for deletion, `policy_family` and `year` for preferring the newer
vintage of a policy over the superseded one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from app.errors import ProviderUnavailable
from app.ingest.chunk import Chunk
from app.logging_config import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class VectorHit:
    chunk_id: str
    doc_id: str
    section: str
    page: int
    text: str
    score: float


def _point_id(chunk_id: str) -> str:
    """Qdrant wants a UUID or an integer, and chunk ids are neither.

    Derived from the chunk id rather than random, so re-indexing the same chunk
    overwrites its point instead of adding a second copy of it.
    """
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


class VectorStore:
    """A Qdrant collection holding one point per chunk."""

    def __init__(self, path: Path, collection: str, dimension: int) -> None:
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise ProviderUnavailable(
                "qdrant-client is not installed. Run: pip install qdrant-client"
            ) from exc

        self._models = models
        self.collection = collection
        self.dimension = dimension
        path.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=str(path))
        self._ensure_collection()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_collection(self) -> None:
        models = self._models
        existing = {c.name for c in self._client.get_collections().collections}
        if self.collection not in existing:
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=self.dimension,
                    # Cosine because bge-m3 embeddings are normalised; with
                    # unit vectors it is equivalent to dot product and does not
                    # care if some future embedder forgets to normalise.
                    distance=models.Distance.COSINE,
                ),
            )
            log.info(
                "vectors.created",
                extra={"collection": self.collection, "dimension": self.dimension},
            )

        # Each of these backs a filter the system applies. `doc_id` is the one
        # deletion depends on, so an unindexed payload here would make removing
        # a document a full scan.
        #
        # Embedded Qdrant ignores them and says so, once per field per run. It
        # filters correctly regardless — the index is an optimisation, and at
        # 901 points there is nothing to optimise. Declared anyway so that
        # moving to a Qdrant server later is a config change and not a
        # rediscovery of which fields needed indexing.
        import warnings
        for field, schema in (
            ("doc_id", "keyword"),
            ("policy_family", "keyword"),
            ("year", "integer"),
            ("kind", "keyword"),
        ):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    self._client.create_payload_index(
                        collection_name=self.collection,
                        field_name=field,
                        field_schema=schema,
                    )
            except Exception:  # already present, which is the normal case
                pass

    # --- writing -------------------------------------------------------------

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> int:
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if not chunks:
            return 0

        models = self._models
        points = [
            models.PointStruct(
                id=_point_id(chunk.chunk_id),
                vector=list(vector),
                payload={
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "title": chunk.title,
                    "policy_family": chunk.policy_family,
                    "year": chunk.year,
                    "section": chunk.section,
                    "section_number": chunk.section_number,
                    "page": chunk.pages[0] if chunk.pages else 0,
                    "pages": list(chunk.pages),
                    "kind": chunk.kind,
                    "text": chunk.text,
                },
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        self._client.upsert(collection_name=self.collection, points=points, wait=True)
        return len(points)

    def delete_document(self, doc_id: str) -> None:
        """Drop every point belonging to one document."""
        models = self._models
        self._client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
                )
            ),
            wait=True,
        )
        log.info("vectors.deleted", extra={"doc_id": doc_id})

    def drop(self) -> int:
        """Empty the collection. Returns how many points were removed.

        Deliberately *not* `delete_collection` followed by a recreate, which is
        the obvious way to write this and does not work in embedded mode: the
        collection disappears from `get_collections()`, and then recreating it
        under the same name brings every old point back, because the on-disk
        data was never purged. That reads as success and leaves the stale
        vectors in place — exactly the failure this method exists to prevent.

        An empty `Filter` matches everything, so this removes all points while
        keeping the collection and its payload indexes.
        """
        models = self._models
        points = self.count()
        self._client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(filter=models.Filter()),
            wait=True,
        )
        remaining = self.count()
        if remaining:
            raise RuntimeError(
                f"{self.collection} still holds {remaining} points after a drop. "
                "Refusing to continue, because the next step would mix vector spaces."
            )
        log.warning("vectors.dropped", extra={"collection": self.collection, "points": points})
        return points

    # --- reading -------------------------------------------------------------

    def search(
        self,
        vector: Sequence[float],
        limit: int = 30,
        *,
        doc_ids: Sequence[str] | None = None,
    ) -> list[VectorHit]:
        models = self._models
        query_filter = None
        if doc_ids:
            query_filter = models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchAny(any=list(doc_ids)))]
            )

        found = self._client.query_points(
            collection_name=self.collection,
            query=list(vector),
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        ).points

        return [
            VectorHit(
                chunk_id=p.payload.get("chunk_id", ""),
                doc_id=p.payload.get("doc_id", ""),
                section=p.payload.get("section", ""),
                page=int(p.payload.get("page", 0) or 0),
                text=p.payload.get("text", ""),
                score=float(p.score),
            )
            for p in found
        ]

    def count(self, doc_id: str | None = None) -> int:
        models = self._models
        count_filter = None
        if doc_id:
            count_filter = models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
            )
        return int(
            self._client.count(
                collection_name=self.collection, count_filter=count_filter, exact=True
            ).count
        )

    def info(self) -> dict[str, Any]:
        return {"collection": self.collection, "dimension": self.dimension, "points": self.count()}
