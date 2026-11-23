from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CompanyDep, HistoryPaginationDep, ListPaginationDep, SessionDep
from app.models.enums import TicketPriority, TicketStatus
from app.repositories.ticket_repository import TicketFilters
from app.schemas.common import Page, error_responses
from app.schemas.ticket import (
    EventRead,
    MessageCreate,
    MessageRead,
    TicketAssign,
    TicketCreate,
    TicketDetail,
    TicketRead,
    TicketStatusUpdate,
)
from app.services import ticket_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post(
    "",
    status_code=201,
    response_model=TicketRead,
    summary="Create a ticket for an existing customer",
    responses=error_responses(404, 409),
)
def create_ticket(data: TicketCreate, session: SessionDep, company: CompanyDep) -> TicketRead:
    return TicketRead.model_validate(ticket_service.create_ticket(session, company, data))


@router.get("", response_model=Page[TicketRead], summary="List and filter tickets (newest first)")
def list_tickets(
    session: SessionDep,
    company: CompanyDep,
    page: ListPaginationDep,
    status: TicketStatus | None = None,
    priority: TicketPriority | None = None,
    customer_id: uuid.UUID | None = None,
    assigned_agent_id: uuid.UUID | None = None,
) -> Page[TicketRead]:
    filters = TicketFilters(
        status=status.value if status else None,
        priority=priority.value if priority else None,
        customer_id=customer_id,
        assigned_agent_id=assigned_agent_id,
    )
    items, total = ticket_service.list_tickets(session, company, filters, limit=page.limit, offset=page.offset)
    return Page[TicketRead](
        items=[TicketRead.model_validate(t) for t in items], total=total, limit=page.limit, offset=page.offset
    )


@router.get(
    "/{ticket_id}", response_model=TicketDetail, summary="Get ticket details", responses=error_responses(404)
)
def get_ticket(ticket_id: uuid.UUID, session: SessionDep, company: CompanyDep) -> TicketDetail:
    return TicketDetail.model_validate(ticket_service.get_ticket_detail(session, company, ticket_id))


@router.patch(
    "/{ticket_id}/assign",
    response_model=TicketRead,
    summary="Assign an active support agent (OPEN tickets move to IN_PROGRESS)",
    responses=error_responses(404, 409),
)
def assign_ticket(ticket_id: uuid.UUID, data: TicketAssign, session: SessionDep, company: CompanyDep) -> TicketRead:
    return TicketRead.model_validate(ticket_service.assign_agent(session, company, ticket_id, data.agent_id))


@router.patch(
    "/{ticket_id}/status",
    response_model=TicketRead,
    summary="Change ticket status (OPEN -> IN_PROGRESS -> RESOLVED)",
    responses=error_responses(404, 409),
)
def update_ticket_status(
    ticket_id: uuid.UUID, data: TicketStatusUpdate, session: SessionDep, company: CompanyDep
) -> TicketRead:
    return TicketRead.model_validate(ticket_service.update_status(session, company, ticket_id, data.status))


@router.post(
    "/{ticket_id}/messages",
    status_code=201,
    response_model=MessageRead,
    summary="Add a message or an internal note",
    responses=error_responses(404, 409),
)
def add_ticket_message(
    ticket_id: uuid.UUID, data: MessageCreate, session: SessionDep, company: CompanyDep
) -> MessageRead:
    return MessageRead.model_validate(ticket_service.add_message(session, company, ticket_id, data))


@router.get(
    "/{ticket_id}/messages",
    response_model=Page[MessageRead],
    summary="Ticket messages in chronological order",
    responses=error_responses(404),
)
def list_ticket_messages(
    ticket_id: uuid.UUID, session: SessionDep, company: CompanyDep, page: HistoryPaginationDep
) -> Page[MessageRead]:
    items, total = ticket_service.list_messages(session, company, ticket_id, limit=page.limit, offset=page.offset)
    return Page[MessageRead](
        items=[MessageRead.model_validate(m) for m in items], total=total, limit=page.limit, offset=page.offset
    )


@router.get(
    "/{ticket_id}/events",
    response_model=Page[EventRead],
    summary="Ticket change history in chronological order",
    responses=error_responses(404),
)
def list_ticket_events(
    ticket_id: uuid.UUID, session: SessionDep, company: CompanyDep, page: HistoryPaginationDep
) -> Page[EventRead]:
    items, total = ticket_service.list_events(session, company, ticket_id, limit=page.limit, offset=page.offset)
    return Page[EventRead](
        items=[EventRead.model_validate(e) for e in items], total=total, limit=page.limit, offset=page.offset
    )
