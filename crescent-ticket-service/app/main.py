"""FastAPI application factory.

Run with:  uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.api.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.database import create_db_engine, create_session_factory
from app.core.errors import register_exception_handlers

logger = logging.getLogger("crescent")

DESCRIPTION = """
Ticket management backend (Microservice 2) for **Crescent Motors** customer support.

* All `/api/v1` endpoints require the `X-API-Key` header (use the **Authorize** button).
* Errors use one format: `{"error": {"code", "message", "details"}}`.
* `POST /api/v1/intake/messages` simulates inbound customer messages (no WhatsApp in Version 1).
"""


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("crescent").setLevel(level)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings.log_level)

    # The engine connects lazily: the API starts even if the database is down and
    # reports it through /health/ready and 503 responses.
    engine = create_db_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Starting %s %s (env=%s)", settings.app_name, settings.app_version, settings.app_env)
        yield
        engine.dispose()
        logger.info("Database connections closed")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    return app
