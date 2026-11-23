"""Support agent creation and listing."""

from __future__ import annotations

from tests.conftest import assert_error


def test_create_agent_persists_row(api, db):
    response = api.post("/api/v1/agents", json={"name": "Asha Demo", "email": "  Asha.Demo@Example.COM "})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "asha.demo@example.com"
    assert body["is_active"] is True

    row = db.one("SELECT name, email, is_active FROM agents WHERE id = :id", id=body["id"])
    assert row == {"name": "Asha Demo", "email": "asha.demo@example.com", "is_active": True}


def test_create_inactive_agent(api, db):
    body = api.post("/api/v1/agents", json={"name": "Away", "email": "away@example.com", "is_active": False}).json()
    assert body["is_active"] is False
    assert db.scalar("SELECT is_active FROM agents WHERE id = :id", id=body["id"]) is False


def test_duplicate_agent_email_is_rejected_case_insensitively(api, db, make_agent):
    make_agent(email="duplicate@example.com")
    assert_error(
        api.post("/api/v1/agents", json={"name": "Copy", "email": "DUPLICATE@example.com"}), 409, "DUPLICATE_AGENT"
    )
    assert db.count("agents") == 1


def test_agent_validation_errors(api, db):
    for payload in (
        {"email": "missing.name@example.com"},
        {"name": "Missing email"},
        {"name": "Bad email", "email": "not-an-email"},
        {"name": "", "email": "empty.name@example.com"},
        {"name": "Bad flag", "email": "flag@example.com", "is_active": "sometimes"},
    ):
        assert_error(api.post("/api/v1/agents", json=payload), 422, "VALIDATION_ERROR")
    assert db.count("agents") == 0


def test_list_agents_with_active_filter_and_pagination(api, make_agent):
    active = [make_agent(name=f"Active {i}") for i in range(3)]
    inactive = make_agent(name="Inactive", is_active=False)

    everyone = api.get("/api/v1/agents").json()
    assert everyone["total"] == 4

    only_active = api.get("/api/v1/agents", params={"is_active": "true"}).json()
    assert sorted(a["id"] for a in only_active["items"]) == sorted(a["id"] for a in active)

    only_inactive = api.get("/api/v1/agents", params={"is_active": "false"}).json()
    assert [a["id"] for a in only_inactive["items"]] == [inactive["id"]]

    page = api.get("/api/v1/agents", params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    # Sorted by name: "Active 0", "Active 1", "Active 2", "Inactive"
    assert [a["name"] for a in page["items"]] == ["Active 1", "Active 2"]
