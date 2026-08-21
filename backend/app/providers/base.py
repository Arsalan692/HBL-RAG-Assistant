"""The four provider contracts every later phase codes against.

`LLM`, `Embedder`, `Reranker`, `OCR`. There is no cloud fallback behind these
interfaces and there never will be — they exist because a fully local stack
changes models *more* often than a hosted one, not less. The OCR engine is
picked by bench-off in Phase 01; the generation model may be re-picked if the
VRAM budget bites. Both should be a line in `.env`, not a refactor.

These are `typing.Protocol`s, checked statically. Implementations do not
inherit from them, which keeps a provider module free of any import from this
package beyond its own settings class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal, Protocol, Sequence

Interface = Literal["llm", "embedder", "reranker", "ocr"]
INTERFACES: tuple[Interface, ...] = ("llm", "embedder", "reranker", "ocr")


# --- Lifecycle ---------------------------------------------------------------


class Loadable(Protocol):
    """Optional, for providers holding VRAM.

    All three models are resident at once — LLM ~9 GB plus ~2 GB of KV cache,
    the embedder ~2.3 GB, the reranker ~2.3 GB, against 16 GB total. That is
    tight enough that whoever owns a model needs to be able to put it down.
    """

    def load(self) -> None: ...

    def unload(self) -> None: ...


# --- Generation --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    model: str
    usage: Usage | None = None
    finish_reason: str | None = None


class LLM(Protocol):
    """A locally served chat model.

    `stream` is the primary method, not a convenience: the frontend renders
    tokens as they arrive over SSE, and answers that cite policy clauses are
    long enough that waiting for the whole thing feels broken.
    """

    name: str
    model: str

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
    ) -> Completion: ...

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
    ) -> Iterator[str]:
        """Yield text deltas in order. The concatenation equals `complete().text`."""
        ...


# --- Dense retrieval ---------------------------------------------------------


class Embedder(Protocol):
    """Turns text into vectors for the dense half of retrieval.

    Documents and queries get separate methods because several models want
    different treatment for each (instruction prefixes, pooling, truncation).
    bge-m3 happens not to, but coding against one method would make swapping to
    a model that does a breaking change.
    """

    name: str
    model: str
    dimension: int

    def embed_documents(
        self, texts: Sequence[str], *, batch_size: int | None = None
    ) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


# --- Reranking ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scored:
    """A passage's position in the input list, and what the reranker thought of it."""

    index: int
    score: float


class Reranker(Protocol):
    """Cross-encoder that reorders fused candidates.

    Returns positions rather than the passages themselves, so the caller keeps
    ownership of whatever metadata was attached to each candidate.
    """

    name: str
    model: str

    def rerank(
        self, query: str, passages: Sequence[str], *, top_k: int | None = None
    ) -> list[Scored]:
        """Descending by score, truncated to `top_k` if given."""
        ...


# --- Page recognition --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PageRef:
    """One page to recognise.

    Engines disagree about what they want handed to them: Docling and MinerU
    take the PDF and locate the page themselves, while Surya and the VLM
    candidates want a rasterised image. Rather than pick a side and force every
    other engine through a conversion, a request carries both — the source PDF
    with a page number, and the raster if one has already been rendered. An
    engine uses whichever it needs and ignores the rest.
    """

    pdf_path: Path
    #: 1-based, matching what a reader sees in a PDF viewer.
    page_number: int
    image_path: Path | None = None
    dpi: int = 300
    languages: tuple[str, ...] = ("en",)
    #: Region to recognise, in page points, for HYBRID pages where only part of
    #: the page is a raster. None means the whole page.
    region: tuple[float, float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Recognised page content as markdown, plus what it cost to get it.

    Markdown rather than plain text because the corpus is table-heavy and a
    table flattened to prose is worse than useless — it reads as fact while
    having lost which number belonged to which row. `duration_s` and
    `table_count` exist for the Phase 01 bench-off, which compares engines on
    real pages rather than published benchmarks.
    """

    markdown: str
    engine: str
    page_number: int
    confidence: float | None = None
    table_count: int = 0
    duration_s: float = 0.0
    warnings: tuple[str, ...] = field(default=())


class OCR(Protocol):
    """A local page-recognition engine."""

    name: str

    def recognise(self, page: PageRef) -> OcrResult: ...

    def recognise_batch(self, pages: Sequence[PageRef]) -> list[OcrResult]:
        """Same order as the input. Engines that batch on the GPU override this profitably."""
        ...


# --- Health ------------------------------------------------------------------

ProviderState = Literal["ready", "declared", "unchosen", "missing-deps", "unknown"]


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """What `cli health` reports for one interface, resolved without importing anything heavy."""

    interface: Interface
    name: str
    model: str
    state: ProviderState
    detail: str = ""
    target: str = ""
    missing: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True if this provider could be loaded and used right now."""
        return self.state == "ready"
