from __future__ import annotations

import uuid

from pydantic import Field, field_validator

from app.schemas.common import RequestModel, ResponseModel, UTCDateTime
from app.schemas.validators import normalize_phone_number


class CustomerCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200, examples=["Demo Customer"])
    phone_number: str = Field(
        min_length=1,
        max_length=32,
        description="International format including the country code. Stored normalized (e.g. +19999999999).",
        examples=["+19999999999"],
    )

    @field_validator("phone_number")
    @classmethod
    def _normalize_phone(cls, value: str) -> str:
        return normalize_phone_number(value)


class CustomerRead(ResponseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    phone_number: str
    created_at: UTCDateTime
    updated_at: UTCDateTime


class CustomerSummary(ResponseModel):
    id: uuid.UUID
    name: str
    phone_number: str
