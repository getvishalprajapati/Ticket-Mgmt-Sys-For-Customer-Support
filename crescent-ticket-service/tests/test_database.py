"""PGlite connectivity, Alembic migrations, persistence and database failure handling."""

from __future__ import annotations

import socket
import subprocess

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.main import create_app
from tests.conftest import TEST_API_KEY, alembic_config, assert_error, make_settings
from tests.pglite_server import DATABASE_DIR, PROJECT_ROOT, START_SCRIPT, PGliteServer, PGliteStartError

EXPECTED_TABLES = {"companies", "customers", "agents", "tickets", "ticket_messages", "ticket_events", "alembic_version"}
HEAD = ScriptDirectory(str(PROJECT_ROOT / "migrations")).get_current_head()


@pytest.fixture
def fresh_server():
    """A throwaway in-memory PGlite server with an empty database."""
    with PGliteServer("memory://") as server:
        yield server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- driver / server -------------------------------------------------------------------


def test_python_driver_connects_to_pglite_without_ssl(app, migrated_database):
    engine = app.state.engine
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg2"
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version()")).scalar()
        assert "PGlite" in version
        assert connection.connection.dbapi_connection.info.ssl_in_use is False
        # Parameterised query round trip through SQLAlchemy
        assert connection.execute(text("SELECT CAST(:value AS integer) + 1"), {"value": 41}).scalar() == 42


def test_test_database_is_isolated_from_the_application_database(migrated_database):
    assert migrated_database.data_dir.replace("\\", "/").endswith("database/pgdata/test")
    assert migrated_database.port != 55432  # application database port from .env.example


# --- migrations --------------------------------------------------------------------------


def test_migrations_create_the_expected_schema(app, migrated_database):
    engine = app.state.engine
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert set(inspector.get_table_names()) == EXPECTED_TABLES
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD
        assert connection.execute(text("SELECT name FROM companies")).scalars().all() == ["Crescent Motors"]

        ticket_indexes = {ix["name"]: ix for ix in inspector.get_indexes("tickets")}
        active = ticket_indexes["uq_tickets_one_active_per_customer"]
        assert active["unique"] and active["column_names"] == ["customer_id"]
        assert "IN_PROGRESS" in active["dialect_options"]["postgresql_where"]

        message_indexes = {ix["name"]: ix for ix in inspector.get_indexes("ticket_messages")}
        dedupe = message_indexes["uq_ticket_messages_company_source_external_id"]
        assert dedupe["unique"] and dedupe["column_names"] == ["company_id", "source", "external_message_id"]

        ticket_fks = {fk["name"]: fk for fk in inspector.get_foreign_keys("tickets")}
        assert ticket_fks["fk_tickets_agent_company"]["constrained_columns"] == ["assigned_agent_id", "company_id"]
        assert ticket_fks["fk_tickets_customer_company"]["constrained_columns"] == ["customer_id", "company_id"]

        checks = {ck["name"] for ck in inspector.get_check_constraints("tickets")}
        assert {"ck_tickets_status_valid", "ck_tickets_priority_valid", "ck_tickets_resolved_at_matches_status"} <= checks

        created_at = next(c for c in inspector.get_columns("tickets") if c["name"] == "created_at")
        assert created_at["type"].timezone is True


def test_models_match_migrations(migrated_database):
    """Alembic autogenerate finds no difference between the ORM models and the migrated schema."""
    command.check(alembic_config(migrated_database.url))


def test_migrations_downgrade_and_upgrade_round_trip(fresh_server):
    config = alembic_config(fresh_server.url)
    engine = create_engine(fresh_server.url, pool_size=1, max_overflow=0)
    try:
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == EXPECTED_TABLES

        command.downgrade(config, "0001")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM companies")).scalar() == 0

        command.downgrade(config, "base")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}

        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == EXPECTED_TABLES
            assert connection.execute(text("SELECT name FROM companies")).scalar() == "Crescent Motors"
    finally:
        engine.dispose()


# --- persistence ---------------------------------------------------------------------------


