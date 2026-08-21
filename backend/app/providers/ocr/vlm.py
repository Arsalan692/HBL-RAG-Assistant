"""Page recognition by asking a local vision model to read the page.

`qwen2.5vl:7b` is already pulled on the workstation and Ollama is already the
generation transport, so this candidate costs no download, no new dependency
and no staged weights — which on an air-gapped machine is the difference
between benching it today and filing a permission request.

The trade is that a VLM *reads* rather than *recognises*. It handles bad scans
and merged table cells better than a detector-plus-recogniser pipeline, and it
will happily invent a plausible line where the page is illegible. That failure
mode is the whole reason the bench-off compares output by eye instead of
trusting a benchmark score.
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import OcrSettings
from app.errors import ProviderUnavailable
from app.logging_config import get_logger
from app.providers.base import OcrResult, PageRef

log = get_logger(__name__)

#: Written to fight the two things a vision model does wrong on a policy page:
#: it summarises when it should transcribe, and it silently smooths over the
#: parts it cannot read. Both are far more damaging here than a missing word —
#: a summary reads as a quotation once it is retrieved and cited.
PROMPT = """Transcribe this page exactly as it appears. Output GitHub-flavoured markdown.

Rules:
- Transcribe every word. Do not summarise, paraphrase, correct or reorder anything.
- Reproduce tables as markdown tables, preserving every row and column. If a cell
  is empty, leave it empty.
- Keep headings, numbered clauses and bullet markers exactly as printed, including
  their numbering (2.1.3 stays 2.1.3).
- Where text is illegible, write [illegible] rather than guessing.
- Only use a markdown table where the page actually shows a table with rows and
  columns. A title page, a heading block or a list is not a table.
- Do not wrap your output in a code fence. Output the markdown directly.
- Do not add commentary, explanation, or a preamble. Output only the page content.
"""


class VlmOCR:
    """The `OCR` protocol, backed by a vision model served by Ollama."""

    name = "vlm"

    def __init__(self, settings: OcrSettings) -> None:
        self._settings = settings
        self.model = settings.model or "qwen2.5vl:7b"
        self._base = settings.base_url.rstrip("/")
        # Reading a dense page is slower than answering a question about one,
        # and this runs unattended over hundreds of pages. Not derived from the
        # LLM timeout, which is tuned for interactive answering.
        self._timeout_s = 600.0

    # --- HTTP ----------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self._base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data else "GET",
        )
        try:
            return urlopen(request, timeout=self._timeout_s)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:400]
            raise ProviderUnavailable(f"Ollama returned {exc.code} for {path}: {body}") from exc
        except URLError as exc:
            raise ProviderUnavailable(
                f"cannot reach Ollama at {self._base} ({exc.reason}). "
                "Is `ollama serve` running on this machine?"
            ) from exc

    # --- OCR protocol --------------------------------------------------------

    def recognise(self, page: PageRef) -> OcrResult:
        if page.image_path is None or not page.image_path.exists():
            raise ProviderUnavailable(
                f"{self.name} reads images, but no rendered page was supplied for "
                f"{page.pdf_path.name} p.{page.page_number}. Render it first."
            )

        encoded = base64.b64encode(page.image_path.read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": PROMPT, "images": [encoded]}],
            "stream": False,
            "options": {
                # Transcription, not composition. Any creativity here is an error.
                "temperature": 0.0,
                "top_p": 1.0,
                # A dense A4 page runs to roughly 1,200 tokens of markdown;
                # tables push it higher. Truncating mid-table is worse than slow.
                "num_predict": 4096,
                "num_ctx": 8192,
            },
            "keep_alive": "30m",
        }

        started = time.perf_counter()
        with self._post("/api/chat", payload) as response:
            body = json.loads(response.read().decode("utf-8"))
        duration = time.perf_counter() - started

        if error := body.get("error"):
            raise ProviderUnavailable(f"{self.model} failed on page {page.page_number}: {error}")

        raw = _unfence(body.get("message", {}).get("content", "").strip())
        markdown = _strip_images(raw)
        warnings: list[str] = []
        if raw != markdown and not markdown:
            # The model returned an image placeholder *instead of* reading the
            # page. Seen once on a title page, where it invented an imgur URL
            # and dropped the document's own title — the single most valuable
            # line in the file for retrieval.
            warnings.append("returned only an image placeholder, no text")
        if not markdown:
            warnings.append("empty output")
        if body.get("done_reason") == "length":
            warnings.append("hit the token limit — output is truncated")
        if "[illegible]" in markdown:
            warnings.append(f"{markdown.count('[illegible]')} illegible region(s)")
        if repeat := _degenerate_repeat(markdown):
            warnings.append(f"looks like a repetition loop — one line occurs {repeat} times")

        log.info(
            "ocr.page",
            extra={
                "engine": self.name,
                "model": self.model,
                "page": page.page_number,
                "seconds": round(duration, 1),
                "chars": len(markdown),
            },
        )

        return OcrResult(
            markdown=markdown,
            engine=f"{self.name}:{self.model}",
            page_number=page.page_number,
            table_count=_count_tables(markdown),
            duration_s=duration,
            warnings=tuple(warnings),
        )

    def recognise_batch(self, pages: Sequence[PageRef]) -> list[OcrResult]:
        """Sequential on purpose. Ollama serialises requests to one model anyway,
        and issuing them in parallel only risks evicting the weights mid-run."""
        return [self.recognise(page) for page in pages]

    # --- Health --------------------------------------------------------------

    def probe(self) -> tuple[bool, str]:
        try:
            with self._post("/api/tags") as response:
                body = json.loads(response.read().decode("utf-8"))
        except ProviderUnavailable as exc:
            return False, str(exc)

        available = [entry["name"] for entry in body.get("models", [])]
        if any(tag == self.model or tag.split(":")[0] == self.model for tag in available):
            return True, f"{self.model} available"
        return False, (
            f"{self.model!r} is not pulled. Available: "
            + (", ".join(available) if available else "none")
            + f". Run: ollama pull {self.model}"
        )


def _unfence(markdown: str) -> str:
    """Strip a code fence wrapping the whole page.

    Every model benched did this on at least one page — asked for markdown, they
    return markdown *inside* ```markdown, because that is what markdown looks
    like in their training data. Telling them not to in the prompt helps and
    does not settle it, so it is also removed here.

    Only an outer fence enclosing the entire response is removed. A fence around
    part of the page is real content — some of these documents quote code and
    system messages — and must survive.
    """
    if not markdown.startswith("```"):
        return markdown

    lines = markdown.splitlines()
    if len(lines) < 2 or not lines[-1].strip().startswith("```"):
        return markdown
    # A fence enclosing everything has exactly two fence lines: first and last.
    if sum(1 for line in lines if line.strip().startswith("```")) != 2:
        return markdown
    return "\n".join(lines[1:-1]).strip()


