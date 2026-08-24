"""Tests for the registry, the vector store and true deletion.

The plan's bar for this phase is one sentence: ingest three documents, delete
one, and confirm by query that not one fragment of it can be retrieved. That is
`test_deleting_a_document_leaves_no_retrievable_fragment`; everything else here
exists to make its failure legible when it fails.

Uses the hashing embedder throughout, which is exactly what it is for — none of
this depends on embedding quality, only on vectors of the right shape arriving
in the right places.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import EmbeddingSettings, Settings
from app.ingest.chunk import Chunk
from app.ingest.metadata import identify
from app.providers.embedding.hashing import HashingEmbedder
from app.store.index import delete_document, index_document, purge_unfinished
from app.store.registry import Registry, escape_fts
from app.store.vectors import VectorStore

DIMENSION = 64


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s.paths.parsed_dir = tmp_path / "parsed"
    s.paths.page_image_dir = tmp_path / "images"
    s.paths.documents_dir = tmp_path / "documents"
    s.paths.registry_db = tmp_path / "registry.sqlite"
    s.paths.qdrant_dir = tmp_path / "qdrant"
    for directory in (s.paths.parsed_dir, s.paths.page_image_dir, s.paths.documents_dir):
        directory.mkdir(parents=True, exist_ok=True)
    s.embedding = EmbeddingSettings(_env_file=None, dimension=DIMENSION)  # type: ignore[call-arg]
    return s


@pytest.fixture
def registry(settings: Settings) -> Registry:
    store = Registry(settings.paths.registry_db)  # type: ignore[arg-type]
    yield store
    store.close()


@pytest.fixture
def vectors(settings: Settings) -> VectorStore:
    store = VectorStore(settings.paths.qdrant_dir, "test_chunks", DIMENSION)  # type: ignore[arg-type]
    yield store
    store.close()


@pytest.fixture
def embedder(settings: Settings) -> HashingEmbedder:
    return HashingEmbedder(settings.embedding)


def _chunk(doc_id: str, n: int, text: str, *, title: str, year: int | None = 2023) -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}:{n:04d}",
        doc_id=doc_id,
        title=title,
        policy_family=doc_id.rsplit("-", 1)[0],
        year=year,
        section=f"{n}. Section {n}",
        section_number=str(n),
        pages=(n,),
        text=text,
        tokens=len(text) // 4,
    )


def _index(name: str, texts: list[str], *, registry, vectors, embedder, settings):
    identity = identify(name)
    chunks = [
        _chunk(identity.doc_id, n, text, title=identity.title, year=identity.year)
        for n, text in enumerate(texts, 1)
    ]
    return identity, index_document(
        identity,
        chunks,
        sha256=f"hash-of-{identity.doc_id}",
        pages=len(texts),
        registry=registry,
        vectors=vectors,
        embedder=embedder,
    )


# --- keyword search ----------------------------------------------------------


def test_an_exact_identifier_is_findable(registry: Registry, settings, vectors, embedder) -> None:
    """The reason FTS5 is here at all: dense search misses these reliably."""
    _index(
        "Sanctions Compliance Policy - 2023.pdf",
        ["Issued under A-INST-2025-01 for all branches.", "Unrelated text about donations."],
        registry=registry, vectors=vectors, embedder=embedder, settings=settings,
    )
    hits = registry.search("A-INST-2025-01")
    assert hits and "A-INST-2025-01" in hits[0].text


def test_a_question_with_punctuation_does_not_raise(registry: Registry, settings, vectors, embedder) -> None:
    """These are real user questions. An apostrophe is a syntax error to FTS5."""
    _index(
        "Sanctions Compliance Policy - 2023.pdf",
        ["A politically exposed person requires enhanced due diligence."],
        registry=registry, vectors=vectors, embedder=embedder, settings=settings,
    )
    assert registry.search("what is a PEP? (and the bank's duty)") is not None


def test_an_identifier_stays_one_token() -> None:
    assert escape_fts("A-INST-2025-01") == '"A-INST-2025-01"'
    assert escape_fts("") == ""


# --- indexing ----------------------------------------------------------------


def test_indexing_stores_chunks_vectors_and_a_ready_status(
    registry: Registry, vectors: VectorStore, embedder, settings
) -> None:
    identity, result = _index(
        "Donations Policy 2024.pdf",
        ["Charitable contributions require approval.", "Donations are capped annually."],
        registry=registry, vectors=vectors, embedder=embedder, settings=settings,
    )
    assert result.ok and result.chunks == 2 and result.vectors == 2
    assert registry.get(identity.doc_id).status == "ready"
    assert vectors.count(identity.doc_id) == 2


def test_re_indexing_replaces_rather_than_duplicates(
    registry: Registry, vectors: VectorStore, embedder, settings
) -> None:
    """A document that changed must not leave its old chunks behind, still
    retrievable and now stale."""
    name = "Donations Policy 2024.pdf"
    _index(name, ["Superseded wording about zakat."], registry=registry, vectors=vectors, embedder=embedder, settings=settings)
    identity, _ = _index(name, ["Current wording about endowments."], registry=registry, vectors=vectors, embedder=embedder, settings=settings)

    assert registry.count_chunks(identity.doc_id) == 1
    assert vectors.count(identity.doc_id) == 1
    # Terms are OR-ed for recall, so the check has to be on a word only the
    # superseded version had.
    assert not registry.search("zakat")
    assert registry.search("endowments")


def test_an_exact_duplicate_is_skipped(
    registry: Registry, vectors: VectorStore, embedder, settings
) -> None:
    """This corpus already contains one byte-identical pair. Indexing both
    would double that policy's weight in retrieval."""
    original = identify("Policy.pdf")
    copy = identify("Policy (1).pdf")
    chunks = [_chunk(original.doc_id, 1, "Some clause.", title=original.title)]

    index_document(original, chunks, sha256="same", pages=1, registry=registry, vectors=vectors, embedder=embedder)
    result = index_document(copy, chunks, sha256="same", pages=1, registry=registry, vectors=vectors, embedder=embedder)

    assert result.skipped_duplicate_of == original.doc_id
    assert registry.get(copy.doc_id) is None


