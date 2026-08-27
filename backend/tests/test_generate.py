"""Grounded generation: the prompt, the refusal, and citation checking.

The LLM is faked throughout. What needs testing is not whether a model can
write — it is everything around it that decides whether an invented answer can
reach a reader who will act on it.
"""

from __future__ import annotations

from typing import Iterator, Sequence

import pytest

from app.config import Settings
from app.generate import REFUSAL, Answerer, format_passages
from app.generate.prompt import build
from app.retrieve.search import Passage, RetrievalResult


def _passage(n: int, text: str, *, year: int | None = 2025, superseded: bool = False) -> Passage:
    return Passage(
        chunk_id=f"doc:{n:04d}",
        doc_id="sanctions-2025" if not superseded else "sanctions-2023",
        title="Sanctions Compliance Policy",
        section=f"{n}. Screening",
        page=n,
        text=text,
        score=0.9 - n * 0.05,
        found_by="both",
        year=year,
        policy_family="sanctions",
        superseded=superseded,
    )


class FakeLLM:
    """Emits a scripted answer, one word per delta — so the citation checker is
    exercised on the chunk boundaries a real stream produces."""

    name = "fake"
    model = "fake"

    def __init__(self, answer: str = "Screening is required [1].") -> None:
        self.answer = answer
        self.messages: list = []

    def stream(self, messages, **kwargs) -> Iterator[str]:
        self.messages = list(messages)
        for word in self.answer.split(" "):
            yield word + " "

    def complete(self, messages, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError


class FakeRetriever:
    def __init__(self, result: RetrievalResult) -> None:
        self._result = result

    def search(self, query: str, *, top_k: int | None = None) -> RetrievalResult:
        return self._result


def _answerer(passages: list[Passage], llm: FakeLLM | None = None) -> Answerer:
    result = RetrievalResult(query="q", passages=passages, refused=not passages)
    return Answerer(
        retriever=FakeRetriever(result),  # type: ignore[arg-type]
        llm=llm or FakeLLM(),
        settings=Settings(),
    )


# --- the prompt --------------------------------------------------------------


def test_passages_are_numbered_from_one_to_match_the_citation_pills() -> None:
    """`Source.index`, the `[n]` the model writes and the pill the frontend
    renders are the same number. Off by one here and every citation in the
    product points at the wrong document."""
    block = format_passages([_passage(1, "Alpha."), _passage(2, "Beta.")])
    assert block.index("[1]") < block.index("[2]")
    assert "Alpha." in block and "Beta." in block


def test_a_superseded_passage_says_so_inside_the_passage() -> None:
    """Not only in the rules. A caveat in the instructions can be skimmed past;
    one in the passage header cannot be read around."""
    block = format_passages([_passage(1, "Old rule.", year=2023, superseded=True)])
    assert "SUPERSEDED" in block


def test_the_question_appears_before_and_after_the_evidence() -> None:
    """Passages run to thousands of tokens. A question stated only above them
    competes with everything that follows it."""
    messages = build("What is the threshold?", [_passage(1, "A clause.")])
    body = messages[-1].content
    assert body.count("What is the threshold?") == 2
    assert body.index("What is the threshold?") < body.index("A clause.")


def test_the_system_prompt_carries_the_exact_refusal_sentence() -> None:
    """The API and the tests both detect refusal by this string. A refusal that
    is merely similar to it is not detectable."""
    assert REFUSAL in build("q", [_passage(1, "x")])[0].content


# --- refusal -----------------------------------------------------------------


def test_nothing_retrieved_refuses_without_calling_the_model() -> None:
    """Asking a model to decline is asking it to do the thing it is worst at.
    With no passages there is nothing to ground an answer in, so the refusal is
    emitted directly and the model is never consulted."""
    llm = FakeLLM(answer="Here is some plausible invented guidance [1].")
    result = _answerer([], llm=llm).answer("something not in the corpus")

    assert result.refused
    assert result.text == REFUSAL
    assert llm.messages == [], "the model must not be called at all"


def test_the_refusal_still_emits_sources_and_done_events() -> None:
    """The frontend's stepper waits for these. A refusal that skips them leaves
    the UI spinning."""
    kinds = [e.kind for e in _answerer([]).stream("q")]
    assert kinds == ["step", "sources", "delta", "done"]


# --- event order -------------------------------------------------------------


def test_sources_arrive_before_any_answer_text() -> None:
    """Citation pills resolve at render time. A delta containing [2] that
    arrives before source 2 exists renders as a pill pointing at nothing."""
    events = list(_answerer([_passage(1, "A clause.")]).stream("q"))
    kinds = [e.kind for e in events]

    assert kinds.index("sources") < kinds.index("delta")
    assert kinds[-1] == "done"
    # And the steps run in the order the stepper draws them.
    steps = [e.value for e in events if e.kind == "step"]
    assert steps == ["searching", "reading", "composing"]


def test_the_source_list_matches_the_numbers_the_model_was_given() -> None:
    events = list(_answerer([_passage(1, "Alpha."), _passage(2, "Beta.")]).stream("q"))
    sources = next(e for e in events if e.kind == "sources").sources

    assert [s.index for s in sources] == [1, 2]
    assert [s.excerpt for s in sources] == ["Alpha.", "Beta."]
    assert sources[0].id == "doc:0001"


# --- citation checking -------------------------------------------------------


def test_a_citation_no_passage_backs_is_stripped_and_reported() -> None:
    """The model writing [9] when eight passages were supplied has invented a
    source, and the frontend would render a pill pointing at nothing."""
    llm = FakeLLM(answer="Screening is required [1] and reviewed yearly [9].")
    result = _answerer([_passage(1, "A clause.")], llm=llm).answer("q")

    assert "[9]" not in result.text
    assert "[1]" in result.text
    assert result.invented_citations == [9]


def test_a_citation_split_across_two_deltas_survives_intact() -> None:
    """Real streams break tokens anywhere, including inside `[12]`. A per-delta
    regex sees `[1` then `2]` and matches neither, so a valid citation would go
    unrecorded — and an invented one would slip through and render as a pill
    pointing at nothing."""

    class Chopping(FakeLLM):
        def stream(self, messages, **kwargs):
            self.messages = list(messages)
            for piece in ("Screening is required [", "1", "] and reviewed [", "9", "]."):
                yield piece

    result = _answerer([_passage(1, "A clause.")], llm=Chopping()).answer("q")

    assert "[1]" in result.text
    assert result.unused_sources == []       # the split citation was recorded
    assert "[9]" not in result.text          # ...and the split invention removed
    assert result.invented_citations == [9]


def test_passages_the_answer_ignored_are_counted() -> None:
    """A large unused count means retrieval handed over more than the answer
    needed, and prefill is the biggest cost in time-to-first-token."""
    llm = FakeLLM(answer="Screening is required [1].")
    result = _answerer([_passage(1, "A."), _passage(2, "B."), _passage(3, "C.")], llm=llm).answer("q")
    assert result.unused_sources == [2, 3]


def test_a_markdown_link_is_not_mistaken_for_a_citation() -> None:
    """`[text](url)` must survive. Only bare bracketed numbers are citations."""
    llm = FakeLLM(answer="See [the policy](https://x/y) and clause [1].")
    result = _answerer([_passage(1, "A clause.")], llm=llm).answer("q")
    assert "[the policy](https://x/y)" in result.text


def test_a_failure_mid_answer_keeps_what_had_already_streamed() -> None:
    """The server can drop halfway. Whatever reached the reader is real and
    should not be discarded — but the stream must end with an error, not a
    `done` that implies the answer finished."""

    class Failing(FakeLLM):
        def stream(self, messages, **kwargs):
            yield "Screening is "
            raise RuntimeError("connection reset")

    answerer = _answerer([_passage(1, "A clause.")], llm=Failing())
    events = list(answerer.stream("q"))

    assert events[-1].kind == "error"
    assert "connection reset" in events[-1].value
    assert "done" not in [e.kind for e in events]


# --- the cold-start timeout --------------------------------------------------


def test_a_first_token_timeout_explains_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """`timeout_s` covers a single read, and the first read is the expensive
    one — the weights load and the whole prompt is prefilled before any token
    appears. On CPU that passes 180s while the same request takes seconds once
    the model is resident, so a bare `TimeoutError` is a misleading way to
    report a machine that is merely cold."""
    from app.config import LLMSettings
    from app.errors import ProviderUnavailable
    from app.providers.llm.ollama import OllamaLLM

    llm = OllamaLLM(LLMSettings(_env_file=None))

    def _never_answers(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr("app.providers.llm.ollama.urlopen", _never_answers)

    with pytest.raises(ProviderUnavailable) as excinfo:
        llm._request("/api/chat", {"model": "x"})

    message = str(excinfo.value)
    assert "cold start" in message
    # Every suggestion must be actionable, not a diagnosis on its own.
    assert "ollama run" in message
    assert "HBL_LLM_TIMEOUT_S" in message
