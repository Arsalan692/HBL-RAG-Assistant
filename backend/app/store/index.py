"""Putting chunks into both stores, and taking documents out of both.

Indexing is the easy direction. Deletion is the one that has to be right: the
requirement is that after removing a document, *no fragment of it can be
retrieved* — not a vector, not a keyword hit, not a cached page image, not the
parsed markdown it came from.

Two stores cannot share a transaction. SQLite holds the registry, the chunks
and the keyword index and can commit all three together; Qdrant is a separate
store with its own files. So deletion is ordered so that every failure leaves
evidence rather than a half-deleted document that looks whole:

1. mark the document `deleting` — committed, survives a crash
2. drop its vectors
3. drop its registry row, chunks and keyword entries in one transaction
4. remove its parsed markdown, sidecar and rendered page images

A crash after step 1 leaves a row saying `deleting`, which `unfinished_deletions`
finds and `purge` can finish. A crash before it changes nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from app.config import Settings
from app.ingest.chunk import Chunk
from app.ingest.metadata import DocumentIdentity
from app.logging_config import get_logger
from app.providers.base import Embedder
from app.store.registry import Registry
from app.store.vectors import VectorStore

log = get_logger(__name__)


@dataclass
class IndexResult:
    doc_id: str
    title: str
    chunks: int = 0
    vectors: int = 0
    seconds: float = 0.0
    skipped_duplicate_of: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class DeleteResult:
    doc_id: str
    found: bool = False
    vectors_removed: int = 0
    chunks_removed: int = 0
    files_removed: list[str] = field(default_factory=list)


def index_document(
    identity: DocumentIdentity,
    chunks: Sequence[Chunk],
    *,
    sha256: str,
    pages: int,
    registry: Registry,
    vectors: VectorStore,
    embedder: Embedder,
    batch_size: int = 16,
    on_progress: Callable[[int, int], None] | None = None,
) -> IndexResult:
    """Embed and store one document's chunks, moving it through its states."""
    result = IndexResult(doc_id=identity.doc_id, title=identity.title)
    started = time.perf_counter()

    # The exact re-upload check. This corpus already contains one duplicate,
    # and indexing it twice would double that policy's weight in retrieval.
    if existing := registry.find_by_hash(sha256):
        if existing.doc_id != identity.doc_id:
            result.skipped_duplicate_of = existing.doc_id
            log.info(
                "index.duplicate",
                extra={"doc_id": identity.doc_id, "of": existing.doc_id},
            )
            return result

    registry.upsert_document(
        doc_id=identity.doc_id,
        title=identity.title,
        source_name=identity.source_name,
        policy_family=identity.policy_family,
        year=identity.year,
        circular=identity.circular,
        sha256=sha256,
        pages=pages,
        status="embedding",
    )

    try:
        # Replace before embedding: if this run dies partway, the document is
        # left with no chunks and a status of `embedding`, which is visibly
        # unfinished. Leaving the old ones would look complete and be stale.
        registry.replace_chunks(identity.doc_id, chunks)

        stored = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            embedded = embedder.embed_documents([c.text for c in batch])
            stored += vectors.upsert(batch, embedded)
            if on_progress:
                on_progress(min(start + batch_size, len(chunks)), len(chunks))

        registry.set_status(identity.doc_id, "ready")
        result.chunks = len(chunks)
        result.vectors = stored

    except Exception as exc:
        registry.set_status(identity.doc_id, "failed", str(exc)[:400])
        result.error = str(exc)[:400]
        log.warning("index.failed", extra={"doc_id": identity.doc_id, "error": result.error})

    result.seconds = round(time.perf_counter() - started, 2)
    return result


def delete_document(
    doc_id: str,
    *,
    registry: Registry,
    vectors: VectorStore,
    settings: Settings,
    remove_files: bool = True,
) -> DeleteResult:
    """Remove every trace of a document from both stores and from disk."""
    result = DeleteResult(doc_id=doc_id)
    row = registry.get(doc_id)
    if row is None:
        return result
    result.found = True
    result.chunks_removed = registry.count_chunks(doc_id)

    # 1. Commit the intent first. Everything after this is recoverable because
    #    of this line.
    registry.mark_deleting(doc_id)

    # 2. Vectors, which cannot join the transaction below.
    before = vectors.count(doc_id)
    vectors.delete_document(doc_id)
    result.vectors_removed = before

    # 3. Registry row, chunks and keyword entries, atomically.
    registry.delete_document(doc_id)

    # 4. Derived files. These carry the same confidential content as the PDF,
    #    so "deleted" has to mean gone from disk, not just unindexed.
    if remove_files:
        result.files_removed = _remove_derived_files(doc_id, row.source_name, settings)

    log.info(
        "index.deleted",
        extra={
            "doc_id": doc_id,
            "vectors": result.vectors_removed,
            "chunks": result.chunks_removed,
            "files": len(result.files_removed),
        },
    )
    return result


def _remove_derived_files(doc_id: str, source_name: str, settings: Settings) -> list[str]:
    """Parsed markdown, its provenance sidecar, and every rendered page image."""
    removed: list[str] = []
    parsed = settings.paths.parsed_dir
    images = settings.paths.page_image_dir

    stem = _slug(source_name) or doc_id
    candidates: list[Path] = []
    if parsed is not None:
        candidates += [parsed / f"{stem}.md", parsed / f"{stem}.pages.json"]
    if images is not None and images.exists():
        candidates += sorted(images.glob(f"{stem}_p*.png"))

    for path in candidates:
        try:
            if path.exists():
                path.unlink()
                removed.append(path.name)
        except OSError as exc:  # a locked file should not abort the delete
            log.warning("index.file_not_removed", extra={"path": str(path), "error": str(exc)})
    return removed


def _slug(name: str) -> str:
    """The same stem extraction `extract` used when writing those files."""
    keep = [c if c.isalnum() or c in "-_" else "-" for c in Path(name).stem]
    return "".join(keep).strip("-")[:80]


def purge_unfinished(
    registry: Registry, vectors: VectorStore, settings: Settings
) -> list[DeleteResult]:
    """Finish deletions a previous run started and did not complete."""
    results = []
    for row in registry.unfinished_deletions():
        log.warning("index.resuming_delete", extra={"doc_id": row.doc_id})
        results.append(
            delete_document(row.doc_id, registry=registry, vectors=vectors, settings=settings)
        )
    return results
