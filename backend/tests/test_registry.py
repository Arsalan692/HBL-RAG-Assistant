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


def test_provider_states_reflect_what_this_machine_can_actually_run():
    """The whole point of the registry: an honest answer about *this* machine.

    `llm` and `ocr` are ready because both reach Ollama over HTTP and need
    nothing installed here.

    The embedder and reranker are deliberately not pinned to one state. Whether
    torch is present is a fact about the machine, and this project has two of
    them — asserting either answer would make the suite fail on the other. What
    must hold everywhere is that the state and the reported gaps agree.
    """
    settings = Settings()
    assert registry.status(settings, "llm").state == "ready"
    assert registry.status(settings, "ocr").state == "ready"

    for interface in ("embedder", "reranker"):
        status = registry.status(settings, interface)  # type: ignore[arg-type]
        assert status.state in {"ready", "missing-deps"}, interface
        assert (status.state == "ready") is (status.missing == ()), interface


def test_status_reports_missing_dependencies_without_importing_anything():
    """`missing-deps` has to be reachable without importing the implementation,
    which is the property that lets `health` run on a machine that can never
    load it.

    Checked against a module that cannot exist, so the assertion is about the
    mechanism rather than about which packages happen to be installed today.
    """
    spec = registry.ProviderSpec(
        interface="embedder",
        name="fictional",
        summary="Exists only to be unsatisfiable.",
        target="app.providers.embedding.fictional:Nothing",
        requires=("a_module_that_will_never_be_installed",),
    )
    assert registry.missing_requirements(spec) == ("a_module_that_will_never_be_installed",)
    assert "app.providers.embedding.fictional" not in sys.modules
    assert "app.providers.embedding.bge_m3" not in sys.modules


def test_declared_providers_fail_to_load_with_their_phase_named(monkeypatch: pytest.MonkeyPatch):
    """A registered-but-unwritten provider must name its phase rather than
    raising ImportError for a module nobody has written.

    `mineru` is the example because it is genuinely still a declaration: it was
    a candidate in the OCR bench-off that `qwen2.5vl:7b` won, so it was never
    implemented. The reranker used to stand here and no longer can."""
    monkeypatch.setenv("HBL_OCR_PROVIDER", "mineru")
    with pytest.raises(ProviderNotImplemented, match="Phase 01"):
        registry.load_ocr(Settings())


def test_unknown_provider_name_lists_the_registered_ones(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HBL_OCR_PROVIDER", "tesseract")
    status = registry.status(Settings(), "ocr")
    assert status.state == "unknown"
    assert "docling" in status.detail

    with pytest.raises(ProviderNotFound):
        registry.spec_for("ocr", "tesseract")


def test_missing_requirements_reports_absent_modules():
    spec = registry.spec_for("embedder", "bge-m3")
    # Whichever of torch / sentence_transformers is absent here — possibly
    # neither — the answer is always a subset of what the spec asked for.
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
