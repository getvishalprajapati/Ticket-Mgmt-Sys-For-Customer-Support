from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models import Company, Customer, Ticket
from app.repositories import customer_repository, ticket_repository
from app.repositories.ticket_repository import TicketFilters
from app.schemas.customer import CustomerCreate


def _duplicate(existing_id: uuid.UUID | None = None) -> ConflictError:
    details = {"existing_customer_id": str(existing_id)} if existing_id else None
    return ConflictError("DUPLICATE_CUSTOMER", "A customer with this phone number already exists", details=details)


def create_customer(session: Session, company: Company, data: CustomerCreate) -> Customer:
    existing = customer_repository.get_by_phone(session, company.id, data.phone_number)
    if existing is not None:
        raise _duplicate(existing.id)
    customer = Customer(company_id=company.id, name=data.name, phone_number=data.phone_number)
    try:
        customer_repository.add(session, customer)
        session.commit()
    except IntegrityError as exc:  # concurrent insert of the same phone number
        session.rollback()
        raise _duplicate() from exc
    return customer


def get_customer(session: Session, company: Company, customer_id: uuid.UUID) -> Customer:
    customer = customer_repository.get(session, company.id, customer_id)
    if customer is None:
        raise NotFoundError("CUSTOMER_NOT_FOUND", "Customer not found")
    return customer


def list_customers(
    session: Session,
    company: Company,
    *,
    phone_number: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Customer], int]:
    return customer_repository.list_customers(
        session, company.id, phone_number=phone_number, limit=limit, offset=offset
    )


def list_customer_tickets(
    session: Session,
    company: Company,
    customer_id: uuid.UUID,
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Ticket], int]:
    """Full ticket history (active and resolved), newest first."""
    get_customer(session, company, customer_id)
    return ticket_repository.list_tickets(
        session,
        company.id,
        TicketFilters(customer_id=customer_id, status=status),
        limit=limit,
        offset=offset,
    )
