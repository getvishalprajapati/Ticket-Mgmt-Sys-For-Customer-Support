"""Test fixtures.

The suite runs against a real PGlite PostgreSQL database:

* a dedicated PGlite server is started for the test session with its own data
  directory (database/pgdata/test, wiped at the start of every session) on an
  OS-assigned free port; the application database is never used;
* the schema is created with the real Alembic migrations;
* every test that uses the ``api`` fixture starts from empty tables (only the
  seeded Crescent Motors company remains).
"""

from __future__ import annotations

import itertools
import shutil
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.config import Settings
from app.main import create_app
from tests.pglite_server import DATABASE_DIR, PROJECT_ROOT, PGliteServer

TEST_API_KEY = "test-api-key-not-a-real-secret-0123456789"
TEST_DATA_DIR = DATABASE_DIR / "pgdata" / "test"
COMPANY_NAME = "Crescent Motors"


# --- configuration helpers ---------------------------------------------------------


def make_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": database_url,
        "api_key": TEST_API_KEY,
        "app_env": "test",
        "log_level": "WARNING",
        "company_name": COMPANY_NAME,
        "db_pool_size": 1,
        "db_max_overflow": 0,
        "db_pool_timeout_seconds": 10,
        "db_connect_timeout_seconds": 5,
    }
    values.update(overrides)
    # _env_file=None: the developer's .env must never influence the tests.
    return Settings(_env_file=None, **values)


def alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


def _reset_test_data_dir() -> None:
    # Safety net: this function may only ever delete database/pgdata/test.
    assert TEST_DATA_DIR.name == "test" and TEST_DATA_DIR.parent.name == "pgdata"
    assert TEST_DATA_DIR.parent.parent == DATABASE_DIR
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
    TEST_DATA_DIR.with_name("test.lock").unlink(missing_ok=True)


# --- database ------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pglite_server() -> Iterator[PGliteServer]:
    _reset_test_data_dir()
    server = PGliteServer(TEST_DATA_DIR).start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="session")
def migrated_database(pglite_server: PGliteServer) -> PGliteServer:
    command.upgrade(alembic_config(pglite_server.url), "head")
    return pglite_server


@pytest.fixture(scope="session")
def app(migrated_database: PGliteServer) -> Iterator[FastAPI]:
    application = create_app(make_settings(migrated_database.url))
    yield application
    application.state.engine.dispose()


@pytest.fixture(scope="session")
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers={"X-API-Key": TEST_API_KEY}) as test_client:
        yield test_client


class Database:
    """Direct SQL access for assertions on real rows (shares the app's connection pool)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [dict(row._mapping) for row in connection.execute(text(sql), params)]

    def one(self, sql: str, **params: Any) -> dict[str, Any]:
        rows = self.rows(sql, **params)
        assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
        return rows[0]

    def scalar(self, sql: str, **params: Any) -> Any:
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar()

    def count(self, table: str, where: str = "true", **params: Any) -> int:
        assert table.isidentifier()
        return int(self.scalar(f"SELECT count(*) FROM {table} WHERE {where}", **params))

    def execute(self, sql: str, **params: Any) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(sql), params)


@pytest.fixture
def db(app: FastAPI) -> Database:
    return Database(app.state.engine)


@pytest.fixture
def api(client: TestClient, db: Database) -> TestClient:
    """Authenticated client on an empty database (the seeded company is kept)."""
    # DELETE (not TRUNCATE): TRUNCATE recreates table files, which is slow on
    # PGlite's emulated file system; the tables here only ever hold a few rows.
    with db.engine.begin() as connection:
        for table in ("ticket_events", "ticket_messages", "tickets", "agents", "customers"):
            connection.execute(text(f"DELETE FROM {table}"))
        connection.execute(text("DELETE FROM companies WHERE name <> :name"), {"name": COMPANY_NAME})
    return client


@pytest.fixture
def anonymous_client(app: FastAPI) -> TestClient:
    """Client without the API key header."""
    return TestClient(app)


# --- record factories (through the public API) ---------------------------------------

_sequence = itertools.count(1)


def unique_phone() -> str:
    # +999 is not an assigned country calling code: these numbers are fictional.
    return f"+999{next(_sequence):08d}"


@pytest.fixture
def make_customer(api: TestClient) -> Callable[..., dict[str, Any]]:
    def _make(name: str | None = None, phone_number: str | None = None) -> dict[str, Any]:
        n = next(_sequence)
        response = api.post(
            "/api/v1/customers",
            json={"name": name or f"Test Customer {n}", "phone_number": phone_number or unique_phone()},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture
def make_agent(api: TestClient) -> Callable[..., dict[str, Any]]:
    def _make(name: str | None = None, email: str | None = None, is_active: bool = True) -> dict[str, Any]:
        n = next(_sequence)
        response = api.post(
            "/api/v1/agents",
            json={"name": name or f"Test Agent {n}", "email": email or f"agent{n}@example.com", "is_active": is_active},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture
def make_ticket(api: TestClient, make_customer: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def _make(customer_id: str | None = None, **fields: Any) -> dict[str, Any]:
        body = {
            "customer_id": customer_id or make_customer()["id"],
            "subject": fields.pop("subject", "Service appointment delayed"),
            "description": fields.pop("description", "The car was not ready on the promised date."),
            **fields,
        }
        response = api.post("/api/v1/tickets", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return _make


def assert_error(response: Any, status_code: int, code: str) -> dict[str, Any]:
    """Assert the standard error envelope and return its body."""
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error"}, body
    assert body["error"]["code"] == code, body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    return body["error"]
