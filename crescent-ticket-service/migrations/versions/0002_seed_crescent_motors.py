"""Seed the Crescent Motors company (the only company served by Version 1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed identifier so every environment (local, test, future Supabase) agrees on it.
CRESCENT_MOTORS_ID = uuid.UUID("c2e5c3a0-7d1b-4b5e-9a6f-1c0de5c00001")
CRESCENT_MOTORS_NAME = "Crescent Motors"

companies = sa.table(
    "companies",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
)


def upgrade() -> None:
    op.execute(
        postgresql.insert(companies)
        .values(id=CRESCENT_MOTORS_ID, name=CRESCENT_MOTORS_NAME)
        .on_conflict_do_nothing(index_elements=["name"])
    )


def downgrade() -> None:
    op.execute(companies.delete().where(companies.c.id == CRESCENT_MOTORS_ID))
