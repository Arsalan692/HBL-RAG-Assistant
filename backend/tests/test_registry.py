"""The provider registry.

The load-bearing property tested here is that reporting status never imports an
implementation. If it did, `health` would stop working on the laptop the moment
a provider grew a torch import — which is exactly the failure this design
exists to prevent.
"""

from __future__ import annotations

import sys

import pytest

from app.config import Settings
from app.errors import ProviderNotFound, ProviderNotImplemented
from app.providers import registry
from app.providers.base import INTERFACES


def test_every_interface_resolves_to_a_status():
    statuses = registry.status_all(Settings())
    assert [s.interface for s in statuses] == list(INTERFACES)


def test_status_does_not_import_the_implementation(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, "app.providers.llm.ollama", raising=False)
    registry.status_all(Settings())
    assert "app.providers.llm.ollama" not in sys.modules


def test_llm_is_the_one_interface_ready_in_phase_00():
    settings = Settings()
    assert registry.status(settings, "llm").state == "ready"
    assert registry.status(settings, "embedder").state == "declared"
    assert registry.status(settings, "reranker").state == "declared"
    assert registry.status(settings, "ocr").state == "unchosen"


def test_declared_providers_fail_to_load_with_their_phase_named(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HBL_EMBEDDING_PROVIDER", "bge-m3")
    with pytest.raises(ProviderNotImplemented, match="Phase 03"):
        registry.load_embedder(Settings())


def test_unknown_provider_name_lists_the_registered_ones(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HBL_OCR_PROVIDER", "tesseract")
    status = registry.status(Settings(), "ocr")
    assert status.state == "unknown"
    assert "docling" in status.detail

    with pytest.raises(ProviderNotFound):
        registry.spec_for("ocr", "tesseract")


def test_missing_requirements_reports_absent_modules():
    spec = registry.spec_for("embedder", "bge-m3")
    # torch is not installed on the development laptop, and should not be.
    assert set(registry.missing_requirements(spec)) <= set(spec.requires)
    assert registry.missing_requirements(registry.spec_for("llm", "ollama")) == ()


def test_ocr_candidates_cover_the_phase_01_bench_off():
    names = {spec.name for spec in registry.specs("ocr")}
    assert {"docling", "mineru", "surya", "vlm"} <= names
    # PaddleOCR does not support Python 3.13; registering it would imply it were an option.
    assert "paddleocr" not in names


def test_ollama_provider_loads_without_a_server():
    """Constructing the provider must not touch the network — only calling it does."""
    llm = registry.load_llm(Settings())
    assert llm.name == "ollama"
    assert llm.model == Settings().llm.model
