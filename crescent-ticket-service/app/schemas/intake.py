from __future__ import annotations

import uuid

from pydantic import Field, field_validator

from app.models.enums import TicketStatus
from app.schemas.common import RequestModel, ResponseModel
from app.schemas.validators import normalize_phone_number


class IntakeMessageCreate(RequestModel):
    """A simulated inbound customer message (future integration point for a WhatsApp service)."""

    customer_name: str = Field(
        min_length=1,
        max_length=200,
        description="Used only when the phone number belongs to a new customer; existing names are not overwritten.",
        examples=["Demo Customer"],
    )
    phone_number: str = Field(min_length=1, max_length=32, examples=["+19999999999"])
    message_text: str = Field(min_length=1, max_length=4096, examples=["My car service is delayed"])
    external_message_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[\x21-\x7E]+$",
        description="Identifier from the sending system. Repeated submissions with the same id are processed once.",
        examples=["demo-msg-001"],
    )

    @field_validator("phone_number")
    @classmethod
    def _normalize_phone(cls, value: str) -> str:
        return normalize_phone_number(value)


class IntakeMessageResult(ResponseModel):
    ticket_id: uuid.UUID
    customer_id: uuid.UUID
    message_id: uuid.UUID
    ticket_status: TicketStatus
    new_ticket_created: bool = Field(description="True when this request opened a new ticket")
    customer_created: bool = Field(description="True when this request created the customer")
    duplicate: bool = Field(description="True when the external_message_id was already processed; nothing was written")
