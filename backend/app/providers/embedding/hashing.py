"""A deterministic embedder with no model behind it. Development only.

This exists so the parts of the system that are *not* the embedding model —
the registry, the vector store, indexing, deletion, the fusion arithmetic —
can be built and proven on a laptop that has no GPU and no staged weights. It
turns "I cannot test any of this until the transfer happens" into "I can test
all of it except retrieval quality".

**It is not an embedding model.** It hashes character n-grams into a fixed
number of buckets. Two texts sharing many n-grams land near each other, which
is enough to make a smoke test meaningful and nothing like enough to retrieve
a policy clause. Anything it ranks is ranked by spelling, not meaning.

It is registered so `hbl index --embedder hashing` works, and it announces
itself in the log every time it loads, because the failure mode to protect
against is not somebody choosing it — it is somebody forgetting they did.
"""

from __future__ import annotations

import hashlib
import math
from typing import Sequence

from app.config import EmbeddingSettings
from app.logging_config import get_logger

log = get_logger(__name__)

#: Character n-gram width. Three is short enough that "PEP" and "PEPs" share
#: buckets, which is the only kind of similarity this thing can represent.
_NGRAM = 3


class HashingEmbedder:
    """The `Embedder` protocol, with arithmetic instead of a model."""

    name = "hashing"

    def __init__(self, settings: EmbeddingSettings) -> None:
        self._settings = settings
        self._warned = False

    @property
    def dimension(self) -> int:
        return self._settings.dimension

    @property
    def fingerprint(self) -> str:
        """Its own name, never the configured one.

        `--embedder hashing` overrides the provider but leaves
        HBL_EMBEDDING_MODEL saying `BAAI/bge-m3`, so reporting the setting here
        would stamp an index of hashed n-grams as though a real model had built
        it — the exact confusion the fingerprint exists to prevent.
        """
        return f"hashing:{self.dimension}"

    def load(self) -> None:
        if not self._warned:
            log.warning(
                "embedder.not_a_model",
                extra={
                    "provider": self.name,
                    "detail": (
                        "hashing embedder in use — vectors carry spelling, not meaning. "
                        "Retrieval results are not meaningful. Set "
                        "HBL_EMBEDDING_PROVIDER=bge-m3 for anything real."
                    ),
                },
            )
            self._warned = True

    def unload(self) -> None:
        return None

    def _vector(self, text: str) -> list[float]:
        self.load()
        buckets = [0.0] * self.dimension
        cleaned = " ".join(text.lower().split())
        if not cleaned:
            return buckets

        for index in range(max(1, len(cleaned) - _NGRAM + 1)):
            gram = cleaned[index : index + _NGRAM]
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            position = int.from_bytes(digest[:4], "big") % self.dimension
            # Sign from a second slice of the digest, so unrelated n-grams can
            # cancel rather than only ever adding.
            sign = 1.0 if digest[4] & 1 else -1.0
            buckets[position] += sign

        if self._settings.normalize:
            norm = math.sqrt(sum(value * value for value in buckets))
            if norm:
                buckets = [value / norm for value in buckets]
        return buckets

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def probe(self) -> tuple[bool, str]:
        return True, (
            f"hashing embedder, {self.dimension} dimensions — DEVELOPMENT ONLY, "
            "vectors carry spelling rather than meaning"
        )
