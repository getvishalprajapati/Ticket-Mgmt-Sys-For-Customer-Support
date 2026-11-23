from __future__ import annotations

import uuid

from pydantic import Field

from app.models.enums import MessageSource, SenderType, TicketEventType, TicketPriority, TicketStatus
from app.schemas.agent import AgentSummary
from app.schemas.common import RequestModel, ResponseModel, UTCDateTime
from app.schemas.customer import CustomerSummary


class TicketCreate(RequestModel):
    customer_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=200, examples=["Car service delayed"])
    description: str = Field(min_length=1, max_length=5000, examples=["My car service is delayed by two days."])
    priority: TicketPriority = TicketPriority.MEDIUM


class TicketAssign(RequestModel):
    agent_id: uuid.UUID


class TicketStatusUpdate(RequestModel):
    status: TicketStatus = Field(description="Allowed transitions: OPEN -> IN_PROGRESS -> RESOLVED")


class TicketRead(ResponseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    customer_id: uuid.UUID
    assigned_agent_id: uuid.UUID | None
    subject: str
    description: str
    priority: TicketPriority
    status: TicketStatus
    created_at: UTCDateTime
    updated_at: UTCDateTime
    resolved_at: UTCDateTime | None


class TicketDetail(TicketRead):
    customer: CustomerSummary
    assigned_agent: AgentSummary | None


class MessageCreate(RequestModel):
    sender_type: SenderType = Field(
        description="CUSTOMER or AGENT for conversation messages, INTERNAL for private support notes"
    )
    message_text: str = Field(min_length=1, max_length=4096)


class MessageRead(ResponseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    external_message_id: str | None
    source: MessageSource
    sender_type: SenderType
    message_text: str
    created_at: UTCDateTime


class EventRead(ResponseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    event_type: TicketEventType
    previous_value: str | None
    new_value: str | None
    created_at: UTCDateTime
