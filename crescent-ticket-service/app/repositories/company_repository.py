from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company


def get_by_name(session: Session, name: str) -> Company | None:
    return session.scalar(select(Company).where(Company.name == name))
