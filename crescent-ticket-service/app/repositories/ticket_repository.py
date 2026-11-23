from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Ticket, TicketEvent, TicketMessage
from app.models.enums import ACTIVE_TICKET_STATUSES
from app.repositories.common import paginate


@dataclass(frozen=True)
class TicketFilters:
    status: str | None = None
    priority: str | None = None
    customer_id: uuid.UUID | None = None
    assigned_agent_id: uuid.UUID | None = None


# --- tickets -----------------------------------------------------------------


def get(
    session: Session,
    company_id: uuid.UUID,
    ticket_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Ticket | None:
    statement = select(Ticket).where(Ticket.company_id == company_id, Ticket.id == ticket_id)
    if for_update:
        # Row lock: serialises concurrent assignment / status changes on PostgreSQL.
        statement = statement.with_for_update()
    return session.scalar(statement)


def get_with_relations(session: Session, company_id: uuid.UUID, ticket_id: uuid.UUID) -> Ticket | None:
    statement = (
        select(Ticket)
        .where(Ticket.company_id == company_id, Ticket.id == ticket_id)
        .options(selectinload(Ticket.customer), selectinload(Ticket.assigned_agent))
        .execution_options(populate_existing=True)
    )
    return session.scalar(statement)


def get_active_for_customer(
    session: Session,
    company_id: uuid.UUID,
    customer_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Ticket | None:
    statement = select(Ticket).where(
        Ticket.company_id == company_id,
        Ticket.customer_id == customer_id,
        Ticket.status.in_([status.value for status in ACTIVE_TICKET_STATUSES]),
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def list_tickets(
    session: Session,
    company_id: uuid.UUID,
    filters: TicketFilters,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Ticket], int]:
    statement = select(Ticket).where(Ticket.company_id == company_id)
    if filters.status is not None:
        statement = statement.where(Ticket.status == filters.status)
    if filters.priority is not None:
        statement = statement.where(Ticket.priority == filters.priority)
    if filters.customer_id is not None:
        statement = statement.where(Ticket.customer_id == filters.customer_id)
    if filters.assigned_agent_id is not None:
        statement = statement.where(Ticket.assigned_agent_id == filters.assigned_agent_id)
    statement = statement.order_by(Ticket.created_at.desc(), Ticket.id)
    return paginate(session, statement, limit=limit, offset=offset)


def add(session: Session, ticket: Ticket) -> Ticket:
    session.add(ticket)
    session.flush()
    return ticket


# --- messages ----------------------------------------------------------------


def add_message(session: Session, message: TicketMessage) -> TicketMessage:
    session.add(message)
    session.flush()
    return message


def get_message_by_external_id(
    session: Session,
    company_id: uuid.UUID,
    source: str,
    external_message_id: str,
) -> TicketMessage | None:
    return session.scalar(
        select(TicketMessage).where(
            TicketMessage.company_id == company_id,
            TicketMessage.source == source,
            TicketMessage.external_message_id == external_message_id,
        )
    )


def list_messages(
    session: Session,
    ticket_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[TicketMessage], int]:
    statement = (
        select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id)
        .order_by(TicketMessage.created_at.asc(), TicketMessage.id)
    )
    return paginate(session, statement, limit=limit, offset=offset)


# --- events ------------------------------------------------------------------


def add_event(session: Session, event: TicketEvent) -> TicketEvent:
    session.add(event)
    session.flush()
    return event


def list_events(
    session: Session,
    ticket_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[TicketEvent], int]:
    statement = (
        select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.created_at.asc(), TicketEvent.id)
    )
    return paginate(session, statement, limit=limit, offset=offset)
