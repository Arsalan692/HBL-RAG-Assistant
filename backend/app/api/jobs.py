"""Ingesting an uploaded PDF, in the background, with progress worth watching.

Upload cannot be a request that returns when the work is done. A scanned
sixty-page policy takes the vision model roughly fourteen seconds a page —
fifteen minutes before anything is searchable — and no browser, proxy or user
waits that long on one connection. So the upload returns a job id immediately
and the work continues on a worker thread.

Progress is per *page*, not a spinner, because that is the number the reader
actually wants: a page count they can watch move tells them the thing is alive
in a way a percentage invented from nothing does not.

Jobs live in memory. That is the honest scope for a single-process server with
one set of models: a restart loses the *record* of a job, never the work, since
extraction writes its markdown and its provenance sidecar to disk as it goes and
re-running resumes from that cache.

**The ingest holds the engine lock while it uses a model.** OCR, embedding and
answering all want the same GPU, or the same handful of CPU cores. Letting an
upload and a question run at once would not serve both faster; on a 16 GB
machine it is how the process dies.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.logging_config import get_logger

log = get_logger(__name__)

JobState = Literal["queued", "extracting", "chunking", "indexing", "ready", "failed", "duplicate"]

#: What the reader is told at each stage. Keyed by state so the wording lives
#: in one place rather than being reinvented in the interface.
LABELS: dict[JobState, str] = {
    "queued": "Waiting to start",
    "extracting": "Reading pages",
    "chunking": "Splitting into passages",
    "indexing": "Building the search index",
    "ready": "Ready to answer questions",
    "failed": "Failed",
    "duplicate": "Already in the library",
}


@dataclass
class Job:
    """One upload, from arrival to searchable."""

    id: str
    filename: str
    state: JobState = "queued"
    #: Pages read so far, and how many there are. Zero total means "not counted
    #: yet" rather than "an empty document".
    pages_done: int = 0
    pages_total: int = 0
    chunks: int = 0
    doc_id: str = ""
    error: str = ""
    #: Set when the upload was byte-identical to something already indexed.
    duplicate_of: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    @property
    def label(self) -> str:
        return LABELS[self.state]

    @property
    def done(self) -> bool:
        return self.state in ("ready", "failed", "duplicate")


class JobRegistry:
    """Every ingest this process has run, and the thread running the current one."""

    def __init__(self, *, keep: int = 50) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._keep = keep

    def create(self, filename: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], filename=filename)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            # Finished jobs are kept so the interface can show what happened,
            # but not forever.
            while len(self._order) > self._keep:
                self._jobs.pop(self._order.pop(0), None)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return [self._jobs[i] for i in reversed(self._order) if i in self._jobs]

    def active(self) -> list[Job]:
        return [job for job in self.all() if not job.done]


def ingest(job: Job, pdf_path: Path, engine) -> None:  # noqa: ANN001 - avoids a cycle
    """Route, read, chunk and index one PDF. Runs on a worker thread.

    Every failure marks the job rather than raising into the void: a thread
    that dies silently leaves an upload stuck at "Waiting to start" forever.
    """
    from app.ingest.extract import extract_document, sha256_of
    from app.ingest.pipeline import chunk_corpus
    from app.providers import registry as providers
    from app.store.index import index_document

    try:
        digest = sha256_of(pdf_path)

        with engine.exclusive():
            existing = engine.registry.find_by_hash(digest)
        if existing is not None:
            # Indexing it twice would double that policy's weight in retrieval,
            # so the same clause would outrank a unique one for being filed
            # twice. This corpus already contains one such pair.
            job.duplicate_of = existing.title or existing.doc_id
            job.state = "duplicate"
            job.finished_at = time.time()
            pdf_path.unlink(missing_ok=True)
            log.info("ingest.duplicate", extra={"file": job.filename, "of": existing.doc_id})
            return

        job.state = "extracting"

        def on_page(_record, total: int) -> None:  # noqa: ANN001
            job.pages_done += 1
            job.pages_total = total

        ocr = providers.load_ocr(engine.settings)
        try:
            with engine.exclusive():
                record = extract_document(pdf_path, engine.settings, ocr, on_page=on_page)
        finally:
            # Give the 7.4 GB vision model back the moment this document is
            # done. It stays resident between pages because reloading it per
            # page would dominate the run — but afterwards it is dead weight,
            # and on a 16 GB machine it is what starves the next question. The
            # server segfaulted exactly this way: an ingest finished, left
            # qwen2.5vl:7b resident, and the following chat died with 2.2 GB
            # free.
            release = getattr(ocr, "release", None)
            if release is not None:
                release()

        if not record.markdown_path:
            raise RuntimeError("extraction produced no markdown")

        job.state = "chunking"
        documents = chunk_corpus(engine.settings, [Path(record.markdown_path)])
        if not documents:
            raise RuntimeError("the document produced no searchable passages")
        document = documents[0]

        job.state = "indexing"
        with engine.exclusive():
            result = index_document(
                document.identity,
                document.chunks,
                sha256=digest,
                pages=record.pages,
                registry=engine.registry,
                vectors=engine.vectors,
                embedder=engine.embedder,
            )

        if result.error:
            raise RuntimeError(result.error)

        job.doc_id = result.doc_id
        job.chunks = result.chunks
        job.state = "ready"
        log.info(
            "ingest.ready",
            extra={"file": job.filename, "doc_id": result.doc_id, "chunks": result.chunks},
        )

    except Exception as exc:  # noqa: BLE001 - the job must record every failure
        job.state = "failed"
        job.error = str(exc)[:400]
        log.warning("ingest.failed", extra={"file": job.filename, "error": job.error})
    finally:
        job.finished_at = time.time()


def start(job: Job, pdf_path: Path, engine) -> None:  # noqa: ANN001
    """Run `ingest` on a daemon thread so it can never hold the process open."""
    threading.Thread(
        target=ingest, args=(job, pdf_path, engine), name=f"ingest-{job.id}", daemon=True
    ).start()
