"""Generation through a local Ollama server.

Written against `urllib` from the standard library rather than httpx or the
`ollama` package. Ollama's API is two JSON endpoints; a dependency to reach
them would buy nothing, and this module has to install cleanly on a laptop that
will never run a model.

Ollama streams NDJSON — one JSON object per line, each carrying a fragment of
the answer — which maps directly onto the SSE stream the frontend reads.
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import LLMSettings
from app.errors import ProviderUnavailable
from app.logging_config import get_logger
from app.providers.base import ChatMessage, Completion, Usage

log = get_logger(__name__)


class OllamaLLM:
    """The `LLM` protocol, backed by `ollama serve` on this machine or the LAN."""

    name = "ollama"

    def __init__(self, settings: LLMSettings) -> None:
        self._settings = settings
        self.model = settings.model
        self._base = settings.base_url.rstrip("/")

    # --- HTTP ----------------------------------------------------------------

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data else "GET",
        )
        try:
            return urlopen(request, timeout=self._settings.timeout_s)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:400]
            raise ProviderUnavailable(f"Ollama returned {exc.code} for {path}: {body}") from exc
        except URLError as exc:
            raise ProviderUnavailable(
                f"cannot reach Ollama at {self._base} ({exc.reason}). "
                "Is `ollama serve` running on this machine?"
            ) from exc

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        *,
        stream: bool,
        temperature: float | None,
        max_tokens: int | None,
        stop: Sequence[str] | None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self._settings.temperature if temperature is None else temperature,
            "top_p": self._settings.top_p,
            "num_predict": max_tokens or self._settings.max_output_tokens,
            "num_ctx": self._settings.context_tokens,
        }
        if stop:
            options["stop"] = list(stop)
        return {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            "options": options,
            "keep_alive": self._settings.keep_alive,
            # Suppresses Qwen3's <think> block. Unknown fields are ignored by
            # Ollama, so this is harmless against a model without one.
            "think": self._settings.think,
        }

    # --- LLM protocol --------------------------------------------------------

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
    ) -> Completion:
        payload = self._payload(
            messages, stream=False, temperature=temperature, max_tokens=max_tokens, stop=stop
        )
        with self._request("/api/chat", payload) as response:
            body = json.loads(response.read().decode("utf-8"))

        return Completion(
            text=body.get("message", {}).get("content", ""),
            model=body.get("model", self.model),
            usage=Usage(
                prompt_tokens=body.get("prompt_eval_count"),
                completion_tokens=body.get("eval_count"),
            ),
            finish_reason=body.get("done_reason"),
        )

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
    ) -> Iterator[str]:
        payload = self._payload(
            messages, stream=True, temperature=temperature, max_tokens=max_tokens, stop=stop
        )
        with self._request("/api/chat", payload) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line:
                    continue
                chunk = json.loads(line)
                if error := chunk.get("error"):
                    raise ProviderUnavailable(f"Ollama stream failed: {error}")
                if delta := chunk.get("message", {}).get("content"):
                    yield delta
                if chunk.get("done"):
                    break

    # --- Health --------------------------------------------------------------

    def installed_models(self) -> list[str]:
        with self._request("/api/tags") as response:
            body = json.loads(response.read().decode("utf-8"))
        return [entry["name"] for entry in body.get("models", [])]

    def probe(self) -> tuple[bool, str]:
        """Contact the server and check the configured model is actually pulled.

        Returns (ok, message) rather than raising, because `cli health --probe`
        wants to report every interface even when one of them is down.
        """
        try:
            available = self.installed_models()
        except ProviderUnavailable as exc:
            return False, str(exc)

        # Ollama tags carry an explicit version — "qwen3:14b" is listed as
        # "qwen3:14b", but a config naming "qwen3" should still match it.
        if any(tag == self.model or tag.split(":")[0] == self.model for tag in available):
            return True, f"{self.model} available ({len(available)} model(s) pulled)"
        return False, (
            f"{self.model!r} is not pulled. Available: "
            + (", ".join(available) if available else "none")
            + f". Run: ollama pull {self.model}"
        )
