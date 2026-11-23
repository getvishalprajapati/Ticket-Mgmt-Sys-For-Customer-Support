from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        # One customer per normalized phone number within a company.
        UniqueConstraint("company_id", "phone_number"),
        # Target of composite foreign keys that keep tickets inside one company.
        UniqueConstraint("id", "company_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Stored normalized as "+" followed by 8-15 digits (E.164 style).
    phone_number: Mapped[str] = mapped_column(String(16), nullable=False)
