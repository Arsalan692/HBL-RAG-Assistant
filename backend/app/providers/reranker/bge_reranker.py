"""The cross-encoder that decides what actually reaches the model.

Fusion produces a ranked list without ever having compared a candidate to the
question as a pair — dense search compared two independent summaries of meaning,
keyword search counted terms. A cross-encoder reads the query and the passage
together in one forward pass, which is far more accurate and far too slow to run
over a whole corpus. That is exactly why it sits here: last, over a few dozen
survivors rather than nine hundred.

There is no Ollama route for this one. Ollama has no rerank endpoint, so unlike
the embedder there is no way to avoid torch on the machine that runs it.

**On the score scale.** `HBL_RETRIEVAL_MIN_REEANK_SCORE` is a refusal threshold —
below it, the answer says it does not know rather than guessing from whatever
ranked highest. That only means something if scores are probabilities, and this
model's head emits a single unbounded logit. sentence-transformers applies a
sigmoid for a one-label model, but that is a default that has moved between
versions, so the range is checked here rather than assumed.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Sequence

from app.config import RerankerSettings, RuntimeSettings
from app.errors import ProviderUnavailable
from app.logging_config import get_logger
from app.providers.base import Scored

log = get_logger(__name__)


class BgeRerankerV2M3:
    """The `Reranker` protocol, backed by a sentence-transformers CrossEncoder."""

    name = "bge-reranker-v2-m3"

    def __init__(
        self, settings: RerankerSettings, runtime: RuntimeSettings | None = None
    ) -> None:
        self._settings = settings
        self._runtime = runtime or RuntimeSettings()
        self.model = settings.model
        self._model: Any | None = None
        self._warned_range = False

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

        Explicit rather than automatic for the same reason as the embedder: all
        three models are resident at once on the 16 GB card, and a caller that
        only wants to check configuration should not pay 2.3 GB for it.
        """
        if self._model is not None:
            return

        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise ProviderUnavailable(
                "sentence-transformers is not installed, and there is no Ollama route "
                "for reranking. Install it on this machine: "
                "pip install torch sentence-transformers"
            ) from exc

        local = Path(self.model)
        if not local.is_absolute():
            from app.config import ROOT_DIR

            local = ROOT_DIR / self.model

        if not local.exists() and "/" in self.model:
            raise ProviderUnavailable(
                f"HBL_RERANKER_MODEL={self.model!r} looks like a Hugging Face repo id "
                f"and {local} does not exist. With HBL_HF_OFFLINE=true nothing will be "
                "fetched at load time, which is deliberate — a run that pauses to "
                "download is a run whose timings mean nothing.\n"
                "Download it once, deliberately:\n"
                f"    hf download {self.model} --local-dir <folder>\n"
                "then point HBL_RERANKER_MODEL at that folder."
            )

        started = time.perf_counter()
        device = self._resolve_device()
        try:
            self._model = CrossEncoder(
                str(local) if local.exists() else self.model,
                device=device,
                max_length=self._settings.max_length,
                local_files_only=self._runtime.hf_offline,
            )
        except Exception as exc:  # pragma: no cover - engine-specific
            raise ProviderUnavailable(f"could not load {self.model}: {exc}") from exc

        log.info(
            "reranker.loaded",
            extra={
                "model": self.model,
                "device": device,
                "seconds": round(time.perf_counter() - started, 1),
            },
        )

    def unload(self) -> None:
        self._model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    # --- Reranker protocol ---------------------------------------------------

    def rerank(
        self, query: str, passages: Sequence[str], *, top_k: int | None = None
    ) -> list[Scored]:
        """Score every passage against the query, best first.

        Returns positions rather than passages, so the caller keeps whatever
        metadata — chunk id, page, section — was attached to each candidate.
        """
        if not passages:
            return []

        self.load()
        started = time.perf_counter()
        raw = self._model.predict(  # type: ignore[union-attr]
            [(query, passage) for passage in passages],
            batch_size=self._settings.batch_size,
            show_progress_bar=False,
        )
        scores = _as_probabilities(
            [float(value) for value in raw], warn=not self._warned_range
        )
        if scores.applied_sigmoid:
            self._warned_range = True

        ranked = sorted(
            (Scored(index=i, score=s) for i, s in enumerate(scores.values)),
            key=lambda s: s.score,
            reverse=True,
        )
        log.debug(
            "reranker.scored",
            extra={
                "passages": len(passages),
                "seconds": round(time.perf_counter() - started, 2),
                "best": round(ranked[0].score, 3),
            },
        )
        return ranked[:top_k] if top_k else ranked

    # --- Health --------------------------------------------------------------

    def probe(self) -> tuple[bool, str]:
        """Check the weights load and that ordering is sane on a known pair."""
        try:
            self.load()
        except ProviderUnavailable as exc:
            return False, str(exc)

        ranked = self.rerank(
            "What is required for a high risk customer?",
            [
                "Bank holidays are notified separately each year.",
                "Enhanced due diligence must be applied to high risk customers.",
            ],
        )
        if ranked[0].index != 1:
            return False, "loaded, but ranked an irrelevant passage first"
        return True, (
            f"{self.model}, best score {ranked[0].score:.2f} vs {ranked[1].score:.2f}"
        )


class _Probabilities:
    __slots__ = ("values", "applied_sigmoid")

    def __init__(self, values: list[float], applied_sigmoid: bool) -> None:
        self.values = values
        self.applied_sigmoid = applied_sigmoid


def _as_probabilities(scores: list[float], *, warn: bool = True) -> _Probabilities:
    """Put scores on 0..1 so the refusal threshold means something.

    sentence-transformers applies a sigmoid for a single-label cross-encoder,
    which is what this model is — so normally these arrive already bounded and
    nothing happens here. If a version change ever stops doing that, the raw
    logits would sail past `min_rerank_score` and the system would answer
    confidently from passages it should have refused on. Cheaper to check.
    """
    if not scores:
        return _Probabilities([], False)
    if all(0.0 <= value <= 1.0 for value in scores):
        return _Probabilities(scores, False)

    if warn:
        log.warning(
            "reranker.raw_logits",
            extra={
                "detail": "scores were outside 0..1, applying sigmoid",
                "min": round(min(scores), 3),
                "max": round(max(scores), 3),
            },
        )
    return _Probabilities([1.0 / (1.0 + math.exp(-value)) for value in scores], True)
