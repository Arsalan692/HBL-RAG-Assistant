"""Running structure, identity and chunking over the parsed corpus.

Thin by design: the decisions live in `structure`, `metadata` and `chunk`. This
only walks the parsed markdown, applies them, and writes the result somewhere
Phase 03 can index from.

Chunks are written as JSONL, one object per line. A chunk dump is meant to be
read — by a person checking breadcrumbs, and by `grep` — and a single 30 MB
JSON array is neither.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from app.config import Settings
from app.errors import HblError
from app.ingest.chunk import Chunk, ChunkStats, chunk_document
from app.ingest.metadata import DocumentIdentity, identify
from app.ingest.structure import parse
from app.logging_config import get_logger

log = get_logger(__name__)

_SOURCE = re.compile(r"<!--\s*source:\s*([^|]+?)\s*\|")


@dataclass
class DocumentChunks:
    identity: DocumentIdentity
    chunks: list[Chunk]
    stats: ChunkStats
    furniture: list[str] = field(default_factory=list)
    contents_pages: list[int] = field(default_factory=list)


def source_name(markdown: str, fallback: str) -> str:
    """The original PDF name, recorded by extraction in the file's header.

    Taken from the file rather than reconstructed from its slug, because the
    slug is lossy — `Compliance Risk  Policy & Program.pdf` became
    `Compliance-Risk--Policy---Program` and cannot be turned back.
    """
    if match := _SOURCE.search(markdown):
        return match.group(1).strip()
    return fallback


def chunk_corpus(settings: Settings, paths: Iterable[Path] | None = None) -> list[DocumentChunks]:
    """Chunk every parsed document."""
    parsed_dir = settings.paths.parsed_dir
    assert parsed_dir is not None

    files = sorted(paths) if paths is not None else sorted(parsed_dir.glob("*.md"))
    if not files:
        raise HblError(
            f"no parsed markdown in {parsed_dir}. Run `hbl extract` first."
        )

    out: list[DocumentChunks] = []
    for path in files:
        markdown = path.read_text(encoding="utf-8")
        identity = identify(source_name(markdown, path.stem + ".pdf"))
        document = parse(markdown)
        chunks, stats = chunk_document(document.blocks, identity, settings.chunk)

        log.info(
            "chunk.document",
            extra={
                "document": identity.title,
                "year": identity.year,
                "chunks": len(chunks),
                "tables": stats.tables,
            },
        )
        out.append(
            DocumentChunks(
                identity=identity,
                chunks=chunks,
                stats=stats,
                furniture=document.furniture,
                contents_pages=sorted(document.contents_pages),
            )
        )
    return out


def write_chunks(documents: list[DocumentChunks], out_dir: Path) -> Path:
    """One JSONL file for the whole corpus, plus a per-document summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "chunks.jsonl"

    with jsonl.open("w", encoding="utf-8") as handle:
        for document in documents:
            for chunk in document.chunks:
                handle.write(json.dumps(chunk.to_payload(), ensure_ascii=False) + "\n")

    (out_dir / "chunks-summary.json").write_text(
        json.dumps(
            [
                {
                    "doc_id": d.identity.doc_id,
                    "title": d.identity.title,
                    "policy_family": d.identity.policy_family,
                    "year": d.identity.year,
                    "circular": d.identity.circular,
                    "chunks": len(d.chunks),
                    "tables": d.stats.tables,
                    "oversized": d.stats.oversized,
                    "merged_fragments": d.stats.merged_fragments,
                    "sections": len(d.stats.sections),
                    "contents_pages": d.contents_pages,
                    "furniture_dropped": d.furniture,
                }
                for d in documents
            ],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return jsonl
