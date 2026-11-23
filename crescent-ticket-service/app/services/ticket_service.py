"""Ticket lifecycle: creation, assignment, status transitions, messages and events.

Lifecycle (Version 1)::

    OPEN --(assign agent / status)--> IN_PROGRESS --(status)--> RESOLVED

A resolved ticket is never reopened; a new customer enquiry creates a new ticket.
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, constraint_name
from app.models import Company, Ticket, TicketEvent, TicketMessage
from app.models.base import utcnow
from app.models.enums import MessageSource, SenderType, TicketEventType, TicketStatus
from app.repositories import agent_repository, customer_repository, ticket_repository
from app.repositories.ticket_repository import TicketFilters
from app.schemas.ticket import MessageCreate, TicketCreate

ALLOWED_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.OPEN: frozenset({TicketStatus.IN_PROGRESS}),
    TicketStatus.IN_PROGRESS: frozenset({TicketStatus.RESOLVED}),
    TicketStatus.RESOLVED: frozenset(),
}

ACTIVE_TICKET_INDEX = "uq_tickets_one_active_per_customer"


# --- helpers -------------------------------------------------------------------


def record_event(
    session: Session,
    ticket: Ticket,
    event_type: TicketEventType,
    *,
    previous_value: str | None = None,
    new_value: str | None = None,
) -> TicketEvent:
    return ticket_repository.add_event(
        session,
        TicketEvent(
            ticket_id=ticket.id,
            event_type=event_type.value,
            previous_value=previous_value,
            new_value=new_value,
        ),
    )


def active_ticket_conflict(active_ticket_id: uuid.UUID | None = None) -> ConflictError:
    details = {"active_ticket_id": str(active_ticket_id)} if active_ticket_id else None
    return ConflictError(
        "ACTIVE_TICKET_EXISTS",
        "The customer already has an active ticket; add messages to it or resolve it first",
        details=details,
    )


def new_ticket(
    session: Session,
    company: Company,
    *,
    customer_id: uuid.UUID,
    subject: str,
    description: str,
    priority: str,
) -> Ticket:
    """Insert an OPEN ticket plus its TICKET_CREATED event (caller commits)."""
    ticket = ticket_repository.add(
        session,
        Ticket(
            company_id=company.id,
            customer_id=customer_id,
            subject=subject,
            description=description,
            priority=priority,
            status=TicketStatus.OPEN.value,
        ),
    )
    record_event(session, ticket, TicketEventType.TICKET_CREATED, new_value=TicketStatus.OPEN.value)
    return ticket


def _get_ticket(session: Session, company: Company, ticket_id: uuid.UUID, *, for_update: bool = False) -> Ticket:
    ticket = ticket_repository.get(session, company.id, ticket_id, for_update=for_update)
    if ticket is None:
        raise NotFoundError("TICKET_NOT_FOUND", "Ticket not found")
    return ticket


# --- queries -------------------------------------------------------------------


def get_ticket_detail(session: Session, company: Company, ticket_id: uuid.UUID) -> Ticket:
    ticket = ticket_repository.get_with_relations(session, company.id, ticket_id)
    if ticket is None:
        raise NotFoundError("TICKET_NOT_FOUND", "Ticket not found")
    return ticket


def list_tickets(
    session: Session,
    company: Company,
    filters: TicketFilters,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Ticket], int]:
    return ticket_repository.list_tickets(session, company.id, filters, limit=limit, offset=offset)


def list_messages(
    session: Session, company: Company, ticket_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[TicketMessage], int]:
    _get_ticket(session, company, ticket_id)
    return ticket_repository.list_messages(session, ticket_id, limit=limit, offset=offset)


def list_events(
    session: Session, company: Company, ticket_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[TicketEvent], int]:
    _get_ticket(session, company, ticket_id)
    return ticket_repository.list_events(session, ticket_id, limit=limit, offset=offset)


# --- commands ------------------------------------------------------------------


def create_ticket(session: Session, company: Company, data: TicketCreate) -> Ticket:
    customer = customer_repository.get(session, company.id, data.customer_id)
    if customer is None:
        raise NotFoundError("CUSTOMER_NOT_FOUND", "Customer not found")
    active = ticket_repository.get_active_for_customer(session, company.id, customer.id)
    if active is not None:
        raise active_ticket_conflict(active.id)
    try:
        ticket = new_ticket(
            session,
            company,
            customer_id=customer.id,
            subject=data.subject,
            description=data.description,
            priority=data.priority.value,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if constraint_name(exc) == ACTIVE_TICKET_INDEX:  # concurrent creation for the same customer
            raise active_ticket_conflict() from exc
        raise
    return ticket


def assign_agent(session: Session, company: Company, ticket_id: uuid.UUID, agent_id: uuid.UUID) -> Ticket:
    ticket = _get_ticket(session, company, ticket_id, for_update=True)
    if ticket.status == TicketStatus.RESOLVED:
        raise ConflictError("TICKET_RESOLVED", "Resolved tickets cannot be assigned")

    # Scoped to the ticket's company: agents of another company are "not found".
    agent = agent_repository.get(session, ticket.company_id, agent_id)
    if agent is None:
        raise NotFoundError("AGENT_NOT_FOUND", "Agent not found")
    if not agent.is_active:
        raise ConflictError("AGENT_INACTIVE", "Inactive agents cannot be assigned to tickets")

    if ticket.assigned_agent_id == agent.id:
        session.commit()  # already assigned: nothing changes, just release the row lock
        return ticket

    # Change every ticket column before recording events: recording an event
    # flushes, and the ticket row must satisfy its CHECK constraints at that point.
    previous_agent_id = ticket.assigned_agent_id
    previous_status = TicketStatus(ticket.status)
    ticket.assigned_agent_id = agent.id
    if previous_status == TicketStatus.OPEN:
        ticket.status = TicketStatus.IN_PROGRESS.value

    record_event(
        session,
        ticket,
        TicketEventType.AGENT_ASSIGNED,
        previous_value=str(previous_agent_id) if previous_agent_id else None,
        new_value=str(agent.id),
    )
    if previous_status == TicketStatus.OPEN:
        record_event(
            session,
            ticket,
            TicketEventType.STATUS_CHANGED,
            previous_value=TicketStatus.OPEN.value,
            new_value=TicketStatus.IN_PROGRESS.value,
        )
    session.commit()
    return ticket


def update_status(session: Session, company: Company, ticket_id: uuid.UUID, target: TicketStatus) -> Ticket:
    ticket = _get_ticket(session, company, ticket_id, for_update=True)
    current = TicketStatus(ticket.status)
    if target not in ALLOWED_TRANSITIONS[current]:
        if current == TicketStatus.RESOLVED:
            message = "Resolved tickets cannot be reopened; a new customer enquiry creates a new ticket"
        elif target == current:
            message = f"Ticket is already {current.value}"
        else:
            message = f"Cannot change ticket status from {current.value} to {target.value}"
        raise ConflictError(
            "INVALID_STATUS_TRANSITION",
            message,
            details={
                "current_status": current.value,
                "requested_status": target.value,
                "allowed_statuses": sorted(status.value for status in ALLOWED_TRANSITIONS[current]),
            },
        )

    # status and resolved_at must change together (CHECK resolved_at_matches_status)
    # before the first flush, which happens when the first event is recorded.
    ticket.status = target.value
    if target == TicketStatus.RESOLVED:
        ticket.resolved_at = utcnow()

    record_event(session, ticket, TicketEventType.STATUS_CHANGED, previous_value=current.value, new_value=target.value)
    if ticket.resolved_at is not None:
        record_event(session, ticket, TicketEventType.TICKET_RESOLVED, new_value=ticket.resolved_at.isoformat())
    session.commit()
    return ticket


def add_message(session: Session, company: Company, ticket_id: uuid.UUID, data: MessageCreate) -> TicketMessage:
    ticket = _get_ticket(session, company, ticket_id, for_update=True)
    if ticket.status == TicketStatus.RESOLVED and data.sender_type != SenderType.INTERNAL:
        raise ConflictError(
            "TICKET_RESOLVED",
            "Resolved tickets only accept INTERNAL notes; new customer enquiries create a new ticket",
        )
    message = ticket_repository.add_message(
        session,
        TicketMessage(
            ticket_id=ticket.id,
            company_id=ticket.company_id,
            source=MessageSource.API.value,
            sender_type=data.sender_type.value,
            message_text=data.message_text,
        ),
    )
    ticket.updated_at = utcnow()
    session.commit()
    return message
