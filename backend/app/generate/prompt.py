"""Turning retrieved passages into a prompt the model cannot wander out of.

The failure this file exists to prevent is not a wrong answer — it is a
*plausible* one. A model asked about bank policy will happily produce fluent,
correctly-formatted, entirely invented compliance guidance, and a reader has no
way to tell that from the real thing. Every rule below is aimed at making
invention either impossible or obvious.

Three things carry most of the weight:

**Numbered passages, cited by number.** Each passage is labelled `[1]`, `[2]`
and the model is required to cite the number it used. The frontend already
turns those literal tokens into clickable pills (`components/chat/Markdown.tsx`),
so the format is a contract, not a preference — and a claim with no number
beside it is visibly unsupported.

**The refusal is spelled out, not implied.** "Only use the passages" is advice a
model will follow until the passages are thin, at which point it helps. So the
instruction names the exact situation and the exact words to use.

**Vintages are surfaced.** This corpus holds two editions of the AML/KYC and
Sanctions policies. Told nothing, a model blends them into one confident
paragraph. Told which is current and that the older one is superseded, it
reports the difference — which is usually what the question was really about.
"""

from __future__ import annotations

from typing import Sequence

from app.providers.base import ChatMessage
from app.retrieve.search import Passage

#: What the model must say when the passages do not answer the question. Kept
#: as a constant because the API and the tests both need to recognise it, and a
#: refusal that is merely *similar* to this is not detectable.
REFUSAL = (
    "I could not find this in the indexed policy documents."
)

SYSTEM = """\
You are an assistant answering questions about HBL's internal policy and \
standard-operating-procedure documents. You are used by bank staff who will \
act on what you say.

Answer ONLY from the numbered passages given to you in the user message.

Rules, in order of importance:

1. Every factual claim must be followed by the number of the passage it came \
from, written as [1], [2], and so on. Cite more than one where more than one \
supports the claim: [1][3]. A sentence with no citation reads as something you \
invented.
2. If the passages do not contain the answer, reply with exactly this sentence \
and nothing else: "{refusal}" Do not guess, do not reason from general \
knowledge of banking, and do not offer what the answer is "likely" to be. \
Saying you do not know is a correct answer; a plausible invention is not.
3. Never state a threshold, a monetary amount, a deadline, a percentage or an \
approval authority that does not appear verbatim in a passage. These are the \
details staff act on and the ones a model most readily fabricates.
4. A passage marked SUPERSEDED comes from an edition that has been replaced. \
Prefer the current edition wherever it covers the point. If you cite a \
SUPERSEDED passage at all, say so in that same sentence — for example: "The \
2023 edition required … [4]." Never present it as the current rule, and never \
cite it silently: a reader acting on a replaced clause is the specific harm \
this rule exists to prevent.
5. If passages from different years disagree, say so explicitly and give the \
current position first — for example: "Under the 2025 policy … [1]. The 2023 \
edition instead required … [4]." Never silently merge them.
6. Quote the document's own wording for anything obligatory. Prefer "must" \
over "should" only when the passage does.

Style: answer the question directly, in as few words as it takes. Use markdown. \
Use a table when comparing several items or listing thresholds — tables render \
properly. Do not open with a summary of the question, do not describe what you \
are about to do, and do not add advice the documents do not contain.\
"""


def system_message() -> ChatMessage:
    return ChatMessage(role="system", content=SYSTEM.format(refusal=REFUSAL))


def format_passages(passages: Sequence[Passage]) -> str:
    """Render the retrieved passages as the numbered block the answer cites.

    The number here is the number the model must write, and the same number the
    frontend renders as a pill — so `Source.index` in the API response has to
    match this exactly or every citation points at the wrong document.
    """
    blocks: list[str] = []
    for n, passage in enumerate(passages, start=1):
        header = f"[{n}] {passage.title}"
        if passage.year:
            header += f" ({passage.year})"
        if passage.superseded:
            # Stated in the passage itself rather than only in the rules, so it
            # is impossible to read the passage without meeting the caveat.
            header += " — SUPERSEDED, a newer edition is also below"
        if passage.section:
            header += f"\n    Section: {passage.section}"
        header += f"\n    Page: {passage.page}"
        blocks.append(f"{header}\n\n{passage.text.strip()}")
    return "\n\n---\n\n".join(blocks)


def user_message(question: str, passages: Sequence[Passage]) -> ChatMessage:
    """The question and its evidence, in that order.

    Question first *and* last. The passages can run to several thousand tokens,
    and a question buried above them competes with everything that follows;
    repeating it after is a cheap, reliable way to keep the answer on target.
    """
    return ChatMessage(
        role="user",
        content=(
            f"Question: {question}\n\n"
            f"Passages:\n\n{format_passages(passages)}\n\n"
            f"---\n\n"
            f"Answer the question using only the passages above, citing them by "
            f"number.\n\nQuestion: {question}"
        ),
    )


def build(question: str, passages: Sequence[Passage]) -> list[ChatMessage]:
    return [system_message(), user_message(question, passages)]
