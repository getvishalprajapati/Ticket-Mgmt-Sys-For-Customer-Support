"""Simulated inbound customer messages.

This is the integration point a future WhatsApp webhook microservice will call.
Processing of one message is a single database transaction: the customer, the
ticket, its TICKET_CREATED event and the message are committed together or not
at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import Company, Customer, Ticket, TicketMessage
from app.models.base import utcnow
from app.models.enums import MessageSource, SenderType, TicketPriority
from app.repositories import customer_repository, ticket_repository
from app.schemas.intake import IntakeMessageCreate
from app.services import ticket_service

logger = logging.getLogger("crescent.intake")

INTAKE_SOURCE = MessageSource.SIMULATED
SUBJECT_MAX_LENGTH = 120


@dataclass(frozen=True)
class IntakeOutcome:
    ticket: Ticket
    customer: Customer
    message: TicketMessage
    new_ticket_created: bool
    customer_created: bool
    duplicate: bool


def subject_from_message(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= SUBJECT_MAX_LENGTH:
        return collapsed
    return collapsed[: SUBJECT_MAX_LENGTH - 3].rstrip() + "..."


def process_inbound_message(session: Session, company: Company, data: IntakeMessageCreate) -> IntakeOutcome:
    # Unique constraints are the final guard against concurrent duplicates (same
    # phone number, same active ticket, same external message id). If one fires,
    # the transaction is rolled back and processed once more, which then finds
    # the rows committed by the other request.
    for attempt in (1, 2):
        try:
            return _process(session, company, data)
        except IntegrityError as exc:
            session.rollback()
            logger.info("Intake attempt %s hit a uniqueness conflict, retrying", attempt)
            if attempt == 2:
                raise ConflictError(
                    "INTAKE_CONFLICT", "The message conflicted with a concurrent update; retry the request"
                ) from exc
    raise AssertionError("unreachable")


def _process(session: Session, company: Company, data: IntakeMessageCreate) -> IntakeOutcome:
    if data.external_message_id is not None:
        replay = _find_processed(session, company, data)
        if replay is not None:
            return replay

    customer = customer_repository.get_by_phone(session, company.id, data.phone_number)
    customer_created = customer is None
    if customer is None:
        customer = customer_repository.add(
            session, Customer(company_id=company.id, name=data.customer_name, phone_number=data.phone_number)
        )

    ticket = ticket_repository.get_active_for_customer(session, company.id, customer.id, for_update=True)
    new_ticket_created = ticket is None
    if ticket is None:
        ticket = ticket_service.new_ticket(
            session,
            company,
            customer_id=customer.id,
            subject=subject_from_message(data.message_text),
            description=data.message_text,
            priority=TicketPriority.MEDIUM.value,
        )
    else:
        ticket.updated_at = utcnow()

    message = ticket_repository.add_message(
        session,
        TicketMessage(
            ticket_id=ticket.id,
            company_id=company.id,
            external_message_id=data.external_message_id,
            source=INTAKE_SOURCE.value,
            sender_type=SenderType.CUSTOMER.value,
            message_text=data.message_text,
        ),
    )
    session.commit()
    return IntakeOutcome(
        ticket=ticket,
        customer=customer,
        message=message,
        new_ticket_created=new_ticket_created,
        customer_created=customer_created,
        duplicate=False,
    )


def _find_processed(session: Session, company: Company, data: IntakeMessageCreate) -> IntakeOutcome | None:
    assert data.external_message_id is not None
    message = ticket_repository.get_message_by_external_id(
        session, company.id, INTAKE_SOURCE.value, data.external_message_id
    )
    if message is None:
        return None
    ticket = ticket_repository.get(session, company.id, message.ticket_id)
    assert ticket is not None  # guaranteed by the foreign key
    customer = customer_repository.get(session, company.id, ticket.customer_id)
    assert customer is not None
    if customer.phone_number != data.phone_number or message.message_text != data.message_text:
        raise ConflictError(
            "EXTERNAL_MESSAGE_ID_CONFLICT",
            "This external_message_id was already used for a different message",
            details={"external_message_id": data.external_message_id},
        )
    session.commit()  # read-only path: nothing was written, just end the transaction
    return IntakeOutcome(
        ticket=ticket,
        customer=customer,
        message=message,
        new_ticket_created=False,
        customer_created=False,
        duplicate=True,
    )
