"""The document registry, and the keyword half of retrieval.

One SQLite file holds three things that must agree with each other: a row per
document, a row per chunk, and an FTS5 index over those chunks. They live in
the same database on purpose — deleting a document has to remove its registry
row, its chunks and its keyword entries or none of them, and that is a
transaction, not a sequence of hopeful calls.

FTS5 rather than an in-memory BM25: this corpus is built on exact identifiers —
`A-INST-2025-01`, CDD, EDD, STR, PEP, threshold figures, clause numbers — that
dense search reliably misses, and an index that cannot delete is the wrong
shape for a system whose whole point is that documents come and go.

The vector store is the one thing that cannot join this transaction, since it
is a separate process with its own storage. `mark_deleting` exists for that:
the intent to delete is committed *before* the vectors go, so a crash halfway
leaves a row that says what was happening rather than a document that is half
gone and looks whole.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

from app.ingest.chunk import Chunk
from app.logging_config import get_logger

log = get_logger(__name__)

#: The lifecycle a document moves through. `deleting` is not a state anyone
#: asks for — it is the marker that survives a crash mid-delete.
Status = Literal["queued", "parsing", "ocr", "embedding", "ready", "failed", "deleting"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    source_name   TEXT NOT NULL,
    policy_family TEXT NOT NULL DEFAULT '',
    year          INTEGER,
    circular      TEXT NOT NULL DEFAULT '',
    sha256        TEXT NOT NULL UNIQUE,
    pages         INTEGER NOT NULL DEFAULT 0,
    chunk_count   INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'queued',
    error         TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS documents_family ON documents(policy_family, year DESC);
CREATE INDEX IF NOT EXISTS documents_status ON documents(status);

CREATE TABLE IF NOT EXISTS chunks (
    rowid_         INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id       TEXT NOT NULL UNIQUE,
    doc_id         TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    section        TEXT NOT NULL DEFAULT '',
    section_number TEXT NOT NULL DEFAULT '',
    page           INTEGER NOT NULL DEFAULT 0,
    pages          TEXT NOT NULL DEFAULT '[]',
    kind           TEXT NOT NULL DEFAULT 'prose',
    tokens         INTEGER NOT NULL DEFAULT 0,
    text           TEXT NOT NULL,
    -- Identifiers that belong to the document but appear nowhere in its body.
    -- `A-INST-2025-01` is the circular number on the covering instruction for
    -- both 2025 policies, and it is written only on the front page, which
    -- becomes the title — never in a clause. Someone asking "what does
    -- A-INST-2025-01 say" was therefore unfindable by the half of retrieval
    -- that exists precisely to find identifiers.
    identifiers    TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);

-- Which embedder built the vectors next door in Qdrant. One row, enforced by
-- the CHECK, because there is one collection and it has one vector space.
--
-- Without this, an index is indistinguishable from an index built by a
-- different model: the development `hashing` stand-in emits 1024 floats and so
-- does bge-m3, so Qdrant accepts writes from either into the same collection
-- and every score afterwards is nonsense that looks like a score.
CREATE TABLE IF NOT EXISTS index_meta (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    fingerprint TEXT NOT NULL,
    updated_at  REAL NOT NULL
);

"""

#: Kept separate from SCHEMA so a migration can drop and rebuild it. An
#: external-content FTS5 table's columns must match what its triggers write, so
#: adding a column means recreating the table, not altering it.
SCHEMA_FTS = """
-- External-content FTS5: the text lives once, in `chunks`. Without this the
-- corpus would be stored twice and the copies could drift.
--
-- `identifiers` is deliberately its own column rather than being glued onto
-- the text: bm25() can then be told to weight it separately, and the document's
-- circular number repeated across all 107 of its chunks does not dilute the
-- statistics of the prose.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    section,
    identifiers,
    content='chunks',
    content_rowid='rowid_',
    tokenize='porter unicode61'
);

-- Triggers rather than application code, so the index cannot be left stale by
-- a code path that forgot. Deleting a document cascades to chunks, which fires
-- these, which removes the keyword entries — all inside one transaction.
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, section, identifiers)
    VALUES (new.rowid_, new.text, new.section, new.identifiers);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, section, identifiers)
    VALUES ('delete', old.rowid_, old.text, old.section, old.identifiers);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, section, identifiers)
    VALUES ('delete', old.rowid_, old.text, old.section, old.identifiers);
    INSERT INTO chunks_fts(rowid, text, section, identifiers)
    VALUES (new.rowid_, new.text, new.section, new.identifiers);
END;
"""


