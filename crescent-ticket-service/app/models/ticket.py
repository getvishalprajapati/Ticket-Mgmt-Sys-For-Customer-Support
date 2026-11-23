from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.agent import Agent
from app.models.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.customer import Customer
from app.models.enums import (
    MessageSource,
    SenderType,
    TicketEventType,
    TicketPriority,
    TicketStatus,
    sql_in_list,
)


class Ticket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        # The customer and the assigned agent must belong to the ticket's company.
        ForeignKeyConstraint(
            ["customer_id", "company_id"],
            ["customers.id", "customers.company_id"],
            name="fk_tickets_customer_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assigned_agent_id", "company_id"],
            ["agents.id", "agents.company_id"],
            name="fk_tickets_agent_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id"),
        CheckConstraint(f"status IN ({sql_in_list(TicketStatus)})", name="status_valid"),
        CheckConstraint(f"priority IN ({sql_in_list(TicketPriority)})", name="priority_valid"),
        # resolved_at is set exactly when the ticket is RESOLVED.
        CheckConstraint("(status = 'RESOLVED') = (resolved_at IS NOT NULL)", name="resolved_at_matches_status"),
        # Version 1 policy: at most one active (OPEN / IN_PROGRESS) ticket per customer.
        Index(
            "uq_tickets_one_active_per_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("status IN ('OPEN', 'IN_PROGRESS')"),
        ),
        Index("ix_tickets_company_status_created", "company_id", "status", "created_at"),
        Index("ix_tickets_company_priority", "company_id", "priority"),
        Index("ix_tickets_customer_created", "customer_id", "created_at"),
        Index("ix_tickets_assigned_agent", "assigned_agent_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(
        String(10), nullable=False, default=TicketPriority.MEDIUM.value, server_default=TicketPriority.MEDIUM.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TicketStatus.OPEN.value, server_default=TicketStatus.OPEN.value
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Read-only conveniences for responses; writes always go through the id columns.
    customer: Mapped[Customer] = relationship(
        primaryjoin="Ticket.customer_id == Customer.id",
        foreign_keys=[customer_id],
        viewonly=True,
        lazy="raise",
    )
    assigned_agent: Mapped[Agent | None] = relationship(
        primaryjoin="Ticket.assigned_agent_id == Agent.id",
        foreign_keys=[assigned_agent_id],
        viewonly=True,
        lazy="raise",
    )


class TicketMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ticket_messages"
    __table_args__ = (
        # company_id is denormalised from the ticket (and kept consistent by this
        # composite key) so duplicate external messages can be rejected by a
        # database uniqueness rule scoped to company + source.
        ForeignKeyConstraint(
            ["ticket_id", "company_id"],
            ["tickets.id", "tickets.company_id"],
            name="fk_ticket_messages_ticket_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"sender_type IN ({sql_in_list(SenderType)})", name="sender_type_valid"),
        CheckConstraint(f"source IN ({sql_in_list(MessageSource)})", name="source_valid"),
        CheckConstraint(
            "external_message_id IS NULL OR length(external_message_id) > 0", name="external_message_id_not_empty"
        ),
        Index(
            "uq_ticket_messages_company_source_external_id",
            "company_id",
            "source",
            "external_message_id",
            unique=True,
            postgresql_where=text("external_message_id IS NOT NULL"),
        ),
        Index("ix_ticket_messages_ticket_created", "ticket_id", "created_at"),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)


class TicketEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ticket_events"
    __table_args__ = (
        CheckConstraint(f"event_type IN ({sql_in_list(TicketEventType)})", name="event_type_valid"),
        Index("ix_ticket_events_ticket_created", "ticket_id", "created_at"),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    previous_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
