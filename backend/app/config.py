"""Configuration, resolved once from the environment.

Everything the backend needs to know about the machine it is running on lives
here and nowhere else: model names, device, paths, retrieval knobs, API bind
address. No other module reads ``os.environ``.

Two machines run this code — a CPU-only development laptop and the office GPU
workstation — so **every path is relative to the repository root and every
model is named in ``.env``**. Moving between them is a ``git pull`` and an
install, never an edit to a source file.

Settings are split into one class per concern, each reading its own ``HBL_*``
prefix. That keeps ``.env`` flat and readable (``HBL_LLM_MODEL=qwen3:14b``)
instead of forcing the nested-delimiter syntax pydantic-settings would
otherwise need.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.errors import ConfigError

# config.py -> app/ -> backend/ -> repository root
BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

# A repository-root .env holds anything shared with the frontend or tooling; a
# backend/.env overrides it for machine-specific values. Later files win.
ENV_FILES = (ROOT_DIR / ".env", BACKEND_DIR / ".env")

Device = Literal["auto", "cuda", "cpu"]
LogFormat = Literal["console", "json"]


def _config(prefix: str) -> SettingsConfigDict:
    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Several fields are literally called `model`, which collides with
        # pydantic's reserved `model_` namespace unless we clear it.
        protected_namespaces=(),
    )


def _under_root(path: Path) -> Path:
    """Anchor a relative path to the repository root, so cwd never matters."""
    return path if path.is_absolute() else (ROOT_DIR / path).resolve()


def _is_local_host(host: str) -> bool:
    """True if `host` is this machine or something on the local network.

    Enforces the project's hardest constraint at the one place a URL enters the
    system. The documents are confidential bank policy; a model endpoint must
    never be reachable over the public internet, however it got into `.env`.
    """
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback or ipaddress.ip_address(host).is_private
    except ValueError:
        pass
    lowered = host.lower()
    # A bare hostname ("workstation") or an mDNS name is a LAN machine. Anything
    # with a dotted public-looking domain is not.
    return lowered == "localhost" or lowered.endswith(".local") or "." not in lowered


def _require_local_url(url: str, field: str) -> str:
    host = urlparse(url).hostname or ""
    if not _is_local_host(host):
        raise ConfigError(
            f"{field}={url!r} points at {host!r}, which is not this machine or the "
            "local network. This corpus may not touch a remote endpoint."
        )
    return url


class RuntimeSettings(BaseSettings):
    """Process-level knobs: where we are, how loud, and which device."""

    model_config = _config("HBL_")

    app_env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"
    log_format: LogFormat = "console"

    #: `auto` resolves to cuda when torch reports a GPU. Deliberately not
    #: resolved here — importing torch to read config would make every CLI
    #: command slow on the laptop and impossible before the GPU install.
    device: Device = "auto"
    torch_dtype: str = "float16"

    #: Keeps huggingface/transformers from reaching for the network at load
    #: time. Weights are fetched deliberately, once, never as a side effect.
    hf_offline: bool = True

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class PathSettings(BaseSettings):
    """Where documents, derived artefacts and indexes live on disk.

    Only `data_dir` and `storage_dir` normally need setting. The rest derive
    from them, and any of them can still be overridden individually — useful on
    the workstation, where the corpus may sit on a different drive.

    Nothing under these paths is ever committed: parsed markdown, page images
    and the vector index all carry the same content as the source PDFs.
    """

    model_config = _config("HBL_")

    data_dir: Path = Path("data")
    storage_dir: Path = Path("storage")

    documents_dir: Path | None = None
    parsed_dir: Path | None = None
    page_image_dir: Path | None = None
    registry_db: Path | None = None
    qdrant_dir: Path | None = None
    model_cache_dir: Path | None = None
    log_dir: Path | None = None

    @model_validator(mode="after")
    def _derive(self) -> PathSettings:
        self.data_dir = _under_root(self.data_dir)
        self.storage_dir = _under_root(self.storage_dir)

        self.documents_dir = _under_root(self.documents_dir or self.data_dir / "documents")
        self.parsed_dir = _under_root(self.parsed_dir or self.data_dir / "parsed")
        self.page_image_dir = _under_root(self.page_image_dir or self.data_dir / "page_images")
        self.registry_db = _under_root(self.registry_db or self.storage_dir / "registry.sqlite")
        self.qdrant_dir = _under_root(self.qdrant_dir or self.storage_dir / "qdrant")
        self.model_cache_dir = _under_root(self.model_cache_dir or self.storage_dir / "models")
        self.log_dir = _under_root(self.log_dir or self.storage_dir / "logs")
        return self

    def directories(self) -> dict[str, Path]:
        """The directories this backend expects to exist, by label."""
        return {
            "data": self.data_dir,
            "documents": self.documents_dir,  # type: ignore[dict-item]
            "parsed": self.parsed_dir,  # type: ignore[dict-item]
            "page images": self.page_image_dir,  # type: ignore[dict-item]
            "storage": self.storage_dir,
            "qdrant": self.qdrant_dir,  # type: ignore[dict-item]
            "model cache": self.model_cache_dir,  # type: ignore[dict-item]
            "logs": self.log_dir,  # type: ignore[dict-item]
        }

    def create(self) -> list[Path]:
        """Create any missing directory. Returns the ones actually created."""
        created = []
        for path in self.directories().values():
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                created.append(path)
        return created


class LLMSettings(BaseSettings):
    """The generation model, served locally by Ollama."""

    model_config = _config("HBL_LLM_")

    provider: str = "ollama"
    model: str = "qwen3:14b"
    base_url: str = "http://127.0.0.1:11434"

    temperature: float = 0.1
    top_p: float = 0.9
    max_output_tokens: int = 1024
    context_tokens: int = 8192
    timeout_s: float = 180.0

    #: How long Ollama holds the weights in VRAM after a request. The three
    #: models together need ~15.6 GB of 16 GB, so eviction churn is expensive;
    #: keeping the LLM resident is cheaper than reloading it per question.
    keep_alive: str = "30m"

    #: Qwen3 is a reasoning model and emits a <think> block before its answer by
    #: default — hundreds of tokens the reader never sees, all of them ahead of
    #: the first visible word. Off, because time-to-first-token is what makes a
    #: chatbot feel fast, and this question type is grounded summarising rather
    #: than reasoning from scratch. Ollama ignores the field on models that have
    #: no thinking mode, so it is safe to always send.
    think: bool = False

    @field_validator("base_url")
    @classmethod
    def _local_only(cls, value: str) -> str:
        return _require_local_url(value, "HBL_LLM_BASE_URL")


class EmbeddingSettings(BaseSettings):
    """The dense retrieval model. Runs in-process on the GPU."""

    model_config = _config("HBL_EMBEDDING_")

    provider: str = "bge-m3"
    model: str = "BAAI/bge-m3"
    #: Must match the Qdrant collection; changing it means a full re-index.
    #: bge-m3 reports hidden_size 1024, so this is the model's number, not a
    #: choice.
    dimension: int = 1024

    #: Tokens the embedder reads before truncating. bge-m3 accepts 8192, so
    #: this is a cost decision rather than a model limit — but it must clear the
    #: largest chunk or the tail of that chunk is never searchable and nothing
    #: reports it. Measured on this corpus the largest chunk is ~1,291 tokens,
    #: and tables are deliberately never split so a big one cannot be trimmed
    #: to fit. 2048 covers that with room for the estimator being optimistic.
    max_length: int = 2048
    batch_size: int = 8
    normalize: bool = True

    #: Only the `ollama` provider uses these. Duplicated from LLMSettings rather
    #: than reached across to it so every provider stays constructible from
    #: exactly one settings object — the property that keeps the registry
    #: uniform. Validated local, like every other endpoint here.
    base_url: str = "http://127.0.0.1:11434"
    timeout_s: float = 120.0
    keep_alive: str = "30m"

    @field_validator("base_url")
    @classmethod
    def _local_only(cls, value: str) -> str:
        return _require_local_url(value, "HBL_EMBEDDING_BASE_URL")


class RerankerSettings(BaseSettings):
    """The cross-encoder that reorders fused candidates before generation."""

    model_config = _config("HBL_RERANKER_")

    provider: str = "bge-reranker-v2-m3"
    model: str = "BAAI/bge-reranker-v2-m3"
    max_length: int = 1024
    batch_size: int = 8


class OcrSettings(BaseSettings):
    """Page recognition. The engine is chosen by the Phase 01 bench-off."""

    model_config = _config("HBL_OCR_")

    #: Chosen 2026-08-21 by running the candidates over five real pages.
    #: `qwen2.5vl:7b` was the only one that read a dense ruled table without
    #: corrupting it: qwen2.5vl:3b silently deleted an Exclusions cell and
    #: shifted another column, and glm-ocr fell into a repetition loop on a
    #: sparse title page, emitting the same four lines 115 times. 7B also
    #: recovered the Urdu in the letterhead, which neither of the others did.
    #: ~14s per page on the RTX 4060 Ti.
    provider: str = "vlm"
    #: Meaning depends on the engine: an Ollama tag for `vlm`, a checkpoint name
    #: for the others, empty where the engine has only one model.
    model: str = "qwen2.5vl:7b"
    #: Comma separated. Kept as a string because pydantic-settings expects JSON
    #: for a `list[str]` read from the environment, which is a poor thing to ask
    #: of a .env file.
    languages: str = "en"
    dpi: int = 300

    #: Only the `vlm` engine uses this, and it points at the same Ollama server
    #: the generation model runs on. Duplicated rather than reached across to
    #: `LLMSettings` so every provider stays constructible from exactly one
    #: settings object — the property that keeps the registry uniform.
    base_url: str = "http://127.0.0.1:11434"

    @property
    def language_list(self) -> list[str]:
        return [part.strip() for part in self.languages.split(",") if part.strip()]

    @field_validator("base_url")
    @classmethod
    def _local_only(cls, value: str) -> str:
        return _require_local_url(value, "HBL_OCR_BASE_URL")


class IngestSettings(BaseSettings):
    """Thresholds for the per-page router.

    Routing is per *page*, never per file: this corpus has scans bound into
    digital documents and digital cover sheets on scanned ones, so a file-level
    decision is wrong for a large minority of pages either way.

    The defaults were set by running `hbl classify` over the real corpus and
    reading the histogram, not by guessing. Re-tune them the same way if the
    corpus changes; `--explain` prints the numbers behind any single verdict.
    """

    model_config = _config("HBL_INGEST_")

    #: Characters per square inch below which a page's text layer is too thin to
    #: be the whole story. Measured across this corpus the distribution is
    #: sharply bimodal — 25th percentile 1.2, median 24.5, 75th 33.0 — so
    #: anything in the teens is in the empty gap between the two modes.
    min_char_density: float = 12.0

    #: Fraction of the page covered by content-bearing raster images above which
    #: the page carries picture-borne content the text layer cannot contain.
    raster_threshold: float = 0.20

    #: Garble score above which the text layer is disbelieved even when there is
    #: plenty of it — the subset-font-without-ToUnicode case, where extraction
    #: yields a full page of confident nonsense.
    max_garble: float = 0.45

    #: Below this character density *and* with no meaningful raster, a page is
    #: blank: a section divider or the back of a duplex scan. Skipped entirely.
    empty_char_density: float = 3.0

    #: Trust a scan's pre-existing OCR text layer instead of re-reading the
    #: page. Off, and it should stay off: 219 of this corpus's pages are scans
    #: and many arrive with a prior text layer of unknown provenance — one was
    #: found rendering the HBL logo as "MBL HA.aH3GANK" alongside raw control
    #: characters. Re-reading costs GPU time once; trusting bad text is
    #: unrecoverable, because nothing downstream can tell it is wrong.
    trust_prior_ocr: bool = False

    #: Rasterisation resolution for anything routed to OCR. 300 is the usual
    #: floor for small print; the bench-off may raise it for poor scans.
    render_dpi: int = 300


class ChunkSettings(BaseSettings):
    """How extracted markdown is split for embedding.

    Splits follow section boundaries rather than a character count, because
    these documents are hierarchies (`4.`, `4.1`, `4.1.2`) and a clause cut in
    half is a clause that retrieves and then fails to answer.
    """

    model_config = _config("HBL_CHUNK_")

    #: Target size. bge-m3 accepts 8192 tokens, so this is not a model limit —
    #: it is a retrieval decision. Bigger chunks bury the sentence that matched
    #: among paragraphs that did not, and cost prefill on every answer.
    target_tokens: int = 700
    #: Carried from the end of the previous chunk so a clause split across two
    #: chunks is answerable from either. Taken at a sentence boundary.
    overlap_tokens: int = 120
    #: Below this, a chunk is merged into its neighbour instead of standing
    #: alone. A 30-token fragment matches on a stray word and answers nothing.
    min_tokens: int = 60
    #: A table larger than this is still never split — it becomes one oversized
    #: chunk. Half a table of risk classifications is worse than none, because
    #: it still reads as complete.
    max_table_tokens: int = 2000

    #: Prepend the section breadcrumb to each chunk's text. Costs a few tokens
    #: and makes every chunk self-describing, so one retrieved in isolation
    #: still says which policy and clause it came from.
    prefix_breadcrumb: bool = True


class RetrievalSettings(BaseSettings):
    """The hybrid retrieval pipeline's shape.

    Dense and keyword each contribute a wide candidate list, RRF fuses them,
    and the cross-encoder cuts to what actually reaches the model. The corpus
    is full of exact identifiers (A-INST-2025-01, CDD, EDD, STR, PEP, numeric
    thresholds) that dense search alone misses, which is why keyword search is
    not optional here.
    """

    model_config = _config("HBL_RETRIEVAL_")

    dense_top_k: int = 30
    keyword_top_k: int = 30
    rrf_k: int = 60

    #: How many fused candidates actually reach the cross-encoder. Dense and
    #: keyword can hand over as many as 60 between them, and scoring 60 long
    #: passages is the second-largest cost in a query after prompt prefill.
    #: Fusion already ranks them, so the tail rarely survives reranking anyway.
    rerank_candidates: int = 30
    rerank_top_k: int = 8
    #: Below this reranker score the answer refuses rather than guesses.
    min_rerank_score: float = 0.15

    qdrant_collection: str = "hbl_chunks"

    #: Prefer the newest vintage when two policies share a family, and say so
    #: when the older one genuinely disagrees rather than silently dropping it.
    prefer_newest_vintage: bool = True


class ApiSettings(BaseSettings):
    """FastAPI bind address and the origins allowed to call it."""

    model_config = _config("HBL_API_")

    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def origin_list(self) -> list[str]:
        return [part.strip() for part in self.cors_origins.split(",") if part.strip()]


class Settings(BaseModel):
    """The whole resolved configuration.

    A plain model rather than a `BaseSettings`: each section reads the
    environment for itself when constructed, so there is nothing left for an
    outer settings class to do.
    """

    model_config = {"protected_namespaces": ()}

    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    reranker: RerankerSettings = Field(default_factory=RerankerSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    chunk: ChunkSettings = Field(default_factory=ChunkSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)

    @property
    def root_dir(self) -> Path:
        return ROOT_DIR


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide configuration. Cached; call `get_settings.cache_clear()` in tests."""
    return Settings()
