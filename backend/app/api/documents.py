"""The document library: what is indexed, and removing it.

Deletion is the endpoint that has to be right. The requirement is not that a
document disappears from a list — it is that no fragment of it can be retrieved
afterwards: not a vector, not a keyword hit, not the parsed markdown, not a
rendered page image. `delete_document` already does that in an order where every
failure leaves evidence; this exposes it and reports what actually went.

Upload returns a job id rather than the finished document. A scanned sixty-page
policy takes the vision model a quarter of an hour, which no connection should
be asked to hold open — so `POST /documents` accepts the file, starts the work
on a worker thread and answers immediately. `GET /documents/jobs` is where the
progress lives.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.api import jobs as jobqueue
from app.api.engine import Engine
from app.api.schemas import (
    DeleteResponse,
    DocumentSummary,
    HealthResponse,
    IngestJob,
)
from app.logging_config import get_logger
from app.providers import registry as providers
from app.store.index import delete_document

log = get_logger(__name__)

router = APIRouter()

#: Uploads are capped rather than trusted. The largest document in this corpus
#: is about 8 MB; a file far past that is a mistake or an attack, and either way
#: it should be refused before it is written to disk.
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024

#: A PDF starts with this. Checked because a filename extension is a claim made
#: by whoever uploaded the file, and the extractor would otherwise fail deep
#: inside PyMuPDF with a message about the wrong thing.
PDF_MAGIC = b"%PDF-"


def safe_filename(name: str) -> str:
    """A filename that cannot escape the documents directory.

    Path separators, `..`, drive letters and control characters are all removed
    rather than escaped: an uploaded name is untrusted input that decides where
    bytes land on disk, and the only safe treatment is to keep the readable
    part and rebuild the path ourselves.
    """
    base = Path(name.replace("\\", "/")).name
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    base = re.sub(r'[<>:"|?*]', "-", base).strip(" .")
    if not base.lower().endswith(".pdf"):
        base = f"{base}.pdf"
    return base[:150] or "upload.pdf"


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(request: Request) -> list[DocumentSummary]:
    engine: Engine = request.app.state.engine
    # No engine lock: this reads SQLite and nothing else, and the registry
    # guards its own connection. An ingest holds the model lock for the fifteen
    # minutes it takes to read a scanned policy, and the library must stay
    # listable throughout — that is the screen showing the progress.
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


@router.post("/documents", response_model=IngestJob, status_code=202)
async def upload_document(request: Request, file: UploadFile = File(...)) -> IngestJob:
    """Accept a PDF and start ingesting it. Returns immediately with a job id.

    202 rather than 201: nothing has been created yet. The document becomes
    answerable minutes from now, and saying so in the status code is more
    honest than implying it is already there.
    """
    engine: Engine = request.app.state.engine
    registry: jobqueue.JobRegistry = request.app.state.jobs

    documents_dir = engine.settings.paths.documents_dir
    if documents_dir is None:
        raise HTTPException(status_code=500, detail="no documents directory is configured")
    documents_dir.mkdir(parents=True, exist_ok=True)

    name = safe_filename(file.filename or "upload.pdf")
    target = documents_dir / name
    if target.exists():
        raise HTTPException(
            status_code=409,
            detail=f"{name!r} is already in the library. Delete it first to replace it.",
        )

    # Streamed to disk in pieces rather than read into memory, and checked as
    # it goes: a 2 GB upload should be refused, not buffered first.
    size = 0
    first = b""
    try:
        with target.open("wb") as out:
            while piece := await file.read(CHUNK_BYTES):
                if not first:
                    first = piece[: len(PDF_MAGIC)]
                    if not first.startswith(PDF_MAGIC):
                        raise HTTPException(
                            status_code=415,
                            detail="that file is not a PDF. Only PDFs can be indexed.",
                        )
                size += len(piece)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{name!r} is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                    )
                out.write(piece)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"could not save the file: {exc}") from exc

    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="that file is empty.")

    job = registry.create(name)
    jobqueue.start(job, target, engine)
    log.info("api.upload", extra={"file": name, "bytes": size, "job": job.id})
    return IngestJob.of(job)


@router.get("/documents/jobs", response_model=list[IngestJob])
def list_jobs(request: Request) -> list[IngestJob]:
    """Every ingest this process has run, newest first.

    Polled rather than pushed. An ingest reports once a page — every fourteen
    seconds or so — and a second connection held open for a quarter of an hour
    to carry that is a worse trade than asking again.
    """
    registry: jobqueue.JobRegistry = request.app.state.jobs
    return [IngestJob.of(job) for job in registry.all()]


@router.get("/documents/jobs/{job_id}", response_model=IngestJob)
def get_job(job_id: str, request: Request) -> IngestJob:
    registry: jobqueue.JobRegistry = request.app.state.jobs
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no job {job_id!r}")
    return IngestJob.of(job)


@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
def remove_document(doc_id: str, request: Request) -> DeleteResponse:
    engine: Engine = request.app.state.engine
    if engine.registry.get(doc_id) is None:
        raise HTTPException(status_code=404, detail=f"no document {doc_id!r} is indexed")

    # The model lock *is* taken here: deletion writes to both stores and must
    # not interleave with an ingest writing the same rows.
    with engine.exclusive():
        result = delete_document(
            doc_id,
            registry=engine.registry,
            vectors=engine.vectors,
            settings=engine.settings,
            # Documents reach the library by being uploaded here, so removing
            # one means the PDF too. Leaving it behind would also block
            # re-uploading the same filename.
            remove_source=True,
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
