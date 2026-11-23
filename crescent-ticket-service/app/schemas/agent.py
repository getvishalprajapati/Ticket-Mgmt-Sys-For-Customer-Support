from __future__ import annotations

import uuid

from pydantic import Field, field_validator

from app.schemas.common import RequestModel, ResponseModel, UTCDateTime
from app.schemas.validators import normalize_email


class AgentCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200, examples=["Demo Agent"])
    email: str = Field(min_length=3, max_length=320, examples=["agent.demo@example.com"])
    is_active: bool = Field(default=True, description="Only active agents can be assigned to tickets")

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class AgentRead(ResponseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    email: str
    is_active: bool
    created_at: UTCDateTime
    updated_at: UTCDateTime


class AgentSummary(ResponseModel):
    id: uuid.UUID
    name: str
    email: str
    is_active: bool
