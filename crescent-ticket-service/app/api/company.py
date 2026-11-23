from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CompanyDep
from app.schemas.common import error_responses
from app.schemas.company import CompanyRead

router = APIRouter(prefix="/company", tags=["company"])


@router.get("", response_model=CompanyRead, summary="Get the configured company", responses=error_responses(503))
def get_company(company: CompanyDep) -> CompanyRead:
    return CompanyRead.model_validate(company)
