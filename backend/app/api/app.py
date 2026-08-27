"""The FastAPI application.

Built by a factory rather than a module-level `app = FastAPI()`, so tests can
construct one against a temporary index without a real corpus, and so the
expensive objects are created when the process is actually serving rather than
whenever something imports this module.

CORS is restricted to the origins in `HBL_API_CORS_ORIGINS`, which default to
the Vite dev server on localhost. The corpus is confidential; a wildcard here
would let any page in the browser read bank policy through this port.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.engine import Engine
from app.api.jobs import JobRegistry
from app.config import Settings, get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Build the application. Pass `engine` to supply a pre-built one in tests."""
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        # Models load here, once. A failure is a failure to start, which is
        # what it should be — a server that boots and then answers every
        # question with a 500 is harder to diagnose than one that refuses.
        built = engine or Engine(resolved)
        application.state.engine = built
        application.state.jobs = JobRegistry()
        try:
            yield
        finally:
            built.close()

    application = FastAPI(
        title="HBL Policy Assistant",
        summary="Offline retrieval over HBL's internal policy documents.",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.api.origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    application.include_router(chat_router)
    application.include_router(documents_router)
    return application
