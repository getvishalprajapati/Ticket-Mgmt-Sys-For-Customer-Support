from __future__ import annotations

import uuid

from app.schemas.common import ResponseModel, UTCDateTime


class CompanyRead(ResponseModel):
    id: uuid.UUID
    name: str
    created_at: UTCDateTime
    updated_at: UTCDateTime