def test_a_failure_leaves_the_document_marked_failed(
    registry: Registry, vectors: VectorStore, settings
) -> None:
    class _Broken:
        def embed_documents(self, texts):
            raise RuntimeError("CUDA out of memory")

        def embed_query(self, text):
            raise RuntimeError("CUDA out of memory")

    identity = identify("Donations Policy 2024.pdf")
    result = index_document(
        identity,
        [_chunk(identity.doc_id, 1, "A clause.", title=identity.title)],
        sha256="h", pages=1, registry=registry, vectors=vectors, embedder=_Broken(),
    )
    assert not result.ok
    row = registry.get(identity.doc_id)
    assert row.status == "failed" and "CUDA" in row.error


# --- vintage -----------------------------------------------------------------


def test_two_vintages_are_stored_as_rivals(
    registry: Registry, vectors: VectorStore, embedder, settings
) -> None:
    for name in ("Sanctions Compliance Policy - 2023.pdf",
                 "A-INST-2025-01- Encl. Sanctions Compliance Policy.pdf"):
        _index(name, ["Sanctions screening is mandatory."],
               registry=registry, vectors=vectors, embedder=embedder, settings=settings)

    family = identify("Sanctions Compliance Policy - 2023.pdf").policy_family
    members = registry.vintages(family)
    assert [m.year for m in members] == [2025, 2023]


# --- deletion: the requirement -----------------------------------------------


def test_deleting_a_document_leaves_no_retrievable_fragment(
    registry: Registry, vectors: VectorStore, embedder, settings: Settings
) -> None:
    """The phase's whole bar. Ingest three, delete one, prove it is gone from
    the vector store, the keyword index, the registry and the disk — while the
    other two are untouched."""
    kept_a, _ = _index("Sanctions Compliance Policy - 2023.pdf", ["Sanctions screening is mandatory."],
                       registry=registry, vectors=vectors, embedder=embedder, settings=settings)
    doomed, _ = _index("Donations Policy 2024.pdf",
                       ["Charitable donations require prior written approval.",
                        "Donation limits are reviewed annually."],
                       registry=registry, vectors=vectors, embedder=embedder, settings=settings)
    kept_b, _ = _index("Business Continuity Policy 2024.pdf", ["Continuity plans are tested yearly."],
                       registry=registry, vectors=vectors, embedder=embedder, settings=settings)

    # Derived files, which carry the same confidential content as the PDF.
    parsed = settings.paths.parsed_dir
    images = settings.paths.page_image_dir
    (parsed / "Donations-Policy-2024.md").write_text("body", encoding="utf-8")
    (parsed / "Donations-Policy-2024.pages.json").write_text("{}", encoding="utf-8")
    (images / "Donations-Policy-2024_p0001_200dpi.png").write_bytes(b"png")

    assert registry.search("charitable donations")
    assert vectors.count(doomed.doc_id) == 2

    result = delete_document(doomed.doc_id, registry=registry, vectors=vectors, settings=settings)

    assert result.found
    assert result.vectors_removed == 2
    assert result.chunks_removed == 2
    assert len(result.files_removed) == 3

    # Nothing of it survives, by any route.
    assert registry.get(doomed.doc_id) is None
    assert registry.count_chunks(doomed.doc_id) == 0
    assert vectors.count(doomed.doc_id) == 0
    assert [h for h in registry.search("charitable donations") if h.doc_id == doomed.doc_id] == []
    assert [h for h in registry.search("donation limits reviewed") if h.doc_id == doomed.doc_id] == []
    assert not list(parsed.glob("Donations-Policy-2024*"))
    assert not list(images.glob("Donations-Policy-2024*"))

    # And the others are exactly as they were.
    assert registry.get(kept_a.doc_id) is not None
    assert registry.get(kept_b.doc_id) is not None
    assert vectors.count() == 2
    assert registry.search("sanctions screening")


