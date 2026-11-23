from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent
from app.repositories.common import paginate


def get(session: Session, company_id: uuid.UUID, agent_id: uuid.UUID) -> Agent | None:
    return session.scalar(select(Agent).where(Agent.company_id == company_id, Agent.id == agent_id))


def get_by_email(session: Session, company_id: uuid.UUID, email: str) -> Agent | None:
    return session.scalar(select(Agent).where(Agent.company_id == company_id, Agent.email == email))


def list_agents(
    session: Session,
    company_id: uuid.UUID,
    *,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[Agent], int]:
    statement = select(Agent).where(Agent.company_id == company_id)
    if is_active is not None:
        statement = statement.where(Agent.is_active.is_(is_active))
    statement = statement.order_by(Agent.name, Agent.id)
    return paginate(session, statement, limit=limit, offset=offset)


def add(session: Session, agent: Agent) -> Agent:
    session.add(agent)
    session.flush()
    return agent
