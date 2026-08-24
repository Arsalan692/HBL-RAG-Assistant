"""Configuration resolution.

These run on the laptop with no models installed — that is the point. If any
test here needs a GPU, something has leaked out of a provider module and into
config.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import ROOT_DIR, LLMSettings, OcrSettings, PathSettings, Settings, get_settings
from app.errors import ConfigError


def test_defaults_match_the_settled_decisions():
    settings = Settings()
    assert settings.llm.model == "qwen3:14b"
    assert settings.embedding.model == "BAAI/bge-m3"
    assert settings.reranker.model == "BAAI/bge-reranker-v2-m3"
    # 30 + 30 fused down to 8 is the retrieval shape the whole plan assumes.
    assert (settings.retrieval.dense_top_k, settings.retrieval.keyword_top_k) == (30, 30)
    assert settings.retrieval.rerank_top_k == 8


def test_env_overrides_every_section(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HBL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setenv("HBL_EMBEDDING_BATCH_SIZE", "4")
    monkeypatch.setenv("HBL_RETRIEVAL_RERANK_TOP_K", "5")
    monkeypatch.setenv("HBL_LOG_FORMAT", "json")

    settings = Settings()
    assert settings.llm.model == "qwen3:8b"
    assert settings.embedding.batch_size == 4
    assert settings.retrieval.rerank_top_k == 5
    assert settings.runtime.log_format == "json"


def test_relative_paths_anchor_to_the_repository_not_the_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    paths = PathSettings()
    assert paths.data_dir == (ROOT_DIR / "data").resolve()
    assert paths.documents_dir == (ROOT_DIR / "data" / "documents").resolve()


def test_absolute_path_override_is_left_alone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HBL_DATA_DIR", str(tmp_path / "corpus"))
    paths = PathSettings()
    assert paths.data_dir == tmp_path / "corpus"
    # Derived directories follow the override rather than the default root.
    assert paths.parsed_dir == (tmp_path / "corpus" / "parsed").resolve()


def test_storage_paths_derive_from_storage_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HBL_STORAGE_DIR", str(tmp_path / "s"))
    paths = PathSettings()
    assert paths.registry_db == (tmp_path / "s" / "registry.sqlite").resolve()
    assert paths.qdrant_dir == (tmp_path / "s" / "qdrant").resolve()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://192.168.1.40:11434",
        "http://10.0.0.7:11434",
        "http://workstation:11434",
        "http://gpu-box.local:11434",
    ],
)
def test_local_endpoints_are_accepted(url: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HBL_LLM_BASE_URL", url)
    assert LLMSettings().base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://ollama.example.com:11434",
        "https://8.8.8.8:11434",
    ],
)
def test_remote_endpoints_are_refused(url: str, monkeypatch: pytest.MonkeyPatch):
    """The corpus is confidential bank policy. A public endpoint is a config error, not a warning."""
    monkeypatch.setenv("HBL_LLM_BASE_URL", url)
    with pytest.raises(Exception) as excinfo:
        LLMSettings()
    assert isinstance(excinfo.value, ConfigError) or isinstance(
        excinfo.value.__cause__, ConfigError
    ) or "not this machine" in str(excinfo.value)


def test_ocr_defaults_to_the_engine_the_bench_off_chose():
    """Decided 2026-08-21 on five real pages, not on published benchmarks.

    qwen2.5vl:7b was the only candidate that read a dense ruled table without
    corrupting it. Changing this default means re-running `hbl bench`, not
    picking a different name.
    """
    assert OcrSettings().provider == "vlm"
    assert OcrSettings().model == "qwen2.5vl:7b"
    assert OcrSettings(languages="en, ur").language_list == ["en", "ur"]


def test_get_settings_is_cached():
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()


def test_the_embedder_reads_further_than_the_largest_chunk():
    """A chunk longer than `max_length` is silently truncated at embedding time
    and its tail never becomes searchable — with nothing reporting it.

    Chunking targets 700 tokens but tables are never split, so a single chunk
    can run well past that. The largest in this corpus is about 1,291 tokens.
    """
    from app.config import ChunkSettings, EmbeddingSettings

    embedding = EmbeddingSettings(_env_file=None)
    chunking = ChunkSettings(_env_file=None)

    assert embedding.max_length >= chunking.max_table_tokens
    assert embedding.max_length > chunking.target_tokens * 2
