"""Ticket lifecycle: creation, assignment, status transitions, messages, events, listing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import assert_error


def events_of(db, ticket_id):
    return db.rows(
        "SELECT event_type, previous_value, new_value FROM ticket_events WHERE ticket_id = :t ORDER BY created_at, id",
        t=ticket_id,
    )


# --- creation ------------------------------------------------------------------------


def test_create_ticket_starts_open_with_defaults(api, db, make_customer):
    customer = make_customer()
    response = api.post(
        "/api/v1/tickets",
        json={"customer_id": customer["id"], "subject": "Brake noise", "description": "Squeaking when braking."},
    )

    assert response.status_code == 201, response.text
    ticket = response.json()
    assert ticket["status"] == "OPEN"
    assert ticket["priority"] == "MEDIUM"
    assert ticket["assigned_agent_id"] is None
    assert ticket["resolved_at"] is None
    assert ticket["customer_id"] == customer["id"]

    row = db.one(
        "SELECT status, priority, assigned_agent_id, resolved_at, subject FROM tickets WHERE id = :id", id=ticket["id"]
    )
    assert row == {
        "status": "OPEN",
        "priority": "MEDIUM",
        "assigned_agent_id": None,
        "resolved_at": None,
        "subject": "Brake noise",
    }
    assert events_of(db, ticket["id"]) == [{"event_type": "TICKET_CREATED", "previous_value": None, "new_value": "OPEN"}]


def test_create_ticket_with_explicit_priority(api, make_customer):
    ticket = api.post(
        "/api/v1/tickets",
        json={"customer_id": make_customer()["id"], "subject": "Engine light", "description": "On", "priority": "HIGH"},
    ).json()
    assert ticket["priority"] == "HIGH"


def test_create_ticket_errors(api, db, make_customer):
    assert_error(
        api.post("/api/v1/tickets", json={"customer_id": str(uuid.uuid4()), "subject": "x", "description": "y"}),
        404,
        "CUSTOMER_NOT_FOUND",
    )
    customer_id = make_customer()["id"]
    for payload in (
        {"subject": "No customer", "description": "y"},
        {"customer_id": customer_id, "description": "No subject"},
        {"customer_id": customer_id, "subject": "No description"},
        {"customer_id": customer_id, "subject": "x", "description": "y", "priority": "URGENT"},
        {"customer_id": customer_id, "subject": "x" * 201, "description": "y"},
        {"customer_id": "not-a-uuid", "subject": "x", "description": "y"},
        {"customer_id": customer_id, "subject": "x", "description": "y", "status": "RESOLVED"},
    ):
        assert_error(api.post("/api/v1/tickets", json=payload), 422, "VALIDATION_ERROR")
    assert db.count("tickets") == 0


def test_only_one_active_ticket_per_customer(api, db, make_customer, make_ticket):
    customer = make_customer()
    first = make_ticket(customer["id"])

    error = assert_error(
        api.post("/api/v1/tickets", json={"customer_id": customer["id"], "subject": "Again", "description": "Again"}),
        409,
        "ACTIVE_TICKET_EXISTS",
    )
    assert error["details"] == {"active_ticket_id": first["id"]}
    assert db.count("tickets", "customer_id = :c", c=customer["id"]) == 1


def test_database_enforces_one_active_ticket_per_customer(api, db, make_ticket):
    ticket = make_ticket()
    with pytest.raises(IntegrityError) as excinfo:
        db.execute(
            "INSERT INTO tickets (id, company_id, customer_id, subject, description, priority, status, "
            "created_at, updated_at) SELECT :id, company_id, customer_id, 's', 'd', 'LOW', 'IN_PROGRESS', now(), now() "
            "FROM tickets WHERE id = :existing",
            id=str(uuid.uuid4()),
            existing=ticket["id"],
        )
    assert excinfo.value.orig.diag.constraint_name == "uq_tickets_one_active_per_customer"


def test_database_requires_resolved_at_exactly_when_resolved(api, db, make_ticket):
    ticket = make_ticket()
    with pytest.raises(IntegrityError) as excinfo:
        db.execute("UPDATE tickets SET status = 'RESOLVED' WHERE id = :id", id=ticket["id"])
    assert excinfo.value.orig.diag.constraint_name == "ck_tickets_resolved_at_matches_status"
    with pytest.raises(IntegrityError):
        db.execute("UPDATE tickets SET resolved_at = now() WHERE id = :id", id=ticket["id"])
    with pytest.raises(IntegrityError):
        db.execute("UPDATE tickets SET status = 'CLOSED' WHERE id = :id", id=ticket["id"])
    assert db.scalar("SELECT status FROM tickets WHERE id = :id", id=ticket["id"]) == "OPEN"


# --- assignment ----------------------------------------------------------------------


def test_assign_active_agent_moves_ticket_to_in_progress(api, db, make_ticket, make_agent):
    ticket = make_ticket()
    agent = make_agent()

    response = api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": agent["id"]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "IN_PROGRESS"
    assert body["assigned_agent_id"] == agent["id"]
    row = db.one("SELECT status, assigned_agent_id FROM tickets WHERE id = :id", id=ticket["id"])
    assert row["status"] == "IN_PROGRESS" and str(row["assigned_agent_id"]) == agent["id"]
    assert events_of(db, ticket["id"]) == [
        {"event_type": "TICKET_CREATED", "previous_value": None, "new_value": "OPEN"},
        {"event_type": "AGENT_ASSIGNED", "previous_value": None, "new_value": agent["id"]},
        {"event_type": "STATUS_CHANGED", "previous_value": "OPEN", "new_value": "IN_PROGRESS"},
    ]


def test_reassignment_keeps_status_and_records_previous_agent(api, db, make_ticket, make_agent):
    ticket = make_ticket()
    first, second = make_agent(), make_agent()
    api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": first["id"]})

    body = api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": second["id"]}).json()
    assert body["status"] == "IN_PROGRESS" and body["assigned_agent_id"] == second["id"]
    assert events_of(db, ticket["id"])[-1] == {
        "event_type": "AGENT_ASSIGNED",
        "previous_value": first["id"],
        "new_value": second["id"],
    }

    # Assigning the same agent again changes nothing and records nothing.
    events_before = db.count("ticket_events", "ticket_id = :t", t=ticket["id"])
    again = api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": second["id"]})
    assert again.status_code == 200 and again.json()["assigned_agent_id"] == second["id"]
    assert db.count("ticket_events", "ticket_id = :t", t=ticket["id"]) == events_before


def test_inactive_agent_cannot_be_assigned(api, db, make_ticket, make_agent):
    ticket = make_ticket()
    inactive = make_agent(is_active=False)

    assert_error(
        api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": inactive["id"]}), 409, "AGENT_INACTIVE"
    )
    row = db.one("SELECT status, assigned_agent_id FROM tickets WHERE id = :id", id=ticket["id"])
    assert row == {"status": "OPEN", "assigned_agent_id": None}
    assert db.count("ticket_events", "ticket_id = :t", t=ticket["id"]) == 1


def test_agent_of_another_company_cannot_be_assigned(api, db, make_ticket):
    ticket = make_ticket()
    other_company = str(uuid.uuid4())
    outsider = str(uuid.uuid4())
    db.execute(
        "INSERT INTO companies (id, name, created_at, updated_at) VALUES (:id, 'Other Motors (test)', now(), now())",
        id=other_company,
    )
    db.execute(
        "INSERT INTO agents (id, company_id, name, email, is_active, created_at, updated_at) "
        "VALUES (:id, :company, 'Outsider', 'outsider@example.com', true, now(), now())",
        id=outsider,
        company=other_company,
    )

    assert_error(
        api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": outsider}), 404, "AGENT_NOT_FOUND"
    )
    assert db.scalar("SELECT assigned_agent_id FROM tickets WHERE id = :id", id=ticket["id"]) is None
    # The outsider is not visible through this company's API either.
    assert outsider not in [a["id"] for a in api.get("/api/v1/agents").json()["items"]]

    # The composite foreign key rejects the cross-company assignment even if the service were bypassed.
    with pytest.raises(IntegrityError) as excinfo:
        db.execute("UPDATE tickets SET assigned_agent_id = :a WHERE id = :t", a=outsider, t=ticket["id"])
    assert excinfo.value.orig.diag.constraint_name == "fk_tickets_agent_company"


def test_assignment_errors(api, db, make_ticket, make_agent):
    ticket = make_ticket()
    agent = make_agent()
    assert_error(
        api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": str(uuid.uuid4())}),
        404,
        "AGENT_NOT_FOUND",
    )
    assert_error(
        api.patch(f"/api/v1/tickets/{uuid.uuid4()}/assign", json={"agent_id": agent["id"]}), 404, "TICKET_NOT_FOUND"
    )
    assert_error(api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={}), 422, "VALIDATION_ERROR")

    api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": agent["id"]})
    api.patch(f"/api/v1/tickets/{ticket['id']}/status", json={"status": "RESOLVED"})
    assert_error(
        api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": make_agent()["id"]}),
        409,
        "TICKET_RESOLVED",
    )
    assert str(db.scalar("SELECT assigned_agent_id FROM tickets WHERE id = :id", id=ticket["id"])) == agent["id"]


# --- status transitions --------------------------------------------------------------


def test_status_update_open_to_in_progress(api, db, make_ticket):
    ticket = make_ticket()
    body = api.patch(f"/api/v1/tickets/{ticket['id']}/status", json={"status": "IN_PROGRESS"}).json()
    assert body["status"] == "IN_PROGRESS"
    assert db.scalar("SELECT status FROM tickets WHERE id = :id", id=ticket["id"]) == "IN_PROGRESS"
    assert events_of(db, ticket["id"])[-1] == {
        "event_type": "STATUS_CHANGED",
        "previous_value": "OPEN",
        "new_value": "IN_PROGRESS",
    }


def test_resolve_ticket_persists_resolved_at_and_events(api, db, make_ticket, make_agent):
    ticket = make_ticket()
    api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": make_agent()["id"]})
    before = datetime.now(UTC)

    response = api.patch(f"/api/v1/tickets/{ticket['id']}/status", json={"status": "RESOLVED"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "RESOLVED"
    resolved_at_api = datetime.fromisoformat(body["resolved_at"])

    row = db.one("SELECT status, resolved_at FROM tickets WHERE id = :id", id=ticket["id"])
    assert row["status"] == "RESOLVED"
    assert row["resolved_at"] is not None and row["resolved_at"].tzinfo is not None
    assert row["resolved_at"] == resolved_at_api
    assert before <= row["resolved_at"] <= datetime.now(UTC)

    events = events_of(db, ticket["id"])
    assert events[-2] == {"event_type": "STATUS_CHANGED", "previous_value": "IN_PROGRESS", "new_value": "RESOLVED"}
    assert events[-1]["event_type"] == "TICKET_RESOLVED"
    assert datetime.fromisoformat(events[-1]["new_value"]) == row["resolved_at"]

    # resolved_at survives a fresh read through the API
    assert api.get(f"/api/v1/tickets/{ticket['id']}").json()["resolved_at"] == body["resolved_at"]


@pytest.mark.parametrize(
    ("setup", "target"),
    [
        ([], "RESOLVED"),  # OPEN -> RESOLVED skips IN_PROGRESS
        ([], "OPEN"),  # no-op
        (["IN_PROGRESS"], "OPEN"),  # backwards
        (["IN_PROGRESS"], "IN_PROGRESS"),
        (["IN_PROGRESS", "RESOLVED"], "OPEN"),  # never reopen
        (["IN_PROGRESS", "RESOLVED"], "IN_PROGRESS"),
        (["IN_PROGRESS", "RESOLVED"], "RESOLVED"),
    ],
)
def test_invalid_status_transitions_are_rejected(api, db, make_ticket, setup, target):
    ticket = make_ticket()
    for status in setup:
        assert api.patch(f"/api/v1/tickets/{ticket['id']}/status", json={"status": status}).status_code == 200
    before = db.one("SELECT status, resolved_at, updated_at FROM tickets WHERE id = :id", id=ticket["id"])
    events_before = db.count("ticket_events", "ticket_id = :t", t=ticket["id"])

    error = assert_error(
        api.patch(f"/api/v1/tickets/{ticket['id']}/status", json={"status": target}), 409, "INVALID_STATUS_TRANSITION"
    )
    assert error["details"]["requested_status"] == target
    assert error["details"]["current_status"] == (setup[-1] if setup else "OPEN")
    assert db.one("SELECT status, resolved_at, updated_at FROM tickets WHERE id = :id", id=ticket["id"]) == before
    assert db.count("ticket_events", "ticket_id = :t", t=ticket["id"]) == events_before


def test_invalid_status_values_and_unknown_ticket(api, make_ticket):
    ticket = make_ticket()
    for payload in ({"status": "CLOSED"}, {"status": "resolved"}, {}, {"status": None}):
        assert_error(api.patch(f"/api/v1/tickets/{ticket['id']}/status", json=payload), 422, "VALIDATION_ERROR")
    assert_error(
        api.patch(f"/api/v1/tickets/{uuid.uuid4()}/status", json={"status": "IN_PROGRESS"}), 404, "TICKET_NOT_FOUND"
    )


# --- details, messages, events ---------------------------------------------------------


def test_ticket_details_include_customer_and_agent(api, make_customer, make_agent, make_ticket):
    customer = make_customer(name="Detail Customer")
    ticket = make_ticket(customer["id"])
    detail = api.get(f"/api/v1/tickets/{ticket['id']}").json()
    assert detail["customer"] == {"id": customer["id"], "name": "Detail Customer", "phone_number": customer["phone_number"]}
    assert detail["assigned_agent"] is None

    agent = make_agent(name="Detail Agent")
    api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": agent["id"]})
    detail = api.get(f"/api/v1/tickets/{ticket['id']}").json()
    assert detail["assigned_agent"]["id"] == agent["id"] and detail["assigned_agent"]["name"] == "Detail Agent"
    assert_error(api.get(f"/api/v1/tickets/{uuid.uuid4()}"), 404, "TICKET_NOT_FOUND")


def test_messages_are_stored_and_returned_in_chronological_order(api, db, make_ticket):
    ticket = make_ticket()
    sent = [
        ("CUSTOMER", "Is my car ready?"),
        ("AGENT", "We are waiting for a part."),
        ("INTERNAL", "Part arrives Friday."),
        ("CUSTOMER", "Thanks!"),
    ]
    created = []
    for sender_type, message_text in sent:
        response = api.post(
            f"/api/v1/tickets/{ticket['id']}/messages", json={"sender_type": sender_type, "message_text": message_text}
        )
        assert response.status_code == 201, response.text
        created.append(response.json())
        assert created[-1]["source"] == "API" and created[-1]["external_message_id"] is None

    listing = api.get(f"/api/v1/tickets/{ticket['id']}/messages").json()
    assert listing["total"] == 4
    assert [(m["sender_type"], m["message_text"]) for m in listing["items"]] == sent
    assert [m["id"] for m in listing["items"]] == [m["id"] for m in created]
    timestamps = [m["created_at"] for m in listing["items"]]
    assert timestamps == sorted(timestamps)

    rows = db.rows(
        "SELECT sender_type, message_text, source FROM ticket_messages WHERE ticket_id = :t ORDER BY created_at",
        t=ticket["id"],
    )
    assert [(r["sender_type"], r["message_text"]) for r in rows] == sent
    assert {r["source"] for r in rows} == {"API"}

    page = api.get(f"/api/v1/tickets/{ticket['id']}/messages", params={"limit": 2, "offset": 2}).json()
    assert [m["message_text"] for m in page["items"]] == ["Part arrives Friday.", "Thanks!"]


def test_message_errors_and_resolved_ticket_rules(api, db, make_ticket):
    ticket = make_ticket()
    for payload in (
        {"sender_type": "CUSTOMER"},
        {"message_text": "no sender"},
        {"sender_type": "BOT", "message_text": "x"},
        {"sender_type": "CUSTOMER", "message_text": "   "},
        {"sender_type": "CUSTOMER", "message_text": "x" * 4097},
    ):
        assert_error(api.post(f"/api/v1/tickets/{ticket['id']}/messages", json=payload), 422, "VALIDATION_ERROR")
    assert_error(
        api.post(f"/api/v1/tickets/{uuid.uuid4()}/messages", json={"sender_type": "CUSTOMER", "message_text": "x"}),
        404,
        "TICKET_NOT_FOUND",
    )
    assert_error(api.get(f"/api/v1/tickets/{uuid.uuid4()}/messages"), 404, "TICKET_NOT_FOUND")

    api.patch(f"/api/v1/tickets/{ticket['id']}/status", json={"status": "IN_PROGRESS"})
    api.patch(f"/api/v1/tickets/{ticket['id']}/status", json={"status": "RESOLVED"})
    for sender_type in ("CUSTOMER", "AGENT"):
        assert_error(
            api.post(
                f"/api/v1/tickets/{ticket['id']}/messages", json={"sender_type": sender_type, "message_text": "late"}
            ),
            409,
            "TICKET_RESOLVED",
        )
    note = api.post(
        f"/api/v1/tickets/{ticket['id']}/messages", json={"sender_type": "INTERNAL", "message_text": "Closed out."}
    )
    assert note.status_code == 201
    assert db.count("ticket_messages", "ticket_id = :t", t=ticket["id"]) == 1


def test_event_history_endpoint(api, make_ticket, make_agent):
    ticket = make_ticket()
    agent = make_agent()
    api.patch(f"/api/v1/tickets/{ticket['id']}/assign", json={"agent_id": agent["id"]})
    api.patch(f"/api/v1/tickets/{ticket['id']}/status", json={"status": "RESOLVED"})

    events = api.get(f"/api/v1/tickets/{ticket['id']}/events").json()
    assert events["total"] == 5
    assert [e["event_type"] for e in events["items"]] == [
        "TICKET_CREATED",
        "AGENT_ASSIGNED",
        "STATUS_CHANGED",
        "STATUS_CHANGED",
        "TICKET_RESOLVED",
    ]
    assert [(e["previous_value"], e["new_value"]) for e in events["items"][2:4]] == [
        ("OPEN", "IN_PROGRESS"),
        ("IN_PROGRESS", "RESOLVED"),
    ]
    assert_error(api.get(f"/api/v1/tickets/{uuid.uuid4()}/events"), 404, "TICKET_NOT_FOUND")


# --- listing ---------------------------------------------------------------------------


def test_list_tickets_filters_and_pagination(api, make_customer, make_agent, make_ticket):
    alice, bob, carol = make_customer(), make_customer(), make_customer()
    agent = make_agent()
    t_alice = make_ticket(alice["id"], priority="HIGH")
    t_bob = make_ticket(bob["id"], priority="LOW")
    t_carol = make_ticket(carol["id"], priority="HIGH")
    api.patch(f"/api/v1/tickets/{t_bob['id']}/assign", json={"agent_id": agent["id"]})
    api.patch(f"/api/v1/tickets/{t_carol['id']}/assign", json={"agent_id": agent["id"]})
    api.patch(f"/api/v1/tickets/{t_carol['id']}/status", json={"status": "RESOLVED"})

    def ids(**params):
        body = api.get("/api/v1/tickets", params=params).json()
        return [t["id"] for t in body["items"]], body["total"]

    assert ids() == ([t_carol["id"], t_bob["id"], t_alice["id"]], 3)  # newest first
    assert ids(status="OPEN") == ([t_alice["id"]], 1)
    assert ids(status="IN_PROGRESS") == ([t_bob["id"]], 1)
    assert ids(status="RESOLVED") == ([t_carol["id"]], 1)
    assert ids(priority="HIGH") == ([t_carol["id"], t_alice["id"]], 2)
    assert ids(customer_id=bob["id"]) == ([t_bob["id"]], 1)
    assert ids(assigned_agent_id=agent["id"]) == ([t_carol["id"], t_bob["id"]], 2)
    assert ids(assigned_agent_id=agent["id"], status="IN_PROGRESS") == ([t_bob["id"]], 1)
    assert ids(priority="HIGH", status="OPEN", customer_id=alice["id"]) == ([t_alice["id"]], 1)
    assert ids(customer_id=str(uuid.uuid4())) == ([], 0)

    page = api.get("/api/v1/tickets", params={"limit": 2, "offset": 1}).json()
    assert [t["id"] for t in page["items"]] == [t_bob["id"], t_alice["id"]]
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 1)

    for params in ({"status": "CLOSED"}, {"priority": "URGENT"}, {"limit": 1000}, {"customer_id": "abc"}):
        assert_error(api.get("/api/v1/tickets", params=params), 422, "VALIDATION_ERROR")


def test_company_endpoint(api, db):
    body = api.get("/api/v1/company").json()
    assert body["name"] == "Crescent Motors"
    assert body["id"] == str(db.scalar("SELECT id FROM companies WHERE name = 'Crescent Motors'"))
