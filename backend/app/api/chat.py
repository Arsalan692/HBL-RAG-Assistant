"""`POST /chat` — the answer, streamed as Server-Sent Events.

Thin on purpose. `Answerer.stream` already emits events in the order
`StreamingState` expects, because that contract was settled while Phase 05 was
written rather than retrofitted here. This module translates those events into
SSE frames and does nothing else to them.

    event: step      → {"step": "searching" | "reading" | "composing"}
    event: sources   → {"sources": [...], "documentCount": n, "sourceCount": n}
    event: delta     → {"text": "..."}
    event: done      → {"refused": bool, "invented": [...], "superseded": [...]}
    event: error     → {"message": "..."}

Written against `StreamingResponse` and hand-formatted frames rather than an SSE
library. The format is two lines and a blank one; a dependency to produce it
would be the same decision as adding an HTTP client to call Ollama, which this
project also declined.

**The stream is generated inside the engine lock.** One machine, one set of
models — a second question waits rather than halving the speed of both. The
lock is held for the whole answer, which for a CPU-only laptop is minutes; that
is a truthful reflection of the hardware, not a flaw in the transport.
"""

from __future__ import annotations

import json
from typing import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.engine import Engine
from app.api.schemas import ChatRequest, Source
from app.generate.answer import AnswerResult
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter()


def _frame(event: str, payload: dict) -> str:
    """One SSE frame. The blank line is what ends it — without it a client waits."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _events(engine: Engine, question: str, request: Request) -> Iterator[str]:
    result = AnswerResult(question=question)
    try:
        with engine.exclusive():
            for event in engine.answerer.stream(question, into=result):
                # A reader who closed the tab should not keep a model busy for
                # another four minutes. Checked between events rather than
                # mid-token, which is as fine-grained as it needs to be.
                if _gone(request):
                    log.info("api.chat_abandoned", extra={"question": question[:60]})
                    return

                if event.kind == "step":
                    yield _frame("step", {"step": event.value})
                elif event.kind == "sources":
                    yield _frame(
                        "sources",
                        {
                            "sources": [Source.of(s).model_dump() for s in event.sources],
                            "documentCount": event.document_count,
                            "sourceCount": event.source_count,
                        },
                    )
                elif event.kind == "delta":
                    yield _frame("delta", {"text": event.value})
                elif event.kind == "error":
                    yield _frame("error", {"message": event.value})
                    return
                elif event.kind == "done":
                    yield _frame(
                        "done",
                        {
                            "refused": result.refused,
                            "invented": result.invented_citations,
                            "superseded": result.superseded_citations,
                            "unused": result.unused_sources,
                            "seconds": result.seconds,
                        },
                    )
    except Exception as exc:  # a model or a store failing mid-answer
        log.warning("api.chat_failed", extra={"error": str(exc)[:200]})
        yield _frame("error", {"message": str(exc)[:400]})


def _gone(request: Request) -> bool:
    """Whether the client has hung up, without awaiting anything.

    `Request.is_disconnected` is a coroutine and this generator is synchronous —
    running on the thread pool, where there is no loop to await on. Starlette
    records the disconnect on the request itself, so it can be read directly.
    """
    return bool(getattr(request, "_is_disconnected", False))


@router.post("/chat")
def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    engine: Engine = request.app.state.engine
    return StreamingResponse(
        _events(engine, body.question.strip(), request),
        media_type="text/event-stream",
        headers={
            # Without this an intermediary may buffer the whole answer and
            # deliver it at once, which looks exactly like the server hanging.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
