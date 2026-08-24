"""Which implementation backs each interface, and whether it can run here.

The registry holds *descriptions* of providers — an import target and the
distributions it needs — not the providers themselves. That distinction is the
point of this module: `python -m app.cli health` has to work on the CPU laptop,
where torch is not installed and never will be. Reporting status therefore uses
`importlib.util.find_spec`, which answers "is this importable?" without
importing it. Nothing heavy is loaded until something actually asks to embed.

A spec carrying a `phase` is a declaration rather than an implementation: the
name and its dependencies are settled, the code arrives in that phase. Asking
to load one fails with a sentence saying which phase, instead of an ImportError
naming a module that was never written.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.errors import ProviderNotFound, ProviderNotImplemented, ProviderUnavailable
from app.providers.base import INTERFACES, Interface, ProviderStatus

if TYPE_CHECKING:
    from app.config import Settings
    from app.providers.base import LLM, OCR, Embedder, Reranker


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    interface: Interface
    name: str
    summary: str
    #: "module.path:ClassName". Empty while `phase` is set.
    target: str = ""
    #: Top-level importable names this provider needs, for the availability check.
    requires: tuple[str, ...] = ()
    #: The phase that writes the implementation. None means it exists now.
    phase: str | None = None


_SPECS: tuple[ProviderSpec, ...] = (
    # --- Generation ----------------------------------------------------------
    ProviderSpec(
        interface="llm",
        name="ollama",
        summary="Local Ollama server over HTTP. Holds the 4-bit generation model.",
        target="app.providers.llm.ollama:OllamaLLM",
    ),
    # --- Dense retrieval -----------------------------------------------------
    ProviderSpec(
        interface="embedder",
        name="hashing",
        summary="DEVELOPMENT ONLY. Hashed character n-grams, no model. Vectors carry spelling, not meaning.",
        target="app.providers.embedding.hashing:HashingEmbedder",
        requires=(),
    ),
    ProviderSpec(
        interface="embedder",
        name="bge-m3",
        summary="BAAI/bge-m3 dense vectors, in-process on the GPU. 1024 dimensions.",
        target="app.providers.embedding.bge_m3:BgeM3Embedder",
        requires=("torch", "sentence_transformers"),
    ),
    # --- Reranking -----------------------------------------------------------
    ProviderSpec(
        interface="reranker",
        name="bge-reranker-v2-m3",
        summary="BAAI cross-encoder, scores query against each fused candidate.",
        requires=("torch", "sentence_transformers"),
        phase="04",
    ),
    # --- Page recognition ----------------------------------------------------
    # Four candidates, one winner, decided on real pages in Phase 01. They are
    # registered now so `cli providers` can tell you which are installed on the
    # workstation before the bench-off starts. PaddleOCR is absent on purpose:
    # it does not support Python 3.13, and 3.13 was the deliberate choice.
    #
    # `vlm` is the cheap one: qwen2.5vl:7b is already pulled on the workstation
    # and Ollama is already the generation transport, so benching it needs no
    # download and no new dependency. The other three each need a package and
    # their own weights, which on that machine means a permission request.
    ProviderSpec(
        interface="ocr",
        name="unset",
        summary="Nothing chosen. Kept so a config with no OCR engine fails clearly.",
        phase="01",
    ),
    ProviderSpec(
        interface="ocr",
        name="docling",
        summary="IBM Docling. Layout-aware, strong table structure, takes the PDF directly.",
        target="app.providers.ocr.docling:DoclingOCR",
        requires=("docling",),
    ),
    ProviderSpec(
        interface="ocr",
        name="mineru",
        summary="MinerU. Pipeline built for dense technical documents.",
        requires=("magic_pdf",),
        phase="01",
    ),
    ProviderSpec(
        interface="ocr",
        name="surya",
        summary="Surya. Fast detection and recognition over rasterised pages.",
        requires=("surya",),
        phase="01",
    ),
    ProviderSpec(
        interface="ocr",
        name="vlm",
        summary="CHOSEN. qwen2.5vl:7b via Ollama. Only candidate that read a ruled table without corrupting it.",
        target="app.providers.ocr.vlm:VlmOCR",
        requires=(),
    ),
)

_BY_KEY: dict[tuple[str, str], ProviderSpec] = {(s.interface, s.name): s for s in _SPECS}


def specs(interface: Interface | None = None) -> list[ProviderSpec]:
    return [s for s in _SPECS if interface is None or s.interface == interface]


def spec_for(interface: Interface, name: str) -> ProviderSpec:
    try:
        return _BY_KEY[(interface, name)]
    except KeyError:
        known = ", ".join(s.name for s in specs(interface)) or "none"
        raise ProviderNotFound(
            f"no {interface} provider named {name!r}. Registered: {known}."
        ) from None


def missing_requirements(spec: ProviderSpec) -> tuple[str, ...]:
    """Which of the spec's dependencies are not importable here. Does not import them."""
    missing = []
    for module in spec.requires:
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(module)
    return tuple(missing)


def _configured(settings: Settings, interface: Interface) -> tuple[str, str]:
    """The provider name and model `.env` selects for this interface."""
    section = {
        "llm": settings.llm,
        "embedder": settings.embedding,
        "reranker": settings.reranker,
        "ocr": settings.ocr,
    }[interface]
    return section.provider, section.model


def status(settings: Settings, interface: Interface) -> ProviderStatus:
    """Resolve one interface to a reportable status, without importing the implementation."""
    name, model = _configured(settings, interface)

    try:
        spec = spec_for(interface, name)
    except ProviderNotFound as exc:
        return ProviderStatus(
            interface=interface, name=name, model=model, state="unknown", detail=str(exc)
        )

    missing = missing_requirements(spec)
    if spec.phase and spec.name == "unset":
        state, detail = "unchosen", f"chosen in Phase {spec.phase}"
    elif spec.phase:
        state, detail = "declared", f"implemented in Phase {spec.phase}"
    elif missing:
        state, detail = "missing-deps", "not installed: " + ", ".join(missing)
    else:
        state, detail = "ready", spec.summary

    return ProviderStatus(
        interface=interface,
        name=name,
        model=model,
        state=state,  # type: ignore[arg-type]
        detail=detail,
        target=spec.target,
        missing=missing,
    )


def status_all(settings: Settings) -> list[ProviderStatus]:
    return [status(settings, interface) for interface in INTERFACES]


def _instantiate(spec: ProviderSpec, section: object) -> object:
    if spec.phase:
        raise ProviderNotImplemented(
            f"the {spec.interface} provider {spec.name!r} is registered but not written yet — "
            f"it lands in Phase {spec.phase}."
        )
    if missing := missing_requirements(spec):
        raise ProviderUnavailable(
            f"{spec.interface} provider {spec.name!r} needs "
            + ", ".join(missing)
            + ", which is not installed on this machine."
        )

    module_path, _, class_name = spec.target.partition(":")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)(section)


def load_llm(settings: Settings) -> LLM:
    return _instantiate(spec_for("llm", settings.llm.provider), settings.llm)  # type: ignore[return-value]


def load_embedder(settings: Settings) -> Embedder:
    return _instantiate(spec_for("embedder", settings.embedding.provider), settings.embedding)  # type: ignore[return-value]


def load_reranker(settings: Settings) -> Reranker:
    return _instantiate(spec_for("reranker", settings.reranker.provider), settings.reranker)  # type: ignore[return-value]


def load_ocr(settings: Settings) -> OCR:
    return _instantiate(spec_for("ocr", settings.ocr.provider), settings.ocr)  # type: ignore[return-value]
