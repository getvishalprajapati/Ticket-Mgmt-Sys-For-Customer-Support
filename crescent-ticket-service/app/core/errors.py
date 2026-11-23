"""Domain errors and the consistent JSON error format used by every endpoint.

Every error response has the shape::

    {"error": {"code": "TICKET_NOT_FOUND", "message": "Ticket not found", "details": null}}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("crescent.errors")


class AppError(Exception):
    """An expected, client-visible error with a stable machine-readable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


class NotFoundError(AppError):
    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(404, code, message, details=details)


class ConflictError(AppError):
    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(409, code, message, details=details)


class ServiceUnavailableError(AppError):
    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(503, code, message, details=details)


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(code, message, details), headers=headers)


# PostgreSQL SQLSTATE codes that describe a conflict with existing rows.
_CONFLICT_PGCODES = frozenset({"23505", "23503"})  # unique_violation, foreign_key_violation

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    406: "NOT_ACCEPTABLE",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
}


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    # Only location, message and type are returned: echoing the submitted input
    # could reflect sensitive values back to the caller or into logs.
    return [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(422, "VALIDATION_ERROR", "Request validation failed", _validation_details(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
        return _error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        # Services translate the integrity errors they expect; this is the safety net.
        pgcode = _pgcode(exc)
        if pgcode in _CONFLICT_PGCODES:
            logger.warning(
                "Integrity conflict on %s %s: %s (%s)", request.method, request.url.path, pgcode, constraint_name(exc)
            )
            return _error_response(409, "CONFLICT", "The request conflicts with existing data")
        # CHECK / NOT NULL violations mean the service produced invalid data: a bug, not a client error.
        logger.error(
            "Integrity violation on %s %s: %s (%s)", request.method, request.url.path, pgcode, constraint_name(exc)
        )
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")

    async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Database unavailable on %s %s: %s", request.method, request.url.path, type(exc).__name__)
        return _error_response(503, "DATABASE_UNAVAILABLE", "The database is currently unavailable")

    app.add_exception_handler(OperationalError, _database_unavailable)
    app.add_exception_handler(InterfaceError, _database_unavailable)
    app.add_exception_handler(PoolTimeoutError, _database_unavailable)

    @app.exception_handler(DBAPIError)
    async def _dbapi_error(request: Request, exc: DBAPIError) -> JSONResponse:
        if exc.connection_invalidated:
            return await _database_unavailable(request, exc)
        if _pgcode(exc) == "42P01":  # undefined_table: migrations have not been applied
            logger.error("Database schema missing on %s %s; run 'alembic upgrade head'", request.method, request.url.path)
            return _error_response(
                503, "DATABASE_NOT_MIGRATED", "The database schema is not initialised; run the database migrations"
            )
        logger.exception("Database error on %s %s", request.method, request.url.path)
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")

    @app.exception_handler(SQLAlchemyError)
    async def _sqlalchemy_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("Database layer error on %s %s", request.method, request.url.path)
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")

    @app.exception_handler(Exception)
    async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Starlette re-raises the exception after this response is sent, so the
        # ASGI server logs the full traceback; only a summary is logged here.
        logger.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


def _pgcode(exc: DBAPIError) -> str:
    return str(getattr(exc.orig, "pgcode", None) or "unknown")


def constraint_name(exc: IntegrityError) -> str | None:
    """Name of the violated constraint, as reported by the PostgreSQL server."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)