@dataclass(frozen=True, slots=True)
class DocumentRow:
    doc_id: str
    title: str
    source_name: str
    policy_family: str
    year: int | None
    circular: str
    sha256: str
    pages: int
    chunk_count: int
    status: str
    error: str
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class KeywordHit:
    chunk_id: str
    doc_id: str
    section: str
    page: int
    text: str
    #: FTS5's bm25(), negated so larger is better — it returns lower-is-better.
    score: float


class Registry:
    """SQLite-backed document registry and keyword index."""

    def __init__(self, path: Path, *, same_thread: bool = True) -> None:
        """`same_thread=False` for the API, which serves requests on a thread
        pool. SQLite's default refuses a connection used from another thread —
        a real protection, since concurrent use of one connection corrupts
        state. The API relaxes it only because it holds a lock that serialises
        every access; nothing else should pass False.
        """
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=same_thread)
        self._db.row_factory = sqlite3.Row
        # Cascade is off by default in SQLite, and this schema depends on it:
        # deleting a document has to take its chunks, which takes its keyword
        # entries via the triggers above.
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        self._migrate()
        self._db.executescript(SCHEMA_FTS)

    def _migrate(self) -> None:
        """Bring an older database up to the current shape.

        Only one migration so far: `chunks.identifiers`. It matters that this
        does not require re-embedding — the vectors are untouched by a keyword
        change, and rebuilding them costs about 45 minutes of CPU. Everything
        needed to backfill is already in the `documents` table.
        """
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(chunks)")}
        if "identifiers" in columns:
            return

        log.info("registry.migrating", extra={"change": "chunks.identifiers"})
        with self.transaction() as db:
            db.execute("ALTER TABLE chunks ADD COLUMN identifiers TEXT NOT NULL DEFAULT ''")
            db.execute(
                """
                UPDATE chunks SET identifiers = COALESCE(
                    (SELECT d.circular FROM documents d WHERE d.doc_id = chunks.doc_id), ''
                )
                """
            )
            # The FTS table's columns must match what the triggers write, and
            # an external-content table cannot be altered — so it is dropped and
            # rebuilt from `chunks`, which still holds every row.
            for trigger in ("chunks_ai", "chunks_ad", "chunks_au"):
                db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            db.execute("DROP TABLE IF EXISTS chunks_fts")

        self._db.executescript(SCHEMA_FTS)
        self._db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        log.info("registry.migrated", extra={"change": "chunks.identifiers"})

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Registry:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._db.execute("BEGIN")
        try:
            yield self._db
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        self._db.execute("COMMIT")

    # --- documents -----------------------------------------------------------

    def upsert_document(
        self,
        *,
        doc_id: str,
        title: str,
        source_name: str,
        sha256: str,
        policy_family: str = "",
        year: int | None = None,
        circular: str = "",
        pages: int = 0,
        status: Status = "queued",
    ) -> None:
        now = time.time()
        self._db.execute(
            """
            INSERT INTO documents (doc_id, title, source_name, policy_family, year,
                                   circular, sha256, pages, status, created_at, updated_at)
            VALUES (:doc_id, :title, :source_name, :policy_family, :year,
                    :circular, :sha256, :pages, :status, :now, :now)
            ON CONFLICT(doc_id) DO UPDATE SET
                title=excluded.title, source_name=excluded.source_name,
                policy_family=excluded.policy_family, year=excluded.year,
                circular=excluded.circular, sha256=excluded.sha256,
                pages=excluded.pages, status=excluded.status, updated_at=:now
            """,
            {
                "doc_id": doc_id, "title": title, "source_name": source_name,
                "policy_family": policy_family, "year": year, "circular": circular,
                "sha256": sha256, "pages": pages, "status": status, "now": now,
            },
        )

    def set_status(self, doc_id: str, status: Status, error: str = "") -> None:
        """Move a document along its lifecycle.

        A 60-page scan takes minutes to ingest, and the interface has to show
        something truthful while it does. These are the states it shows.
        """
        self._db.execute(
            "UPDATE documents SET status = ?, error = ?, updated_at = ? WHERE doc_id = ?",
            (status, error, time.time(), doc_id),
        )
        log.info("registry.status", extra={"doc_id": doc_id, "status": status})

    def get(self, doc_id: str) -> DocumentRow | None:
        row = self._db.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return _to_document(row) if row else None

    def find_by_hash(self, sha256: str) -> DocumentRow | None:
        """The exact-re-upload check. This corpus already contains one."""
        row = self._db.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
        return _to_document(row) if row else None

    def documents(self, status: str | None = None) -> list[DocumentRow]:
        sql = "SELECT * FROM documents"
        args: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status = ?"
            args = (status,)
        sql += " ORDER BY policy_family, year DESC, title"
        return [_to_document(r) for r in self._db.execute(sql, args)]

    def vintages(self, policy_family: str) -> list[DocumentRow]:
        """Every vintage of one policy, newest first."""
        return [
            _to_document(r)
            for r in self._db.execute(
                "SELECT * FROM documents WHERE policy_family = ? ORDER BY year DESC",
                (policy_family,),
            )
        ]

    # --- which model built the index -----------------------------------------

    def index_fingerprint(self) -> str:
        """The embedder that built the current vectors, or "" if never stamped.

        An empty string means one of two things and cannot tell them apart: a
        store nothing has been written to yet, or one written before this table
        existed. Both are handled the same way — by whoever is about to write,
        which is the only moment the answer is knowable.
        """
        row = self._db.execute("SELECT fingerprint FROM index_meta WHERE id = 1").fetchone()
        return str(row["fingerprint"]) if row else ""

    def set_index_fingerprint(self, fingerprint: str) -> None:
        self._db.execute(
            """
            INSERT INTO index_meta (id, fingerprint, updated_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET fingerprint = excluded.fingerprint,
                                          updated_at = excluded.updated_at
            """,
            (fingerprint, time.time()),
        )
        log.info("registry.fingerprint", extra={"fingerprint": fingerprint})

    def clear_index_fingerprint(self) -> None:
        self._db.execute("DELETE FROM index_meta")

    # --- chunks --------------------------------------------------------------

    def replace_chunks(
        self, doc_id: str, chunks: Sequence[Chunk], *, identifiers: str = ""
    ) -> int:
        """Set a document's chunks to exactly these, in one transaction.

        Replace rather than append: re-indexing a document that changed must
        not leave its previous chunks behind, retrievable and stale.

        `identifiers` is the document's circular number, copied onto every
        chunk. It appears only on the front page of the PDF, so without this it
        reaches the title and stops — leaving the corpus's most quotable
        identifier invisible to keyword search.
        """
        with self.transaction() as db:
            db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            db.executemany(
                """
                INSERT INTO chunks (chunk_id, doc_id, section, section_number,
                                    page, pages, kind, tokens, text, identifiers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c.chunk_id, doc_id, c.section, c.section_number,
                        c.pages[0] if c.pages else 0, json.dumps(list(c.pages)),
                        c.kind, c.tokens, c.text, identifiers,
                    )
                    for c in chunks
                ],
            )
            db.execute(
                "UPDATE documents SET chunk_count = ?, updated_at = ? WHERE doc_id = ?",
                (len(chunks), time.time(), doc_id),
            )
        return len(chunks)

    def chunk_ids(self, doc_id: str) -> list[str]:
        return [
            r["chunk_id"]
            for r in self._db.execute("SELECT chunk_id FROM chunks WHERE doc_id = ?", (doc_id,))
        ]

    def count_chunks(self, doc_id: str | None = None) -> int:
        if doc_id:
            sql, args = "SELECT COUNT(*) FROM chunks WHERE doc_id = ?", (doc_id,)
        else:
            sql, args = "SELECT COUNT(*) FROM chunks", ()
        return int(self._db.execute(sql, args).fetchone()[0])

    # --- keyword search ------------------------------------------------------

    def search(self, query: str, limit: int = 30) -> list[KeywordHit]:
        """BM25 over the chunk text.

        The query is passed through `escape_fts` because these are real user
        questions: an apostrophe or a stray quote is a syntax error to FTS5,
        and "what is a PEP?" should not raise.

        Column weights matter here. `identifiers` holds the document's circular
        number on *every* one of its chunks, so at equal weight a query naming
        that circular would match all 107 chunks of a policy identically and
        flood the candidate list with a flat tie. At 0.25 it still surfaces the
        document — the token appears nowhere else in the corpus — without
        outranking a chunk whose prose actually answers the question.
        """
        escaped = escape_fts(query)
        if not escaped:
            return []
        rows = self._db.execute(
            """
            SELECT c.chunk_id, c.doc_id, c.section, c.page, c.text,
                   bm25(chunks_fts, 1.0, 0.5, 0.25) AS score
            FROM chunks_fts
            JOIN chunks c ON c.rowid_ = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (escaped, limit),
        ).fetchall()
        return [
            KeywordHit(
                chunk_id=r["chunk_id"], doc_id=r["doc_id"], section=r["section"],
                page=r["page"], text=r["text"], score=-float(r["score"]),
            )
            for r in rows
        ]

    # --- deletion ------------------------------------------------------------

    def mark_deleting(self, doc_id: str) -> None:
        """Commit the intent before touching anything that cannot roll back.

        The vector store is a separate process. If the machine dies between
        dropping vectors and dropping rows, this status is what tells the next
        run that the document is half-removed rather than whole.
        """
        self.set_status(doc_id, "deleting")

    def delete_document(self, doc_id: str) -> bool:
        """Remove the document, its chunks and its keyword entries atomically."""
        with self.transaction() as db:
            cursor = db.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            removed = cursor.rowcount > 0
        if removed:
            log.info("registry.deleted", extra={"doc_id": doc_id})
        return removed

    def unfinished_deletions(self) -> list[DocumentRow]:
        """Documents a previous run started deleting and did not finish."""
        return self.documents(status="deleting")


def _to_document(row: sqlite3.Row) -> DocumentRow:
    return DocumentRow(
        doc_id=row["doc_id"], title=row["title"], source_name=row["source_name"],
        policy_family=row["policy_family"], year=row["year"], circular=row["circular"],
        sha256=row["sha256"], pages=row["pages"], chunk_count=row["chunk_count"],
        status=row["status"], error=row["error"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def escape_fts(query: str) -> str:
    """Turn a user's question into a safe FTS5 MATCH expression.

    Every term is double-quoted, which makes it a literal rather than syntax.
    That matters twice over here: it stops `what is a PEP?` from raising, and
    it keeps `A-INST-2025-01` as one token instead of a boolean expression over
    four numbers — and identifiers like that are exactly why keyword search is
    in this system at all.
    """
    terms: list[str] = []
    for raw in query.replace('"', " ").split():
        term = raw.strip(".,;:!?()[]{}<>")
        if term:
            terms.append('"' + term + '"')
    return " OR ".join(terms)
