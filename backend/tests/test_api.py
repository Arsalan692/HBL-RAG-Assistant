"""The HTTP surface.

Runs against a hand-built engine holding a temporary index and fake models, so
these need no weights, no corpus and no Ollama. What is being tested is the
contract the frontend was written against — event names, their order, and the
field names in `types.ts` — not whether a model can write.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.app import create_app  # noqa: E402
from app.api.engine import Engine  # noqa: E402
from app.config import EmbeddingSettings, Settings  # noqa: E402
from app.generate.answer import Answerer  # noqa: E402
from app.ingest.chunk import Chunk  # noqa: E402
from app.ingest.metadata import DocumentIdentity  # noqa: E402
from app.providers.embedding.hashing import HashingEmbedder  # noqa: E402
from app.retrieve.search import Retriever  # noqa: E402
from app.store.index import ensure_same_embedder, index_document  # noqa: E402
from app.store.registry import Registry  # noqa: E402
from app.store.vectors import VectorStore  # noqa: E402

DIMENSION = 64


class FakeLLM:
    name = "fake"
    model = "fake"

    def __init__(self, answer: str = "Screening is required [1].") -> None:
        self.answer = answer

    def stream(self, messages, **kwargs):
        for word in self.answer.split(" "):
            yield word + " "

    def complete(self, messages, **kwargs):  # pragma: no cover
        raise NotImplementedError


class FakeReranker:
    """Scores by word overlap.

    Deliberately not a constant: a reranker that returns 1.0 for everything can
    never refuse, which would make the refusal test pass for the wrong reason
    and hide the behaviour it exists to check.
    """

    name = "fake"
    model = "fake"

    def rerank(self, query, passages, *, top_k=None):
        from app.providers.base import Scored

        wanted = set(query.lower().split())
        scored = [
            Scored(index=i, score=len(wanted & set(p.lower().split())) / max(len(wanted), 1))
            for i, p in enumerate(passages)
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k] if top_k else scored


class StubEngine(Engine):
    """An Engine assembled by hand — no model loading, no provider registry."""

    def __init__(self, settings: Settings, *, llm=None) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self.registry = Registry(settings.paths.registry_db, same_thread=False)  # type: ignore[arg-type]
        self.vectors = VectorStore(
            settings.paths.qdrant_dir, "test_chunks", DIMENSION  # type: ignore[arg-type]
        )
        self.embedder = HashingEmbedder(settings.embedding)
        self.llm = llm or FakeLLM()
        self.reranker = FakeReranker()
        self.retriever = Retriever(
            registry=self.registry, vectors=self.vectors, embedder=self.embedder,
            reranker=self.reranker, settings=settings,
        )
        self.answerer = Answerer(retriever=self.retriever, llm=self.llm, settings=settings)
        # The real Engine refuses to serve an index built by a different
        # embedder. The stub stamps it the same way, so `/health` reports a
        # fingerprint rather than an empty string.
        ensure_same_embedder(self.registry, self.vectors, self.embedder)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.paths.registry_db = tmp_path / "registry.sqlite"
    s.paths.qdrant_dir = tmp_path / "qdrant"
    s.paths.parsed_dir = tmp_path / "parsed"
    s.paths.page_image_dir = tmp_path / "images"
    s.paths.parsed_dir.mkdir(parents=True, exist_ok=True)
    s.embedding = EmbeddingSettings(_env_file=None, dimension=DIMENSION)  # type: ignore[call-arg]
    return s


def _seed(engine: StubEngine, *, title: str, year: int, family: str, circular: str = "") -> str:
    doc_id = f"{family}-{year}"
    identity = DocumentIdentity(
        doc_id=doc_id, title=title, source_name=f"{title}.pdf",
        policy_family=family, year=year, circular=circular,
    )
    chunks = [
        Chunk(
            chunk_id=f"{doc_id}:0001", doc_id=doc_id, title=title, policy_family=family,
            year=year, section="1. Screening", section_number="1", pages=(2,),
            text="Screening is performed against the sanctions list.", tokens=9,
        )
    ]
    index_document(identity, chunks, sha256=f"h-{doc_id}", pages=1,
                   registry=engine.registry, vectors=engine.vectors, embedder=engine.embedder)
    return doc_id


@pytest.fixture
def client(settings: Settings):
    engine = StubEngine(settings)
    _seed(engine, title="Sanctions Compliance Policy", year=2025,
          family="sanctions", circular="A-INST-2025-01")
    with TestClient(create_app(settings, engine=engine)) as c:
        yield c, engine


def _sse(response) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, payload) pairs."""
    events: list[tuple[str, dict]] = []
    name = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            events.append((name, json.loads(line[6:])))
            name = None
    return events


# --- the streaming contract --------------------------------------------------


