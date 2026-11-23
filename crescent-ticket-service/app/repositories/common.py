from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def paginate(session: Session, statement: Select[Any], *, limit: int, offset: int) -> tuple[list[Any], int]:
    """Run a SELECT with LIMIT/OFFSET and return (rows, total matching rows)."""
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    items = list(session.scalars(statement.limit(limit).offset(offset)))
    return items, int(total)
