"""Retrieval to answer, as a stream of events the frontend already understands.

The event names and their order are not free choices — they mirror
`StreamingState` in `frontend/src/components/chat/Thread.tsx`:

    step(searching) → step(reading) → sources → step(composing) → delta* → done

**Sources arrive before any answer text.** That ordering is load-bearing: the
frontend resolves `[1]` into a clickable pill at render time, so if a delta
containing `[2]` arrives before source 2 exists, the pill renders as a dead
number. Retrieval finishes first anyway; this just makes the guarantee explicit.

Two behaviours belong here rather than in the prompt, because a prompt is a
request and these have to be facts:

**A refusal never reaches the model.** When retrieval returns nothing, there is
nothing to ground an answer in, so the refusal is emitted directly. Asking a
model to decline is asking it to do the one thing it is worst at.

**Citations are checked against the passages that existed.** A model that writes
`[9]` when eight passages were supplied has invented a source, and the frontend
would render a pill pointing at nothing. Those are stripped from the text as it
streams and counted, so the fault is visible rather than silent.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator, Literal, Sequence

from app.config import Settings
from app.generate.prompt import REFUSAL, build
from app.logging_config import get_logger
from app.providers.base import LLM
from app.retrieve.search import Passage, RetrievalResult, Retriever

log = get_logger(__name__)

EventKind = Literal["step", "sources", "delta", "done", "error"]

#: `[1]`, `[12]`, and the `[1][3]` form the prompt asks for when two passages
#: support one claim. Deliberately not matching `[a]` or `[1.2]` — a markdown
#: link's `[text](url)` must survive untouched.
CITATION = re.compile(r"\[(\d{1,2})\]")

#: A citation cut off by the end of a delta: `[`, `[1`, `[12`. At most three
#: characters are ever held back, so nothing perceptible is delayed.
PARTIAL_CITATION = re.compile(r"\[\d{0,2}$")


@dataclass(frozen=True, slots=True)
class Event:
    kind: EventKind
    #: "searching" | "reading" | "composing" | "done" for `step`; the text delta
    #: for `delta`; the message for `error`.
    value: str = ""
    sources: tuple[Source, ...] = ()
    document_count: int = 0
    source_count: int = 0


@dataclass(frozen=True, slots=True)
class Source:
    """One citable passage, shaped for `frontend/src/types.ts`.

    `index` is the number the model was told to cite and the number the pill
    renders — they have to agree, or every citation points at the wrong
    document.
    """

    id: str
    index: int
    title: str
    section: str
    page: int
    relevance: float
    excerpt: str
    year: int | None = None
    #: The document's circular number where it has one. Carried through so a
    #: citation can name it, since it appears in no clause of any document.
    circular: str = ""
    superseded: bool = False

    @classmethod
    def of(cls, index: int, passage: Passage) -> Source:
        return cls(
            id=passage.chunk_id,
            index=index,
            title=passage.title,
            section=passage.section,
            page=passage.page,
            relevance=passage.score,
            excerpt=passage.text,
            year=passage.year,
            circular=passage.circular,
            superseded=passage.superseded,
        )


@dataclass
class AnswerResult:
    """What an answer turned out to be, once the stream has finished."""

    question: str
    text: str = ""
    sources: list[Source] = field(default_factory=list)
    refused: bool = False
    #: Citation numbers the model produced that no passage backed.
    invented_citations: list[int] = field(default_factory=list)
    #: Passages the answer never cited. High counts mean retrieval is too wide.
    unused_sources: list[int] = field(default_factory=list)
    #: Cited passages that came from a replaced edition. The prompt asks the
    #: model to say so in the sentence, but a rule the model may or may not
    #: follow is not a safeguard — a reader acting on a superseded clause is
    #: the specific harm here, so it is measured rather than trusted.
    superseded_citations: list[int] = field(default_factory=list)
    retrieval_seconds: float = 0.0
    seconds: float = 0.0


class Answerer:
    """Retrieval, grounding and generation for one question at a time."""

    def __init__(self, *, retriever: Retriever, llm: LLM, settings: Settings) -> None:
        self._retriever = retriever
        self._llm = llm
        self._settings = settings

    # --- streaming -----------------------------------------------------------

    def stream(self, question: str, into: AnswerResult | None = None) -> Iterator[Event]:
        """Yield events in the order the frontend expects them."""
        started = time.perf_counter()
        result = into if into is not None else AnswerResult(question=question)
        result.question = question

        # Loading the weights does not depend on the question, so on a machine
        # with room it starts now and overlaps retrieval. On a memory-bound one
        # it must not: see `_warms_ahead`.
        if self._warms_ahead():
            self._start_warming()

        yield Event(kind="step", value="searching")
        retrieval = self._retriever.search(question)
        result.retrieval_seconds = retrieval.seconds

        if retrieval.refused or not retrieval.passages:
            result.refused = True
            result.text = REFUSAL
            yield Event(kind="sources", sources=(), document_count=0, source_count=0)
            yield Event(kind="delta", value=REFUSAL)
            yield Event(kind="done", value="refused")
            result.seconds = round(time.perf_counter() - started, 2)
            log.info("answer.refused", extra={"question": question[:80]})
            return

        sources = tuple(
            Source.of(n, passage) for n, passage in enumerate(retrieval.passages, start=1)
        )
        result.sources = list(sources)

        yield Event(kind="step", value="reading")

        # Reranking is over, and the cross-encoder's ~2.3 GB is now dead weight
        # held through the longest part of the query. On CPU that is not a
        # micro-optimisation: bge-m3 (2.3 GB) plus the reranker (2.3 GB) plus a
        # resident qwen3:8b (4.9 GB) exhausted a 16 GB laptop mid-load and
        # segfaulted — no exception, no message. The same budget is tight on
        # the 16 GB card, where all three are documented as barely fitting.
        #
        # Kept resident on CUDA, where reloading costs real time per query and
        # the design accounts for it; released on CPU, where a query is slow
        # enough that a few seconds of reload is invisible beside a crash.
        if self._settings.runtime.device == "cpu":
            self._retriever.release_reranker()

        # Before any text: a `[2]` delta arriving before source 2 exists renders
        # as a pill pointing at nothing.
        yield Event(
            kind="sources",
            sources=sources,
            document_count=retrieval.document_count,
            source_count=len(sources),
        )
        yield Event(kind="step", value="composing")

        cited: set[int] = set()
        invented: set[int] = set()
        pieces: list[str] = []
        carry = ""

        try:
            for delta in self._llm.stream(
                build(question, retrieval.passages),
                temperature=self._settings.llm.temperature,
                max_tokens=self._settings.llm.max_output_tokens,
            ):
                ready, carry = _hold_partial_citation(carry + delta)
                clean = self._check_citations(ready, len(sources), cited, invented)
                pieces.append(clean)
                if clean:
                    yield Event(kind="delta", value=clean)

            if carry:  # a stream that ended mid-bracket; emit it as written
                pieces.append(carry)
                yield Event(kind="delta", value=carry)
        except Exception as exc:  # the model or its server, mid-answer
            result.text = "".join(pieces)
            log.warning("answer.stream_failed", extra={"error": str(exc)[:200]})
            yield Event(kind="error", value=str(exc)[:400])
            return

        result.text = "".join(pieces)
        result.invented_citations = sorted(invented)
        result.unused_sources = sorted(set(range(1, len(sources) + 1)) - cited)
        result.superseded_citations = sorted(
            source.index for source in sources if source.superseded and source.index in cited
        )
        result.seconds = round(time.perf_counter() - started, 2)

        log.info(
            "answer.done",
            extra={
                "sources": len(sources),
                "cited": len(cited),
                "invented": len(invented),
                "seconds": result.seconds,
            },
        )
        yield Event(kind="done", value="ok")

    def answer(self, question: str) -> AnswerResult:
        """The whole answer at once. Consumes `stream`, so behaviour is identical."""
        result = AnswerResult(question=question)
        for _ in self.stream(question, into=result):
            pass
        return result

    def _warms_ahead(self) -> bool:
        """Whether to load the model alongside retrieval, or strictly after it.

        `HBL_LLM_WARM_AHEAD` decides when set. Unset, the device does — and the
        two devices want opposite answers.

        On CUDA the VRAM budget already assumes all three models are resident,
        so overlapping the load with retrieval costs nothing and buys seconds
        off the first token.

        On CPU it is the opposite trade. Warming makes the LLM's ~4.9 GB
        resident *while* the embedder and reranker are working, and on a 16 GB
        laptop with a browser open that peak segfaults the process — observed
        twice, once in `hbl ask` and once in the API. Serialising costs a cold
        start instead, which is slow but survivable, and `timeout_s` is the
        knob for it.
        """
        configured = self._settings.llm.warm_ahead
        if configured is not None:
            return configured
        return self._settings.runtime.device != "cpu"

    def _start_warming(self) -> None:
        """Begin loading the generation model in the background, if it can be.

        Optional by protocol: an LLM with no `warm` simply does not get one.
        Daemon so it can never hold the process open, and errors are swallowed
        inside `warm` itself — the real request loads the model anyway, so a
        failure here costs nothing but the overlap.
        """
        warm = getattr(self._llm, "warm", None)
        if warm is None:
            return
        threading.Thread(target=warm, name="llm-warm", daemon=True).start()

    # --- grounding -----------------------------------------------------------

    def _check_citations(
        self, delta: str, available: int, cited: set[int], invented: set[int]
    ) -> str:
        """Drop citations no passage backs, and record which were used.

        Whole deltas only — `_hold_partial_citation` has already ensured no
        citation is cut in half at the end of this string.
        """
        if "[" not in delta:
            return delta

        def replace(match: re.Match[str]) -> str:
            number = int(match.group(1))
            if 1 <= number <= available:
                cited.add(number)
                return match.group(0)
            invented.add(number)
            return ""

        return CITATION.sub(replace, delta)


def _hold_partial_citation(text: str) -> tuple[str, str]:
    """Split off a citation the delta boundary cut in half.

    Returns `(safe_to_emit, hold_back)`. Real streams break tokens anywhere,
    including between `[1` and `2]` — and a per-delta regex sees neither half,
    so a valid citation goes unrecorded and an invented one survives to render
    as a pill pointing at nothing.

    The alternative, buffering whole sentences, would cost time-to-first-token,
    which this project treats as a requirement. At most three characters are
    ever held, and only when a delta happens to end mid-bracket.
    """
    match = PARTIAL_CITATION.search(text)
    if match:
        return text[: match.start()], text[match.start() :]
    return text, ""
