"""Liveness and readiness endpoints (no API key required, no sensitive data returned)."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import PROJECT_ROOT
from app.core.errors import error_body
from app.models import Company

logger = logging.getLogger("crescent.health")
router = APIRouter(tags=["health"])


@lru_cache
def expected_migration_head() -> str | None:
    return ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_current_head()


@router.get("/health", summary="Application liveness")
def health(request: Request) -> dict[str, str]:
    """The process is running. Does not touch the database (see /health/ready)."""
    settings = request.app.state.settings
    return {"status": "ok", "service": "crescent-ticket-service", "version": settings.app_version}


@router.get(
    "/health/ready",
    summary="Database readiness",
    responses={503: {"description": "Database unreachable, migrations pending or company missing"}},
)
def readiness(request: Request) -> JSONResponse:
    """Ready only if the database answers, migrations are at head and the company exists."""
    settings = request.app.state.settings
    checks: dict[str, str] = {"database": "unknown", "migrations": "unknown", "company": "unknown"}
    error: dict[str, Any] | None = None
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            checks["database"] = "ok"

            current = None
            if inspect(connection).has_table("alembic_version"):
                current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            checks["migrations"] = "ok" if current is not None and current == expected_migration_head() else "pending"

            if checks["migrations"] == "ok":
                found = connection.execute(select(Company.id).where(Company.name == settings.company_name)).first()
                checks["company"] = "ok" if found else "missing"
    except SQLAlchemyError as exc:
        logger.warning("Readiness check failed: %s", type(exc).__name__)
        if checks["database"] != "ok":
            checks["database"] = "unavailable"
            error = error_body("DATABASE_UNAVAILABLE", "The database is currently unavailable")["error"]
        else:
            error = error_body("DATABASE_ERROR", "The database readiness query failed")["error"]

    ready = all(value == "ok" for value in checks.values())
    if not ready and error is None:
        error = error_body("NOT_READY", "Database migrations are pending or the company is missing")["error"]
    body: dict[str, Any] = {"status": "ready" if ready else "not_ready", "checks": checks}
    if error is not None:
        body["error"] = error
    return JSONResponse(status_code=200 if ready else 503, content=body)
