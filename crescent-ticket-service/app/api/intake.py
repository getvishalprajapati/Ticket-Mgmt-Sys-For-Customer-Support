from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import CompanyDep, SessionDep
from app.schemas.common import error_responses
from app.schemas.intake import IntakeMessageCreate, IntakeMessageResult
from app.services import intake_service

router = APIRouter(prefix="/intake", tags=["intake"])


@router.post(
    "/messages",
    status_code=201,
    response_model=IntakeMessageResult,
    summary="Simulate an inbound customer message",
    responses={
        200: {"model": IntakeMessageResult, "description": "Duplicate external_message_id: already processed"},
        **error_responses(409),
    },
)
def receive_message(
    data: IntakeMessageCreate, response: Response, session: SessionDep, company: CompanyDep
) -> IntakeMessageResult:
    """Find or create the customer, reuse their active ticket or open a new one, and store the message.

    Returns **201** when the message was stored, **200** when the same
    `external_message_id` was already processed (nothing is written twice).
    """
    outcome = intake_service.process_inbound_message(session, company, data)
    if outcome.duplicate:
        response.status_code = 200
    return IntakeMessageResult(
        ticket_id=outcome.ticket.id,
        customer_id=outcome.customer.id,
        message_id=outcome.message.id,
        ticket_status=outcome.ticket.status,
        new_ticket_created=outcome.new_ticket_created,
        customer_created=outcome.customer_created,
        duplicate=outcome.duplicate,
    )
