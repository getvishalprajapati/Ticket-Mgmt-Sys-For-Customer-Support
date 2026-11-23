from __future__ import annotations

import uuid
from datetime import UTC, datetime

from typing import Any

from sqlalchemy import DateTime, MetaData, event, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Mapper, mapped_column

# Deterministic constraint names keep Alembic migrations stable and readable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Timezone-aware current time with microsecond precision."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, server_default=func.now()
    )


@event.listens_for(Base, "before_insert", propagate=True)
def _stamp_new_row(_mapper: Mapper[Any], _connection: Any, target: Any) -> None:
    """Give created_at and updated_at the same instant on insert.

    Separate column defaults would be evaluated microseconds apart, leaving
    updated_at earlier than created_at.
    """
    now = utcnow()
    if getattr(target, "created_at", None) is None and hasattr(target, "created_at"):
        target.created_at = now
    if getattr(target, "updated_at", None) is None and hasattr(target, "updated_at"):
        target.updated_at = now
