from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CompanyDep, ListPaginationDep, SessionDep
from app.core.errors import AppError
from app.models.enums import TicketStatus
from app.schemas.common import Page, error_responses
from app.schemas.customer import CustomerCreate, CustomerRead
from app.schemas.ticket import TicketRead
from app.schemas.validators import normalize_phone_number
from app.services import customer_service

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post(
    "",
    status_code=201,
    response_model=CustomerRead,
    summary="Create a customer",
    responses=error_responses(409),
)
def create_customer(data: CustomerCreate, session: SessionDep, company: CompanyDep) -> CustomerRead:
    return CustomerRead.model_validate(customer_service.create_customer(session, company, data))


@router.get("", response_model=Page[CustomerRead], summary="List or look up customers")
def list_customers(
    session: SessionDep,
    company: CompanyDep,
    page: ListPaginationDep,
    phone_number: Annotated[
        str | None, Query(max_length=32, description="Exact lookup by phone number (any common format)")
    ] = None,
) -> Page[CustomerRead]:
    normalized = None
    if phone_number is not None:
        try:
            normalized = normalize_phone_number(phone_number)
        except ValueError as exc:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "Request validation failed",
                details=[{"loc": ["query", "phone_number"], "msg": str(exc), "type": "value_error"}],
            ) from exc
    items, total = customer_service.list_customers(
        session, company, phone_number=normalized, limit=page.limit, offset=page.offset
    )
    return Page[CustomerRead](
        items=[CustomerRead.model_validate(c) for c in items], total=total, limit=page.limit, offset=page.offset
    )


@router.get(
    "/{customer_id}", response_model=CustomerRead, summary="Get a customer", responses=error_responses(404)
)
def get_customer(customer_id: uuid.UUID, session: SessionDep, company: CompanyDep) -> CustomerRead:
    return CustomerRead.model_validate(customer_service.get_customer(session, company, customer_id))


@router.get(
    "/{customer_id}/tickets",
    response_model=Page[TicketRead],
    summary="Customer ticket history (newest first)",
    responses=error_responses(404),
)
def list_customer_tickets(
    customer_id: uuid.UUID,
    session: SessionDep,
    company: CompanyDep,
    page: ListPaginationDep,
    status: TicketStatus | None = None,
) -> Page[TicketRead]:
    items, total = customer_service.list_customer_tickets(
        session,
        company,
        customer_id,
        status=status.value if status else None,
        limit=page.limit,
        offset=page.offset,
    )
    return Page[TicketRead](
        items=[TicketRead.model_validate(t) for t in items], total=total, limit=page.limit, offset=page.offset
    )
