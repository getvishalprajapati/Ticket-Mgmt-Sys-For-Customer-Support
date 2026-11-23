from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models import Agent, Company
from app.repositories import agent_repository
from app.schemas.agent import AgentCreate


def _duplicate() -> ConflictError:
    return ConflictError("DUPLICATE_AGENT", "An agent with this email address already exists")


def create_agent(session: Session, company: Company, data: AgentCreate) -> Agent:
    if agent_repository.get_by_email(session, company.id, data.email) is not None:
        raise _duplicate()
    agent = Agent(company_id=company.id, name=data.name, email=data.email, is_active=data.is_active)
    try:
        agent_repository.add(session, agent)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise _duplicate() from exc
    return agent


def list_agents(
    session: Session,
    company: Company,
    *,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[Agent], int]:
    return agent_repository.list_agents(session, company.id, is_active=is_active, limit=limit, offset=offset)
