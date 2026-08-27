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
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.engine import Engine
from app.api.jobs import JobRegistry
from app.config import ROOT_DIR, Settings, get_settings
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

    # The interface, served by the same process on the same port. Mounted last
    # so every API route above wins the match — a static mount at "/" is a
    # catch-all, and mounting it first would swallow /chat.
    _mount_interface(application)
    return application


def frontend_dist() -> Path:
    """Where `npm run build` puts the interface."""
    return ROOT_DIR / "frontend" / "dist"


def _mount_interface(application: FastAPI) -> None:
    """Serve the built frontend at `/`, if it has been built.

    One command and one port for the whole product, which also removes CORS
    from the picture entirely: the page and the API share an origin, so the
    browser has nothing to check.

    Absence is not an error. The workstation may run this purely to ingest and
    answer over HTTP, and a missing `dist/` should leave a working API rather
    than a server that refuses to start. `hbl serve` says how to build it.
    """
    dist = frontend_dist()
    if not (dist / "index.html").exists():
        log.info("api.no_interface", extra={"looked_in": str(dist)})
        return

    application.mount("/", StaticFiles(directory=dist, html=True), name="interface")
    log.info("api.interface_mounted", extra={"directory": str(dist)})