def test_the_event_order_is_what_the_frontend_waits_for(client) -> None:
    """`StreamingState` drives a stepper and resolves citation pills. Sources
    must arrive before any answer text, or a `[1]` in the first delta renders
    as a pill pointing at nothing."""
    c, _ = client
    response = c.post("/chat", json={"question": "sanctions screening"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _sse(response)
    kinds = [name for name, _ in events]

    assert kinds.index("sources") < kinds.index("delta")
    assert kinds[-1] == "done"
    steps = [payload["step"] for name, payload in events if name == "step"]
    assert steps == ["searching", "reading", "composing"]


def test_a_source_carries_the_field_names_types_ts_declares(client) -> None:
    """Renamed fields here are silent breakage there — the component reads
    `effectiveDate`, not `year`."""
    c, _ = client
    events = _sse(c.post("/chat", json={"question": "sanctions screening"}))
    sources = next(payload for name, payload in events if name == "sources")["sources"]

    assert sources, "expected at least one source"
    for key in ("id", "index", "title", "section", "page", "relevance",
                "department", "effectiveDate", "version", "excerpt"):
        assert key in sources[0], key
    assert sources[0]["index"] == 1


def test_metadata_the_documents_do_not_carry_is_empty_not_invented(client) -> None:
    """`mock.ts` supplies a department of "Global Compliance", which reads like
    real metadata and was written to make the mock look plausible. The corpus
    has no such field. A system built to stop a model inventing details must
    not open by inventing them."""
    c, _ = client
    events = _sse(c.post("/chat", json={"question": "sanctions screening"}))
    source = next(payload for name, payload in events if name == "sources")["sources"][0]

    assert source["department"] == ""
    # ...while everything the documents *do* state is passed through.
    assert source["effectiveDate"] == "2025"
    assert source["version"] == "A-INST-2025-01"


def test_a_question_with_no_answer_streams_a_refusal(client) -> None:
    c, _ = client
    events = _sse(c.post("/chat", json={"question": "submarine hatch bolt torque"}))
    done = next(payload for name, payload in events if name == "done")

    assert done["refused"] is True
    text = "".join(p["text"] for n, p in events if n == "delta")
    assert "could not find" in text.lower()


def test_a_model_failure_ends_the_stream_with_an_error_not_a_done(settings) -> None:
    """A `done` after a failure would tell the frontend the answer finished."""
    class Failing(FakeLLM):
        def stream(self, messages, **kwargs):
            yield "Screening is "
            raise RuntimeError("connection reset")

    engine = StubEngine(settings, llm=Failing())
    _seed(engine, title="Sanctions Compliance Policy", year=2025, family="sanctions")
    with TestClient(create_app(settings, engine=engine)) as c:
        events = _sse(c.post("/chat", json={"question": "sanctions screening"}))

    kinds = [name for name, _ in events]
    assert kinds[-1] == "error"
    assert "done" not in kinds


def test_the_done_event_carries_the_citation_audit(client) -> None:
    """Invented and superseded citations are the two faults a reader cannot see
    for themselves, so they travel with the answer rather than only to a log."""
    c, _ = client
    events = _sse(c.post("/chat", json={"question": "sanctions screening"}))
    done = next(payload for name, payload in events if name == "done")

    for key in ("refused", "invented", "superseded", "unused"):
        assert key in done, key


def test_an_empty_question_is_rejected_before_any_model_runs(client) -> None:
    c, _ = client
    assert c.post("/chat", json={"question": ""}).status_code == 422


# --- the library -------------------------------------------------------------


def test_documents_lists_what_is_indexed(client) -> None:
    c, _ = client
    rows = c.get("/documents").json()

    assert len(rows) == 1
    assert rows[0]["title"] == "Sanctions Compliance Policy"
    assert rows[0]["circular"] == "A-INST-2025-01"
    assert rows[0]["hasOtherVintage"] is False


def test_two_editions_are_flagged_as_rival_vintages(settings) -> None:
    """Two rows sharing a title look like a duplicate unless the interface can
    say they are different editions."""
    engine = StubEngine(settings)
    _seed(engine, title="Sanctions Compliance Policy", year=2025, family="sanctions")
    _seed(engine, title="Sanctions Compliance Policy", year=2023, family="sanctions")

    with TestClient(create_app(settings, engine=engine)) as c:
        rows = c.get("/documents").json()

    assert len(rows) == 2
    assert all(row["hasOtherVintage"] for row in rows)


def test_deleting_a_document_leaves_nothing_retrievable(client) -> None:
    """The bar is not that it vanishes from a list — it is that no fragment of
    it can be retrieved afterwards."""
    c, engine = client
    doc_id = c.get("/documents").json()[0]["id"]

    body = c.delete(f"/documents/{doc_id}").json()
    assert body["deleted"] is True
    assert body["chunksRemoved"] == 1

    assert c.get("/documents").json() == []
    assert engine.vectors.count(doc_id) == 0
    assert engine.registry.search("sanctions") == []


def test_deleting_something_that_is_not_there_is_a_404(client) -> None:
    c, _ = client
    assert c.delete("/documents/no-such-document").status_code == 404


def test_health_reports_the_fingerprint_that_makes_answers_meaningful(client) -> None:
    """An index built by a different embedder still returns results, still
    scores them, and means nothing. This is the one piece of state that reveals
    it."""
    c, engine = client
    body = c.get("/health").json()

    assert body["ok"] is True
    assert body["documents"] == 1
    assert body["indexFingerprint"] == engine.embedder.fingerprint
    assert "llm" in body["providers"]
