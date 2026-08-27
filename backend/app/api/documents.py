"""The document library: what is indexed, and removing it.

Deletion is the endpoint that has to be right. The requirement is not that a
document disappears from a list — it is that no fragment of it can be retrieved
afterwards: not a vector, not a keyword hit, not the parsed markdown, not a
rendered page image. `delete_document` already does that in an order where every
failure leaves evidence; this exposes it and reports what actually went.

Upload is deliberately **not** here yet. Ingesting a PDF means routing every
page, running a vision model over the scans and re-embedding — about an hour of
work for a large document. That needs a job queue and a progress channel, not a
request that holds a connection open for an hour, and it is honest to say so
rather than ship an endpoint that times out.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.engine import Engine
from app.api.schemas import DeleteResponse, DocumentSummary, HealthResponse
from app.logging_config import get_logger
from app.providers import registry as providers
from app.store.index import delete_document

log = get_logger(__name__)

router = APIRouter()


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(request: Request) -> list[DocumentSummary]:
    engine: Engine = request.app.state.engine
    with engine.exclusive():
        rows = engine.registry.documents()

    # Which policies exist in more than one edition. The library should show
    # that: two rows with the same title and different years look like a
    # duplicate unless the interface can say they are rival vintages.
    families: dict[str, int] = {}
    for row in rows:
        if row.policy_family:
            families[row.policy_family] = families.get(row.policy_family, 0) + 1

    return [
        DocumentSummary.of(row, other_vintages=families.get(row.policy_family, 0) > 1)
        for row in rows
    ]


@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
def remove_document(doc_id: str, request: Request) -> DeleteResponse:
    engine: Engine = request.app.state.engine
    with engine.exclusive():
        if engine.registry.get(doc_id) is None:
            raise HTTPException(status_code=404, detail=f"no document {doc_id!r} is indexed")

        result = delete_document(
            doc_id,
            registry=engine.registry,
            vectors=engine.vectors,
            settings=engine.settings,
        )

    return DeleteResponse(
        id=doc_id,
        deleted=result.found,
        vectorsRemoved=result.vectors_removed,
        chunksRemoved=result.chunks_removed,
        filesRemoved=result.files_removed,
    )


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """What this process has loaded and what it is serving.

    Reports the index fingerprint because it is the one piece of state that can
    make every answer silently wrong: an index built by a different embedder
    still returns results, still scores them, and means nothing.
    """
    engine: Engine = request.app.state.engine
    statuses = {s.interface: f"{s.name} ({s.state})" for s in providers.status_all(engine.settings)}

    with engine.exclusive():
        documents = len(engine.registry.documents())
        chunks = engine.registry.count_chunks()
        fingerprint = engine.registry.index_fingerprint()

    return HealthResponse(
        ok=True,
        providers=statuses,
        documents=documents,
        chunks=chunks,
        indexFingerprint=fingerprint,
    )
