from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

T = TypeVar("T")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# Timestamps are always returned in UTC ("...Z"), whatever time zone the
# database session uses (PGlite inherits the host's offset; Supabase uses UTC).
UTCDateTime = Annotated[datetime, AfterValidator(_as_utc)]


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected and strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Number of records matching the filters")
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str = Field(examples=["TICKET_NOT_FOUND"])
    message: str = Field(examples=["Ticket not found"])
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI documentation for the standard error format."""
    descriptions = {
        401: "Missing or invalid API key",
        404: "Record not found",
        409: "Conflict with the current state of the data",
        422: "Request validation failed",
        503: "Database unavailable",
    }
    return {code: {"model": ErrorResponse, "description": descriptions.get(code, "Error")} for code in status_codes}