def test_records_persist_across_database_restart(tmp_path):
    data_dir = tmp_path / "pgdata"

    with PGliteServer(data_dir) as server:
        command.upgrade(alembic_config(server.url), "head")
        application = create_app(make_settings(server.url))
        with TestClient(application, headers={"X-API-Key": TEST_API_KEY}) as client:
            customer = client.post("/api/v1/customers", json={"name": "Persistent", "phone_number": "+99912345678"})
            assert customer.status_code == 201
            ticket = client.post(
                "/api/v1/tickets",
                json={"customer_id": customer.json()["id"], "subject": "Persist me", "description": "Across restarts"},
            )
            assert ticket.status_code == 201
        application.state.engine.dispose()
    assert server.process.returncode == 0, server.log  # graceful shutdown

    with PGliteServer(data_dir) as restarted:
        engine = create_engine(restarted.url, pool_size=1, max_overflow=0)
        try:
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT c.name, t.subject, t.status FROM tickets t JOIN customers c ON c.id = t.customer_id "
                        "WHERE t.id = :id"
                    ),
                    {"id": ticket.json()["id"]},
                ).one()
                assert tuple(row) == ("Persistent", "Persist me", "OPEN")
                assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD
        finally:
            engine.dispose()


def test_a_data_directory_cannot_be_opened_by_two_servers(tmp_path):
    data_dir = tmp_path / "locked"
    with PGliteServer(data_dir):
        second = PGliteServer(data_dir)
        with pytest.raises(PGliteStartError, match="already in use"):
            second.start(timeout=30)


def test_server_refuses_to_bind_to_a_public_address():
    result = subprocess.run(
        ["node", str(START_SCRIPT), "--data-dir", "memory://", "--host", "0.0.0.0", "--port", "0"],
        cwd=DATABASE_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "Only localhost addresses are allowed" in result.stderr


# --- health and failure handling ---------------------------------------------------------


def test_readiness_reports_ready(api):
    response = api.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "migrations": "ok", "company": "ok"}}


def test_database_unavailable_is_reported_as_503():
    application = create_app(make_settings(f"postgresql+psycopg2://postgres@127.0.0.1:{_free_port()}/postgres?sslmode=disable"))
    with TestClient(application, headers={"X-API-Key": TEST_API_KEY}) as client:
        assert client.get("/health").status_code == 200  # liveness does not need the database

        ready = client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json()["status"] == "not_ready"
        assert ready.json()["checks"]["database"] == "unavailable"
        assert ready.json()["error"]["code"] == "DATABASE_UNAVAILABLE"

        assert_error(client.get("/api/v1/customers"), 503, "DATABASE_UNAVAILABLE")
        response = client.post("/api/v1/customers", json={"name": "Nobody", "phone_number": "+99900000001"})
        assert_error(response, 503, "DATABASE_UNAVAILABLE")
        assert "127.0.0.1" not in response.text  # connection details are not leaked
    application.state.engine.dispose()


def test_unmigrated_database_is_reported(fresh_server):
    application = create_app(make_settings(fresh_server.url))
    with TestClient(application, headers={"X-API-Key": TEST_API_KEY}) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json()["checks"] == {"database": "ok", "migrations": "pending", "company": "unknown"}
        assert_error(client.get("/api/v1/tickets"), 503, "DATABASE_NOT_MIGRATED")
    application.state.engine.dispose()


def test_api_recovers_after_database_restart(tmp_path):
    data_dir = tmp_path / "restart"
    server = PGliteServer(data_dir).start()
    command.upgrade(alembic_config(server.url), "head")
    port = server.port
    application = create_app(make_settings(server.url))
    with TestClient(application, headers={"X-API-Key": TEST_API_KEY}) as client:
        assert client.get("/api/v1/company").status_code == 200
        server.stop()
        assert_error(client.get("/api/v1/company"), 503, "DATABASE_UNAVAILABLE")

        restarted = PGliteServer(data_dir, port=port).start()
        try:
            # pool_pre_ping replaces the dead pooled connection transparently
            assert client.get("/api/v1/company").status_code == 200
        finally:
            restarted.stop()
    application.state.engine.dispose()
