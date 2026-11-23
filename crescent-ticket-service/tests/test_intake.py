"""Simulated inbound customer messages (POST /api/v1/intake/messages)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.repositories import ticket_repository
from app.services import intake_service
from tests.conftest import TEST_API_KEY, assert_error, unique_phone

INTAKE = "/api/v1/intake/messages"


def intake(api, phone, text, external_id=None, name="Demo Customer"):
    payload = {"customer_name": name, "phone_number": phone, "message_text": text}
    if external_id is not None:
        payload["external_message_id"] = external_id
    return api.post(INTAKE, json=payload)


def test_first_message_creates_customer_ticket_and_message(api, db):
    phone = unique_phone()
    response = intake(api, phone, "My car service is delayed", "demo-msg-001")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["new_ticket_created"] is True
    assert body["customer_created"] is True
    assert body["duplicate"] is False
    assert body["ticket_status"] == "OPEN"

    customer = db.one("SELECT id, name, phone_number FROM customers")
    assert str(customer["id"]) == body["customer_id"]
    assert (customer["name"], customer["phone_number"]) == ("Demo Customer", phone)

    ticket = db.one("SELECT id, customer_id, status, priority, subject, description FROM tickets")
    assert str(ticket["id"]) == body["ticket_id"]
    assert ticket["customer_id"] == customer["id"]
    assert (ticket["status"], ticket["priority"]) == ("OPEN", "MEDIUM")
    assert ticket["subject"] == ticket["description"] == "My car service is delayed"

    message = db.one("SELECT id, ticket_id, external_message_id, source, sender_type, message_text FROM ticket_messages")
    assert str(message["id"]) == body["message_id"]
    assert message["ticket_id"] == ticket["id"]
    assert (message["external_message_id"], message["source"], message["sender_type"]) == (
        "demo-msg-001",
        "SIMULATED",
        "CUSTOMER",
    )
    assert db.scalar("SELECT event_type FROM ticket_events WHERE ticket_id = :t", t=ticket["id"]) == "TICKET_CREATED"


def test_long_message_produces_truncated_subject(api, db):
    text = "Engine   warning light\nkeeps coming on " + "and the car shakes " * 20
    intake(api, unique_phone(), text)
    subject, description = db.one("SELECT subject, description FROM tickets").values()
    assert len(subject) <= 120 and subject.endswith("...")
    assert subject.startswith("Engine warning light keeps coming on")
    assert description == text.strip()


def test_existing_customer_is_reused_and_not_renamed(api, db, make_customer):
    customer = make_customer(name="Original Name")
    formatted_phone = customer["phone_number"][:4] + " " + customer["phone_number"][4:]

    body = intake(api, formatted_phone, "Hello again", name="Different Name").json()

    assert body["customer_id"] == customer["id"]
    assert body["customer_created"] is False
    assert db.count("customers") == 1
    assert db.scalar("SELECT name FROM customers") == "Original Name"


def test_message_is_appended_to_the_active_ticket(api, db, make_agent):
    phone = unique_phone()
    first = intake(api, phone, "Car not ready", "wa-1").json()
    updated_before = db.scalar("SELECT updated_at FROM tickets")

    second = intake(api, phone, "Any update?", "wa-2")
    assert second.status_code == 201
    assert second.json()["ticket_id"] == first["ticket_id"]
    assert second.json()["new_ticket_created"] is False

    # Still reused when the ticket is IN_PROGRESS with an agent.
    api.patch(f"/api/v1/tickets/{first['ticket_id']}/assign", json={"agent_id": make_agent()["id"]})
    third = intake(api, phone, "Please call me", "wa-3").json()
    assert third["ticket_id"] == first["ticket_id"] and third["ticket_status"] == "IN_PROGRESS"

    assert db.count("tickets") == 1
    texts = [r["message_text"] for r in db.rows("SELECT message_text FROM ticket_messages ORDER BY created_at")]
    assert texts == ["Car not ready", "Any update?", "Please call me"]
    assert db.scalar("SELECT updated_at FROM tickets") > updated_before

    listing = api.get(f"/api/v1/tickets/{first['ticket_id']}/messages").json()
    assert [m["message_text"] for m in listing["items"]] == texts


def test_new_ticket_after_previous_ticket_is_resolved(api, db, make_agent):
    phone = unique_phone()
    first = intake(api, phone, "Service delayed", "wa-10").json()
    api.patch(f"/api/v1/tickets/{first['ticket_id']}/assign", json={"agent_id": make_agent()["id"]})
    assert api.patch(f"/api/v1/tickets/{first['ticket_id']}/status", json={"status": "RESOLVED"}).status_code == 200
    resolved_at = db.scalar("SELECT resolved_at FROM tickets WHERE id = :t", t=first["ticket_id"])

    second = intake(api, phone, "New problem: AC not cooling", "wa-11")

    assert second.status_code == 201
    body = second.json()
    assert body["new_ticket_created"] is True
    assert body["customer_created"] is False
    assert body["ticket_id"] != first["ticket_id"]
    assert body["ticket_status"] == "OPEN"

    old = db.one("SELECT status, resolved_at FROM tickets WHERE id = :t", t=first["ticket_id"])
    assert old == {"status": "RESOLVED", "resolved_at": resolved_at}
    assert db.count("tickets") == 2
    assert db.count("ticket_messages", "ticket_id = :t", t=first["ticket_id"]) == 1
    assert db.count("ticket_messages", "ticket_id = :t", t=body["ticket_id"]) == 1

    history = api.get(f"/api/v1/customers/{body['customer_id']}/tickets").json()
    assert [t["status"] for t in history["items"]] == ["OPEN", "RESOLVED"]


def test_duplicate_external_message_is_processed_once(api, db):
    phone = unique_phone()
    first = intake(api, phone, "My car service is delayed", "demo-msg-dup")
    second = intake(api, phone, "My car service is delayed", "demo-msg-dup")
    third = intake(api, phone, "My car service is delayed", "demo-msg-dup")

    assert first.status_code == 201
    assert second.status_code == third.status_code == 200
    for replay in (second.json(), third.json()):
        assert replay["duplicate"] is True
        assert replay["new_ticket_created"] is False and replay["customer_created"] is False
        for key in ("ticket_id", "customer_id", "message_id"):
            assert replay[key] == first.json()[key]
    assert second.json() == third.json()

    assert db.count("customers") == 1
    assert db.count("tickets") == 1
    assert db.count("ticket_messages") == 1
    assert db.count("ticket_events") == 1


def test_duplicate_of_a_message_on_a_resolved_ticket_does_not_open_a_new_ticket(api, db):
    phone = unique_phone()
    first = intake(api, phone, "Original enquiry", "wa-20").json()
    api.patch(f"/api/v1/tickets/{first['ticket_id']}/status", json={"status": "IN_PROGRESS"})
    api.patch(f"/api/v1/tickets/{first['ticket_id']}/status", json={"status": "RESOLVED"})

    replay = intake(api, phone, "Original enquiry", "wa-20")
    assert replay.status_code == 200
    assert replay.json()["ticket_id"] == first["ticket_id"]
    assert replay.json()["ticket_status"] == "RESOLVED"
    assert db.count("tickets") == 1 and db.count("ticket_messages") == 1


def test_reused_external_id_with_different_content_is_rejected(api, db):
    phone = unique_phone()
    intake(api, phone, "First text", "wa-30")

    assert_error(intake(api, phone, "Changed text", "wa-30"), 409, "EXTERNAL_MESSAGE_ID_CONFLICT")
    assert_error(intake(api, unique_phone(), "First text", "wa-30"), 409, "EXTERNAL_MESSAGE_ID_CONFLICT")
    assert db.count("customers") == 1
    assert db.count("ticket_messages") == 1


def test_messages_without_external_id_are_not_deduplicated(api, db):
    phone = unique_phone()
    a = intake(api, phone, "Same words").json()
    b = intake(api, phone, "Same words").json()
    assert a["message_id"] != b["message_id"] and a["ticket_id"] == b["ticket_id"]
    assert db.count("ticket_messages") == 2


def test_database_rejects_duplicate_external_message_ids(api, db):
    intake(api, unique_phone(), "Hello", "wa-40")
    with pytest.raises(IntegrityError) as excinfo:
        db.execute(
            "INSERT INTO ticket_messages (id, ticket_id, company_id, external_message_id, source, sender_type, "
            "message_text, created_at) SELECT gen_random_uuid(), ticket_id, company_id, external_message_id, source, "
            "sender_type, 'copy', now() FROM ticket_messages WHERE external_message_id = 'wa-40'"
        )
    assert excinfo.value.orig.diag.constraint_name == "uq_ticket_messages_company_source_external_id"


def test_concurrent_duplicate_is_resolved_by_the_unique_index(api, db, monkeypatch):
    """Simulate a race: the duplicate check misses a message committed by a concurrent request.

    The insert then violates the unique index, the transaction is rolled back and
    retried, and the retry returns the already-stored message.
    """
    phone = unique_phone()
    original = intake(api, phone, "Racing message", "wa-race").json()

    real_find = intake_service._find_processed
    calls = {"n": 0}

    def find_misses_first_time(session, company, data):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_find(session, company, data)

    monkeypatch.setattr(intake_service, "_find_processed", find_misses_first_time)
    replay = intake(api, phone, "Racing message", "wa-race")

    assert calls["n"] == 2
    assert replay.status_code == 200, replay.text
    assert replay.json()["duplicate"] is True and replay.json()["message_id"] == original["message_id"]
    assert db.count("ticket_messages") == 1 and db.count("tickets") == 1


def test_failure_rolls_back_the_whole_intake_transaction(app, api, db, monkeypatch):
    def broken_add_message(*args, **kwargs):
        raise RuntimeError("simulated failure while saving the message")

    monkeypatch.setattr(ticket_repository, "add_message", broken_add_message)
    failing_client = TestClient(app, headers={"X-API-Key": TEST_API_KEY}, raise_server_exceptions=False)

    response = failing_client.post(
        INTAKE, json={"customer_name": "Rollback", "phone_number": unique_phone(), "message_text": "Lost?"}
    )

    assert_error(response, 500, "INTERNAL_ERROR")
    assert "simulated failure" not in response.text  # internal details are not exposed
    # Customer, ticket and TICKET_CREATED event were flushed before the failure: all rolled back.
    assert db.count("customers") == 0
    assert db.count("tickets") == 0
    assert db.count("ticket_events") == 0
    assert db.count("ticket_messages") == 0


def test_failure_on_existing_ticket_leaves_it_untouched(app, api, db, monkeypatch):
    phone = unique_phone()
    intake(api, phone, "First", "wa-50")
    before = db.one("SELECT id, updated_at FROM tickets")

    def broken_add_message(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(ticket_repository, "add_message", broken_add_message)
    failing_client = TestClient(app, headers={"X-API-Key": TEST_API_KEY}, raise_server_exceptions=False)
    response = failing_client.post(
        INTAKE, json={"customer_name": "X", "phone_number": phone, "message_text": "Second", "external_message_id": "wa-51"}
    )

    assert response.status_code == 500
    assert db.one("SELECT id, updated_at FROM tickets") == before
    assert db.count("ticket_messages") == 1


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"customer_name": "A", "phone_number": "+19995550199"}, "message_text"),
        ({"customer_name": "A", "message_text": "hi"}, "phone_number"),
        ({"phone_number": "+19995550199", "message_text": "hi"}, "customer_name"),
        ({"customer_name": "A", "phone_number": "12345", "message_text": "hi"}, "phone_number"),
        ({"customer_name": "A", "phone_number": "+19995550199", "message_text": "   "}, "message_text"),
        ({"customer_name": "A", "phone_number": "+19995550199", "message_text": "x" * 4097}, "message_text"),
        (
            {"customer_name": "A", "phone_number": "+19995550199", "message_text": "hi", "external_message_id": ""},
            "external_message_id",
        ),
        (
            {"customer_name": "A", "phone_number": "+19995550199", "message_text": "hi", "external_message_id": "a b"},
            "external_message_id",
        ),
        (
            {"customer_name": "A", "phone_number": "+19995550199", "message_text": "hi", "source": "WHATSAPP"},
            "source",
        ),
    ],
)
def test_invalid_intake_requests(api, db, payload, field):
    error = assert_error(api.post(INTAKE, json=payload), 422, "VALIDATION_ERROR")
    assert ["body", field] in [d["loc"] for d in error["details"]]
    assert db.count("customers") == 0 and db.count("tickets") == 0
