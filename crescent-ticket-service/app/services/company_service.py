from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import ServiceUnavailableError
from app.models import Company
from app.repositories import company_repository


def get_configured_company(session: Session, company_name: str) -> Company:
    """Version 1 serves exactly one company, selected by the COMPANY_NAME setting."""
    company = company_repository.get_by_name(session, company_name)
    if company is None:
        raise ServiceUnavailableError(
            "COMPANY_NOT_CONFIGURED",
            "The configured company does not exist in the database. Run the database migrations.",
        )
    return company
