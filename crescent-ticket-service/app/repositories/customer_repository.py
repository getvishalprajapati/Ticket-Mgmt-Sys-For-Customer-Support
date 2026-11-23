from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer
from app.repositories.common import paginate


def get(session: Session, company_id: uuid.UUID, customer_id: uuid.UUID) -> Customer | None:
    return session.scalar(select(Customer).where(Customer.company_id == company_id, Customer.id == customer_id))


def get_by_phone(session: Session, company_id: uuid.UUID, phone_number: str) -> Customer | None:
    return session.scalar(
        select(Customer).where(Customer.company_id == company_id, Customer.phone_number == phone_number)
    )


def list_customers(
    session: Session,
    company_id: uuid.UUID,
    *,
    phone_number: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Customer], int]:
    statement = select(Customer).where(Customer.company_id == company_id)
    if phone_number is not None:
        statement = statement.where(Customer.phone_number == phone_number)
    statement = statement.order_by(Customer.created_at.desc(), Customer.id)
    return paginate(session, statement, limit=limit, offset=offset)


def add(session: Session, customer: Customer) -> Customer:
    session.add(customer)
    session.flush()
    return customer
