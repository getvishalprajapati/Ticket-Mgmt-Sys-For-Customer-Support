"""API-key protection for the internal business API.

This is an initial internal-service safeguard (shared secret between trusted
services), not an end-user authentication system. See README "Limitations".
"""

from __future__ import annotations

import secrets

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from app.core.errors import AppError

API_KEY_HEADER_NAME = "X-API-Key"

api_key_header = APIKeyHeader(
    name=API_KEY_HEADER_NAME,
    auto_error=False,  # missing keys are reported with the standard error format below
    description="Shared internal API key configured through the API_KEY environment variable.",
)


def require_api_key(request: Request, api_key: str | None = Security(api_key_header)) -> None:
    expected = request.app.state.settings.api_key.get_secret_value()
    # compare_digest avoids leaking the key through response timing.
    if not api_key or not secrets.compare_digest(api_key.encode("utf-8"), expected.encode("utf-8")):
        raise AppError(
            401,
            "UNAUTHORIZED",
            "Missing or invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
