from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CompanyDep, ListPaginationDep, SessionDep
from app.schemas.agent import AgentCreate, AgentRead
from app.schemas.common import Page, error_responses
from app.services import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post(
    "",
    status_code=201,
    response_model=AgentRead,
    summary="Create a human support agent",
    responses=error_responses(409),
)
def create_agent(data: AgentCreate, session: SessionDep, company: CompanyDep) -> AgentRead:
    return AgentRead.model_validate(agent_service.create_agent(session, company, data))


@router.get("", response_model=Page[AgentRead], summary="List support agents")
def list_agents(
    session: SessionDep,
    company: CompanyDep,
    page: ListPaginationDep,
    is_active: bool | None = None,
) -> Page[AgentRead]:
    items, total = agent_service.list_agents(
        session, company, is_active=is_active, limit=page.limit, offset=page.offset
    )
    return Page[AgentRead](
        items=[AgentRead.model_validate(a) for a in items], total=total, limit=page.limit, offset=page.offset
    )
