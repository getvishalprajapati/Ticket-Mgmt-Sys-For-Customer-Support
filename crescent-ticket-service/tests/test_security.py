"""API key protection, configuration safeguards and error-response hygiene."""

from __future__ import annotations

import logging
import re

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import TEST_API_KEY, assert_error

PROTECTED_REQUESTS = [
    ("GET", "/api/v1/company", None),
    ("GET", "/api/v1/customers", None),
    ("POST", "/api/v1/customers", {"name": "X", "phone_number": "+99900000002"}),
    ("GET", "/api/v1/agents", None),
    ("GET", "/api/v1/tickets", None),
    ("POST", "/api/v1/intake/messages", {"customer_name": "X", "phone_number": "+99900000003", "message_text": "hi"}),
]


@pytest.mark.parametrize(("method", "path", "body"), PROTECTED_REQUESTS)
def test_missing_api_key_is_rejected(api, anonymous_client, db, method, path, body):
    response = anonymous_client.request(method, path, json=body)
    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["WWW-Authenticate"] == "ApiKey"
    assert db.count("customers") == 0


@pytest.mark.parametrize("bad_key", ["wrong-key", TEST_API_KEY + "x", TEST_API_KEY.upper(), " "])
def test_invalid_api_key_is_rejected_without_echoing_it(api, anonymous_client, db, bad_key, caplog):
    caplog.set_level(logging.DEBUG)
    response = anonymous_client.post(
        "/api/v1/customers",
        json={"name": "Intruder", "phone_number": "+99900000004"},
        headers={"X-API-Key": bad_key},
    )
    assert_error(response, 401, "UNAUTHORIZED")
    if bad_key.strip():
        assert bad_key not in response.text
        assert bad_key not in caplog.text
    assert TEST_API_KEY not in response.text and TEST_API_KEY not in caplog.text
    assert db.count("customers") == 0


def test_valid_api_key_is_accepted(api, anonymous_client):
    assert anonymous_client.get("/api/v1/company", headers={"X-API-Key": TEST_API_KEY}).status_code == 200


def test_health_and_docs_do_not_require_a_key(app, anonymous_client):
    assert anonymous_client.get("/health").json()["status"] == "ok"
    assert anonymous_client.get("/docs").status_code == 200
    schema = anonymous_client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey",
        "description": "Shared internal API key configured through the API_KEY environment variable.",
        "in": "header",
        "name": "X-API-Key",
    }
    assert "/api/v1/intake/messages" in schema["paths"]


def test_unknown_routes_use_the_standard_error_format(api):
    assert_error(api.get("/api/v1/does-not-exist"), 404, "NOT_FOUND")
    assert_error(api.delete("/api/v1/customers"), 405, "METHOD_NOT_ALLOWED")


def test_malformed_json_is_a_validation_error(api):
    response = api.post("/api/v1/customers", content=b"{not json", headers={"Content-Type": "application/json"})
    assert_error(response, 422, "VALIDATION_ERROR")


# --- configuration safeguards -------------------------------------------------------------

LOCAL_URL = "postgresql+psycopg2://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable"


def settings(**values):
    return Settings(_env_file=None, **{"database_url": LOCAL_URL, "api_key": TEST_API_KEY, **values})


def test_valid_local_settings():
    s = settings()
    assert s.sqlalchemy_url == LOCAL_URL
    assert "postgres:postgres" not in repr(s)  # secrets are masked in reprs and logs
    assert TEST_API_KEY not in repr(s)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"api_key": "replace-with-a-long-random-api-key"}, "placeholder"),
        ({"api_key": "short"}, "at least 16"),
        ({"database_url": "postgresql+psycopg2://u:p@db.example.com:5432/postgres"}, "sslmode=require"),
        ({"database_url": "postgresql+psycopg2://u:p@db.example.com:5432/postgres?sslmode=disable"}, "sslmode"),
        ({"database_url": "sqlite:///tickets.db"}, "postgresql+psycopg2"),
        ({"database_url": "postgresql+asyncpg://u:p@127.0.0.1/postgres"}, "postgresql+psycopg2"),
        ({"database_url": "not a url"}, "valid SQLAlchemy"),
        ({"db_pool_size": 0}, "greater than or equal to 1"),
    ],
)
def test_unsafe_settings_are_rejected(values, message):
    with pytest.raises(ValidationError, match=re.escape(message)):
        settings(**values)


def test_remote_database_with_ssl_is_accepted():
    s = settings(database_url="postgresql+psycopg2://u:p@db.example.com:5432/postgres?sslmode=require")
    assert "db.example.com" in s.sqlalchemy_url


def test_missing_required_settings(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)
    missing = {error["loc"][0] for error in excinfo.value.errors()}
    assert missing == {"database_url", "api_key"}
