"""Dense embeddings from bge-m3, served by the Ollama that is already running.

The same model as `bge_m3.py`, reached a different way. Loading it through
sentence-transformers pulls in torch, transformers and the Hugging Face stack —
roughly 2.5 GB of wheels plus a 2.2 GB weights folder. Ollama is already
installed on the workstation, already serving the generation and OCR models,
and already holds `bge-m3`, so going through it costs **no download and no new
dependency**: this module is stdlib `urllib` and nothing else.

That is a smaller win than it was — the workstation turned out to have internet,
so the alternative is a `pip install` rather than a hand-carried transfer. It
still matters for a different reason: Phase 04's reranker needs torch anyway,
so this route does not remove the dependency, it defers it.

Two things are handled here rather than assumed:

**Normalisation.** The vector store uses cosine distance, which is only
equivalent to a dot product when vectors are unit length. sentence-transformers
applies a Normalize module; Ollama returns whatever the model produced. So the
vectors are normalised here unconditionally — doing it twice is a no-op, and
not doing it once is a silently wrong ranking.

**Dimension.** Checked on the first call against the configured value, because
the Qdrant collection is built to that number. A mismatch is not a degraded
result, it is a store that refuses every write, and the error should name the
cause.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import EmbeddingSettings
from app.errors import ProviderUnavailable
from app.logging_config import get_logger
from app.providers.base import model_identity

log = get_logger(__name__)


class OllamaEmbedder:
    """The `Embedder` protocol, backed by an Ollama embedding model."""

    name = "ollama"

    def __init__(self, settings: EmbeddingSettings) -> None:
        self._settings = settings
        # `.env` may carry a local folder path for the sentence-transformers
        # route. That is meaningless to Ollama, which wants a model tag, so a
        # path collapses to its last component: storage/models/bge-m3 -> bge-m3.
        self.model = model_identity(settings.model or "bge-m3")
        self._base = settings.base_url.rstrip("/")
        self._checked = False

    # --- HTTP ----------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self._base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data else "GET",
        )
        try:
            with urlopen(request, timeout=self._settings.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:400]
            # Not every Ollama build serves embeddings. Some are started without
            # the endpoint enabled and answer 501 with a message about a flag
            # that is not part of the `ollama serve` interface — which reads as
            # a bug in this code rather than a server that is simply not
            # configured for it. Say what it means and where else to go.
            if exc.code == 501 or "does not support embeddings" in body:
                raise ProviderUnavailable(
                    f"the Ollama server at {self._base} does not serve embeddings "
                    f"({body.strip()}).\n"
                    "Either start it with embeddings enabled, or switch to the "
                    "in-process route: set HBL_EMBEDDING_PROVIDER=bge-m3 with "
                    "HBL_EMBEDDING_MODEL pointing at the staged weights folder. "
                    "That route needs torch and sentence-transformers installed."
                ) from exc
            raise ProviderUnavailable(f"Ollama returned {exc.code} for {path}: {body}") from exc
        except URLError as exc:
            raise ProviderUnavailable(
                f"cannot reach Ollama at {self._base} ({exc.reason}). "
                "Is `ollama serve` running on this machine?"
            ) from exc

    # --- Loadable ------------------------------------------------------------

    def load(self) -> None:
        """Nothing to load in this process — Ollama holds the weights."""
        return None

    def unload(self) -> None:
        return None

    # --- Embedder protocol ---------------------------------------------------

    @property
    def dimension(self) -> int:
        return self._settings.dimension

    @property
    def fingerprint(self) -> str:
        """Deliberately identical to the in-process route's.

        Both serve the same bge-m3 weights, so an index built through Ollama is
        searchable through sentence-transformers and the reverse — which is the
        point of having two routes at all. If the two are ever found to disagree
        numerically, this is the line that has to change.
        """
        return f"{model_identity(self.model)}:{self.dimension}"

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        started = time.perf_counter()
        body = self._post(
            "/api/embed",
            {
                "model": self.model,
                "input": list(texts),
                # Ollama would otherwise refuse anything past the model's
                # window. Chunking already keeps inputs well inside it; this is
                # the backstop for an oversized table.
                "truncate": True,
                "options": {"num_ctx": self._settings.max_length},
                "keep_alive": self._settings.keep_alive,
            },
        )

        vectors = body.get("embeddings")
        if not vectors:
            raise ProviderUnavailable(
                f"{self.model} returned no embeddings. Is it an embedding model? "
                f"Check with: ollama show {self.model}"
            )

        self._check_dimension(len(vectors[0]))
        log.debug(
            "embedder.batch",
            extra={
                "model": self.model,
                "texts": len(texts),
                "seconds": round(time.perf_counter() - started, 2),
            },
        )
        return [_unit(v) for v in vectors]

    def _check_dimension(self, actual: int) -> None:
        if self._checked:
            return
        if actual != self.dimension:
            raise ProviderUnavailable(
                f"{self.model} produces {actual}-dimensional vectors but "
                f"HBL_EMBEDDING_DIMENSION is {self.dimension}. The Qdrant collection is "
                f"built to that number and will reject every write. Set "
                f"HBL_EMBEDDING_DIMENSION={actual} and re-index, or use a different model."
            )
        self._checked = True

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    # --- Health --------------------------------------------------------------

    def probe(self) -> tuple[bool, str]:
        try:
            body = self._post("/api/tags")
        except ProviderUnavailable as exc:
            return False, str(exc)

        available = [entry["name"] for entry in body.get("models", [])]
        if not any(tag == self.model or tag.split(":")[0] == self.model for tag in available):
            return False, (
                f"{self.model!r} is not pulled. Available: "
                + (", ".join(available) if available else "none")
                + f". Run: ollama pull {self.model}"
            )

        try:
            vector = self.embed_query("enhanced due diligence")
        except ProviderUnavailable as exc:
            return False, str(exc)

        return True, f"{self.model} via Ollama, {len(vector)} dimensions, normalised"


def _unit(vector: Sequence[float]) -> list[float]:
    """Scale to unit length.

    Applied to everything, because Ollama does not promise normalised output and
    the vector store's cosine distance assumes it. A vector that is already unit
    length is unchanged, so the only cost of doing this unconditionally is a
    multiplication nobody notices.
    """
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return [float(value) for value in vector]
    return [float(value) / norm for value in vector]
