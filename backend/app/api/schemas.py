"""The wire shapes, mirroring `frontend/src/types.ts`.

Field names are camelCase here and nowhere else in the backend, because they
are the frontend's names and the frontend is already written against them. The
contract is that a component reading `mock.ts` today keeps working when the
data starts arriving from this API.

**Nothing is invented to fill a field.** `mock.ts` carries a `department` of
"Global Compliance", which reads like real metadata and is not — it was written
to make the mock look plausible. The documents themselves carry no department,
so this returns an empty string rather than a guess. A system built to stop a
model inventing confident details should not open by inventing them itself.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.generate.answer import Source as EngineSource
from app.store.registry import DocumentRow


class Source(BaseModel):
    """One citable passage. `index` is the number in the answer's `[1]` token."""

    id: str
    index: int
    title: str
    section: str
    page: int
    relevance: float

    #: Present in the frontend's type, absent from the documents. Empty rather
    #: than fabricated — the source panel skips a row with no value.
    department: str = ""
    #: The document's year, which is the only date the corpus actually states.
    effectiveDate: str = ""
    #: The circular number where there is one, e.g. A-INST-2025-01.
    version: str = ""

    excerpt: str
    #: True when a newer edition of the same policy is also indexed. Not in the
    #: original mock; the UI can badge it, and it must not be silently dropped.
    superseded: bool = False

    @classmethod
    def of(cls, source: EngineSource) -> Source:
        return cls(
            id=source.id,
            index=source.index,
            title=source.title,
            section=source.section,
            page=source.page,
            relevance=source.relevance,
            effectiveDate=str(source.year) if source.year else "",
            version=source.circular,
            excerpt=source.excerpt,
            superseded=source.superseded,
        )


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class DocumentSummary(BaseModel):
    """A row of the document library."""

    id: str
    title: str
    year: int | None = None
    policyFamily: str = ""
    circular: str = ""
    pages: int = 0
    chunks: int = 0
    status: str = "ready"
    error: str = ""
    #: True when another edition of the same policy is also indexed.
    hasOtherVintage: bool = False

    @classmethod
    def of(cls, row: DocumentRow, *, other_vintages: bool = False) -> DocumentSummary:
        return cls(
            id=row.doc_id,
            title=row.title,
            year=row.year,
            policyFamily=row.policy_family,
            circular=row.circular,
            pages=row.pages,
            chunks=row.chunk_count,
            status=row.status,
            error=row.error,
            hasOtherVintage=other_vintages,
        )


class IngestJob(BaseModel):
    """An upload on its way to being answerable."""

    id: str
    filename: str
    state: str
    #: Human-readable version of `state`, so the wording lives in one place.
    label: str
    #: Pages read so far, and how many there are. A total of 0 means "not
    #: counted yet" rather than "an empty document".
    pagesDone: int = 0
    pagesTotal: int = 0
    chunks: int = 0
    docId: str = ""
    error: str = ""
    #: Set when the file was byte-identical to something already indexed.
    duplicateOf: str = ""
    done: bool = False
    seconds: float = 0.0

    @classmethod
    def of(cls, job) -> IngestJob:  # noqa: ANN001 - avoids importing jobs here
        import time

        return cls(
            id=job.id,
            filename=job.filename,
            state=job.state,
            label=job.label,
            pagesDone=job.pages_done,
            pagesTotal=job.pages_total,
            chunks=job.chunks,
            docId=job.doc_id,
            error=job.error,
            duplicateOf=job.duplicate_of,
            done=job.done,
            seconds=round((job.finished_at or time.time()) - job.started_at, 1),
        )


class DeleteResponse(BaseModel):
    id: str
    deleted: bool
    vectorsRemoved: int = 0
    chunksRemoved: int = 0
    filesRemoved: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    ok: bool
    providers: dict[str, str]
    documents: int
    chunks: int
    #: Which embedder built the index, e.g. "bge-m3:1024". A client comparing
    #: this across machines can tell whether an index is portable.
    indexFingerprint: str = ""