#: Markdown image syntax. Not link syntax — the difference is the leading `!`,
#: and it matters: these policies genuinely cite SECP, OFAC, OFSI and the EU
#: sanctions map by URL, and those are content that must survive.
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _strip_images(markdown: str) -> str:
    """Remove embedded images from a transcription.

    A page transcription can never legitimately contain one: the engine is
    asked for the text on the page, and it has no way to host an image even if
    the page holds a figure. What it can do — observed once on the Insider
    Trading title page — is emit `![](https://i.imgur.com/...)` in place of
    reading, inventing a plausible URL and discarding the document's title.

    Plain links are deliberately left alone.
    """
    return _IMAGE.sub("", markdown).strip()


def _degenerate_repeat(markdown: str, *, threshold: int = 8) -> int:
    """How many times the most repeated line occurs, if that looks pathological.

    A vision model handed a nearly-empty page can fall into a loop, re-emitting
    the little it found until it exhausts its token budget. Benched on a title
    page, one candidate produced the same four lines 115 times.

    This is the failure that most needs flagging rather than fixing: the output
    is fluent, every word of it is genuinely on the page, and nothing downstream
    would question it — it would simply index the same sentence a hundred times
    and skew retrieval toward it. Returns 0 when the text looks normal.
    """
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if len(lines) < threshold * 2:
        return 0

    counts: dict[str, int] = {}
    for line in lines:
        # Table rules and fences legitimately repeat; content lines do not.
        if len(line) < 12 or set(line) <= set("|-:` \t"):
            continue
        counts[line] = counts.get(line, 0) + 1
    if not counts:
        return 0

    most = max(counts.values())
    return most if most >= threshold else 0


def _count_tables(markdown: str) -> int:
    """Blocks of pipe-delimited rows.

    Counted as runs of adjacent `|`-delimited lines rather than by the header
    separator `|---|---|`, because plenty of real tables here have no header
    row: the abbreviations glossary in the AML policy runs straight into
    `| PEPCO | Pakistan Electric Power Company |`. Counting separators reported
    that page as having no table at all, which is exactly the alarm this signal
    exists to raise — so it must not cry wolf.

    An engine that finds no table on a page of tables has flattened them into
    prose, the single most damaging OCR failure for this corpus, because the
    result still reads as fact once retrieved and cited.
    """
    count = 0
    run = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            run += 1
            if run == 2:  # two adjacent rows is the smallest believable table
                count += 1
        else:
            run = 0
    return count
