"""Initial schema: companies, customers, agents, tickets, ticket_messages, ticket_events.

Revision ID: 0001
Revises:
Create Date: 2026-11-21

Constraint names are wrapped in op.f() ("final"): they are already complete and
must not be passed through the metadata naming convention a second time.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("name", name=op.f("uq_companies_name")),
    )

    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phone_number", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_customers_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("company_id", "phone_number", name=op.f("uq_customers_company_id_phone_number")),
        sa.UniqueConstraint("id", "company_id", name=op.f("uq_customers_id_company_id")),
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_agents_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("company_id", "email", name=op.f("uq_agents_company_id_email")),
        sa.UniqueConstraint("id", "company_id", name=op.f("uq_agents_id_company_id")),
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_agent_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=10), server_default="MEDIUM", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="OPEN", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_tickets_company_id_companies"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "company_id"],
            ["customers.id", "customers.company_id"],
            name=op.f("fk_tickets_customer_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_agent_id", "company_id"],
            ["agents.id", "agents.company_id"],
            name=op.f("fk_tickets_agent_company"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name=op.f("uq_tickets_id_company_id")),
        sa.CheckConstraint("status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED')", name=op.f("ck_tickets_status_valid")),
        sa.CheckConstraint("priority IN ('LOW', 'MEDIUM', 'HIGH')", name=op.f("ck_tickets_priority_valid")),
        sa.CheckConstraint(
            "(status = 'RESOLVED') = (resolved_at IS NOT NULL)", name=op.f("ck_tickets_resolved_at_matches_status")
        ),
    )
    op.create_index(
        op.f("uq_tickets_one_active_per_customer"),
        "tickets",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('OPEN', 'IN_PROGRESS')"),
    )
    op.create_index(op.f("ix_tickets_company_status_created"), "tickets", ["company_id", "status", "created_at"])
    op.create_index(op.f("ix_tickets_company_priority"), "tickets", ["company_id", "priority"])
    op.create_index(op.f("ix_tickets_customer_created"), "tickets", ["customer_id", "created_at"])
    op.create_index(op.f("ix_tickets_assigned_agent"), "tickets", ["assigned_agent_id"])

    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("external_message_id", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("sender_type", sa.String(length=20), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_messages")),
        sa.ForeignKeyConstraint(
            ["ticket_id", "company_id"],
            ["tickets.id", "tickets.company_id"],
            name=op.f("fk_ticket_messages_ticket_company"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "sender_type IN ('CUSTOMER', 'AGENT', 'INTERNAL')", name=op.f("ck_ticket_messages_sender_type_valid")
        ),
        sa.CheckConstraint("source IN ('API', 'SIMULATED')", name=op.f("ck_ticket_messages_source_valid")),
        sa.CheckConstraint(
            "external_message_id IS NULL OR length(external_message_id) > 0",
            name=op.f("ck_ticket_messages_external_message_id_not_empty"),
        ),
    )
    op.create_index(
        op.f("uq_ticket_messages_company_source_external_id"),
        "ticket_messages",
        ["company_id", "source", "external_message_id"],
        unique=True,
        postgresql_where=sa.text("external_message_id IS NOT NULL"),
    )
    op.create_index(op.f("ix_ticket_messages_ticket_created"), "ticket_messages", ["ticket_id", "created_at"])

    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("previous_value", sa.String(length=200), nullable=True),
        sa.Column("new_value", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_events")),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_events_ticket_id_tickets"), ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "event_type IN ('TICKET_CREATED', 'AGENT_ASSIGNED', 'STATUS_CHANGED', 'TICKET_RESOLVED')",
            name=op.f("ck_ticket_events_event_type_valid"),
        ),
    )
    op.create_index(op.f("ix_ticket_events_ticket_created"), "ticket_events", ["ticket_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ticket_events")
    op.drop_table("ticket_messages")
    op.drop_table("tickets")
    op.drop_table("agents")
    op.drop_table("customers")
    op.drop_table("companies")
