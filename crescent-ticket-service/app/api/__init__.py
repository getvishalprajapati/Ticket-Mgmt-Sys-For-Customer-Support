"""HTTP routes. Every business route lives under /api/v1 and requires the X-API-Key header."""

from fastapi import APIRouter, Depends

from app.api import agents, company, customers, intake, tickets
from app.core.security import require_api_key
from app.schemas.common import error_responses

api_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_api_key)],
    responses=error_responses(401, 422, 503),
)
for module in (company, customers, agents, tickets, intake):
    api_router.include_router(module.router)
