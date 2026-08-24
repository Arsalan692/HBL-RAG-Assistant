"""Dense embeddings from BAAI/bge-m3, running locally on the GPU.

Chosen for three properties this corpus needs: it is multilingual (the
letterheads carry Urdu), it handles 8192-token inputs so an oversized table
chunk is not silently truncated, and it is strong on retrieval rather than on
sentence similarity, which are different tasks that get benchmarked together.

**The model name in `.env` is a local directory, not a repo id.** On the
air-gapped workstation `from_pretrained("BAAI/bge-m3")` does not fail — it
hangs, waiting on a network that is not there. `HBL_HF_OFFLINE=true` turns that
hang into an error message, which is the only reason it is set.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Sequence

from app.config import EmbeddingSettings, RuntimeSettings
from app.errors import ProviderUnavailable
from app.logging_config import get_logger

log = get_logger(__name__)

#: bge-m3 was trained with an instruction prefix on queries but not on
#: documents. Skipping it costs a few points of recall; applying it to both
#: sides costs more. Kept explicit so nobody has to remember which is which.
QUERY_PREFIX = ""


class BgeM3Embedder:
    """The `Embedder` protocol, backed by sentence-transformers."""

    name = "bge-m3"

    def __init__(self, settings: EmbeddingSettings, runtime: RuntimeSettings | None = None) -> None:
        self._settings = settings
        self._runtime = runtime or RuntimeSettings()
        self.model_name = settings.model
        self._model: Any | None = None

    # --- loading -------------------------------------------------------------

    def _resolve_device(self) -> str:
        if self._runtime.device != "auto":
            return self._runtime.device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def load(self) -> None:
        """Bring the weights into memory. Idempotent.

        Called explicitly rather than in `__init__` because the VRAM budget is
        tight — the generation model, this and the reranker together need about
        15.6 GB of 16 — and a caller that only wants to check configuration
        should not pay 2.3 GB for the privilege.
        """
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise ProviderUnavailable(
                "sentence-transformers is not installed. On the workstation: "
                "pip install --no-index --find-links=wheels sentence-transformers"
            ) from exc

        local = Path(self.model_name)
        if not local.is_absolute():
            from app.config import ROOT_DIR

            local = ROOT_DIR / self.model_name

        if not local.exists() and "/" in self.model_name:
            raise ProviderUnavailable(
                f"HBL_EMBEDDING_MODEL={self.model_name!r} looks like a Hugging Face repo id, "
                f"and {local} does not exist. The workstation has no internet, so this would "
                "hang rather than download. Stage the weights and point this at the folder — "
                "see docs/download-manifest.html."
            )

        started = time.perf_counter()
        try:
            self._model = SentenceTransformer(
                str(local) if local.exists() else self.model_name,
                device=self._resolve_device(),
                local_files_only=self._runtime.hf_offline,
            )
        except Exception as exc:  # pragma: no cover - engine-specific
            raise ProviderUnavailable(f"could not load {self.model_name}: {exc}") from exc

        self._model.max_seq_length = self._settings.max_length
        log.info(
            "embedder.loaded",
            extra={
                "model": self.model_name,
                "device": self._resolve_device(),
                "seconds": round(time.perf_counter() - started, 1),
            },
        )

    def unload(self) -> None:
        """Give the VRAM back. Used when the budget bites."""
        self._model = None
        try:
            import torch

            torch.cuda.empty_cache()
        except ImportError:
            pass

    # --- Embedder protocol ---------------------------------------------------

    @property
    def dimension(self) -> int:
        return self._settings.dimension

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        self.load()
        assert self._model is not None
        vectors = self._model.encode(
            list(texts),
            batch_size=self._settings.batch_size,
            normalize_embeddings=self._settings.normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [[float(value) for value in row] for row in vectors]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([QUERY_PREFIX + text])[0]

    # --- Health --------------------------------------------------------------

    def probe(self) -> tuple[bool, str]:
        try:
            vector = self.embed_query("enhanced due diligence")
        except ProviderUnavailable as exc:
            return False, str(exc)
        if len(vector) != self.dimension:
            return False, (
                f"{self.model_name} produced {len(vector)} dimensions but "
                f"HBL_EMBEDDING_DIMENSION says {self.dimension}. The Qdrant collection "
                "is built to that number; fix the config and re-index."
            )
        return True, f"{self.model_name} on {self._resolve_device()}, {len(vector)} dimensions"
