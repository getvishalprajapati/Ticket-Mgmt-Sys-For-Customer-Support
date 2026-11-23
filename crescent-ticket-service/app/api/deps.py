"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from app.models import Company
from app.services import company_service


def get_session(request: Request) -> Iterator[Session]:
    """One session per request. Closing it rolls back anything not committed by a service."""
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_current_company(request: Request, session: SessionDep) -> Company:
    return company_service.get_configured_company(session, request.app.state.settings.company_name)


CompanyDep = Annotated[Company, Depends(get_current_company)]


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def list_pagination(
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (1-100)")] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000, description="Number of records to skip")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


def history_pagination(
    limit: Annotated[int, Query(ge=1, le=500, description="Page size (1-500)")] = 100,
    offset: Annotated[int, Query(ge=0, le=1_000_000, description="Number of records to skip")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


ListPaginationDep = Annotated[Pagination, Depends(list_pagination)]
HistoryPaginationDep = Annotated[Pagination, Depends(history_pagination)]