def test_deleting_an_unknown_document_is_not_an_error(
    registry: Registry, vectors: VectorStore, settings: Settings
) -> None:
    result = delete_document("never-indexed", registry=registry, vectors=vectors, settings=settings)
    assert not result.found


def test_keep_files_leaves_the_derived_markdown(
    registry: Registry, vectors: VectorStore, embedder, settings: Settings
) -> None:
    identity, _ = _index("Donations Policy 2024.pdf", ["A clause."],
                         registry=registry, vectors=vectors, embedder=embedder, settings=settings)
    marker = settings.paths.parsed_dir / "Donations-Policy-2024.md"
    marker.write_text("body", encoding="utf-8")

    delete_document(identity.doc_id, registry=registry, vectors=vectors, settings=settings, remove_files=False)
    assert marker.exists()


def test_an_interrupted_deletion_is_finished_on_the_next_run(
    registry: Registry, vectors: VectorStore, embedder, settings: Settings
) -> None:
    """Two stores cannot share a transaction, so the intent is committed first.
    A crash after that leaves a row saying `deleting` rather than a document
    that is half gone and looks whole."""
    identity, _ = _index("Donations Policy 2024.pdf", ["A clause about donations."],
                         registry=registry, vectors=vectors, embedder=embedder, settings=settings)

    registry.mark_deleting(identity.doc_id)  # and then the machine dies
    assert [r.doc_id for r in registry.unfinished_deletions()] == [identity.doc_id]

    finished = purge_unfinished(registry, vectors, settings)

    assert len(finished) == 1
    assert registry.get(identity.doc_id) is None
    assert vectors.count(identity.doc_id) == 0
    assert registry.unfinished_deletions() == []


# --- the development embedder ------------------------------------------------


def test_the_hashing_embedder_is_deterministic_and_the_right_shape(settings: Settings) -> None:
    embedder = HashingEmbedder(settings.embedding)
    first = embedder.embed_query("enhanced due diligence")
    second = embedder.embed_query("enhanced due diligence")
    assert first == second
    assert len(first) == DIMENSION


def test_the_hashing_embedder_says_what_it_is(settings: Settings) -> None:
    """Protection against somebody forgetting they chose it, not against
    choosing it."""
    ok, detail = HashingEmbedder(settings.embedding).probe()
    assert ok
    assert "DEVELOPMENT ONLY" in detail


# --- the Ollama embedder route ----------------------------------------------


def test_a_local_model_path_becomes_an_ollama_tag(settings: Settings) -> None:
    """`.env` may hold `storage/models/bge-m3` for the sentence-transformers
    route. Ollama wants a tag, and would look for a model literally named
    `storage/models/bge-m3`."""
    from app.config import EmbeddingSettings
    from app.providers.embedding.ollama import OllamaEmbedder

    for configured, expected in [
        ("bge-m3", "bge-m3"),
        ("bge-m3:latest", "bge-m3:latest"),
        ("storage/models/bge-m3", "bge-m3"),
        (r"storage\models\bge-m3", "bge-m3"),
    ]:
        embedder = OllamaEmbedder(EmbeddingSettings(_env_file=None, model=configured))
        assert embedder.model == expected


def test_vectors_are_normalised_whatever_ollama_returns() -> None:
    """The vector store uses cosine distance, which only equals a dot product on
    unit vectors. sentence-transformers has a Normalize module; Ollama promises
    nothing, so it is done here unconditionally."""
    from app.providers.embedding.ollama import _unit

    assert _unit([3.0, 4.0]) == [0.6, 0.8]
    already = _unit([0.6, 0.8])
    assert all(abs(a - b) < 1e-9 for a, b in zip(already, [0.6, 0.8]))
    assert _unit([0.0, 0.0]) == [0.0, 0.0]  # must not divide by zero


def test_the_embedding_endpoint_must_be_local(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import EmbeddingSettings
    from app.errors import ConfigError

    monkeypatch.setenv("HBL_EMBEDDING_BASE_URL", "https://api.openai.com")
    with pytest.raises((ConfigError, Exception)) as excinfo:
        EmbeddingSettings()
    assert "not this machine" in str(excinfo.value) or isinstance(
        getattr(excinfo.value, "__cause__", None), ConfigError
    )
