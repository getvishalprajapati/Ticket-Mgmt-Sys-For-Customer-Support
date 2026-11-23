"""Customer creation, duplicate prevention, lookup and ticket history."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import COMPANY_NAME, assert_error, unique_phone


def test_create_customer_persists_normalized_row(api, db):
    response = api.post("/api/v1/customers", json={"name": "  Demo Customer  ", "phone_number": "+1 (999) 555-0101"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Demo Customer"
    assert body["phone_number"] == "+19995550101"
    assert body["created_at"].endswith("Z")
    assert body["created_at"] == body["updated_at"]

    row = db.one(
        "SELECT c.name, c.phone_number, co.name AS company FROM customers c "
        "JOIN companies co ON co.id = c.company_id WHERE c.id = :id",
        id=body["id"],
    )
    assert row == {"name": "Demo Customer", "phone_number": "+19995550101", "company": COMPANY_NAME}


def test_duplicate_phone_number_is_rejected_even_when_formatted_differently(api, db):
    first = api.post("/api/v1/customers", json={"name": "First", "phone_number": "+19995550102"})
    assert first.status_code == 201

    for variant in ("+19995550102", "+1 999-555-0102", "0019995550102", " +1.999.555.0102 "):
        error = assert_error(
            api.post("/api/v1/customers", json={"name": "Second", "phone_number": variant}), 409, "DUPLICATE_CUSTOMER"
        )
        assert error["details"] == {"existing_customer_id": first.json()["id"]}

    assert db.count("customers") == 1
    assert db.scalar("SELECT name FROM customers") == "First"


def test_database_unique_constraint_backs_up_duplicate_check(api, db, make_customer):
    customer = make_customer()
    company_id = db.scalar("SELECT company_id FROM customers WHERE id = :id", id=customer["id"])
    with pytest.raises(IntegrityError) as excinfo:
        db.execute(
            "INSERT INTO customers (id, company_id, name, phone_number, created_at, updated_at) "
            "VALUES (:id, :company, 'Raw insert', :phone, now(), now())",
            id=str(uuid.uuid4()),
            company=company_id,
            phone=customer["phone_number"],
        )
    assert excinfo.value.orig.pgcode == "23505"
    assert excinfo.value.orig.diag.constraint_name == "uq_customers_company_id_phone_number"
    assert db.count("customers") == 1


def test_create_customer_validation_errors(api, db):
    cases = [
        ({"phone_number": "+19995550103"}, ["body", "name"]),
        ({"name": "No phone"}, ["body", "phone_number"]),
        ({"name": "   ", "phone_number": "+19995550103"}, ["body", "name"]),
        ({"name": "Local number", "phone_number": "9995550103"}, ["body", "phone_number"]),
        ({"name": "Too short", "phone_number": "+123"}, ["body", "phone_number"]),
        ({"name": "Letters", "phone_number": "+1999CALLNOW"}, ["body", "phone_number"]),
        ({"name": "Extra", "phone_number": "+19995550103", "vip": True}, ["body", "vip"]),
    ]
    for payload, location in cases:
        error = assert_error(api.post("/api/v1/customers", json=payload), 422, "VALIDATION_ERROR")
        assert location in [detail["loc"] for detail in error["details"]], (payload, error)
        # Submitted values are never echoed back.
        assert all("input" not in detail for detail in error["details"])
    assert db.count("customers") == 0


def test_get_customer_and_unknown_customer(api, make_customer):
    customer = make_customer(name="Lookup Customer")
    response = api.get(f"/api/v1/customers/{customer['id']}")
    assert response.status_code == 200
    assert response.json() == customer

    assert_error(api.get(f"/api/v1/customers/{uuid.uuid4()}"), 404, "CUSTOMER_NOT_FOUND")
    assert_error(api.get("/api/v1/customers/not-a-uuid"), 422, "VALIDATION_ERROR")


def test_list_customers_with_pagination_and_phone_lookup(api, make_customer):
    created = [make_customer(name=f"Customer {i}") for i in range(5)]

    page1 = api.get("/api/v1/customers", params={"limit": 2, "offset": 0}).json()
    page2 = api.get("/api/v1/customers", params={"limit": 2, "offset": 2}).json()
    page3 = api.get("/api/v1/customers", params={"limit": 2, "offset": 4}).json()
    assert [page1["total"], page1["limit"], page1["offset"]] == [5, 2, 0]
    ids = [c["id"] for c in page1["items"] + page2["items"] + page3["items"]]
    assert len(page3["items"]) == 1
    assert sorted(ids) == sorted(c["id"] for c in created)
    # Newest first
    assert page1["items"][0]["id"] == created[-1]["id"]

    target = created[2]
    formatted = "+999 " + target["phone_number"][4:]
    lookup = api.get("/api/v1/customers", params={"phone_number": formatted}).json()
    assert lookup["total"] == 1 and lookup["items"][0]["id"] == target["id"]

    none = api.get("/api/v1/customers", params={"phone_number": unique_phone()}).json()
    assert none == {"items": [], "total": 0, "limit": 20, "offset": 0}

    assert_error(api.get("/api/v1/customers", params={"phone_number": "abc"}), 422, "VALIDATION_ERROR")
    assert_error(api.get("/api/v1/customers", params={"limit": 101}), 422, "VALIDATION_ERROR")
    assert_error(api.get("/api/v1/customers", params={"limit": 0}), 422, "VALIDATION_ERROR")
    assert_error(api.get("/api/v1/customers", params={"offset": -1}), 422, "VALIDATION_ERROR")


def test_customer_ticket_history_keeps_resolved_tickets(api, db, make_customer, make_agent, make_ticket):
    customer = make_customer()
    agent = make_agent()

    first = make_ticket(customer["id"], subject="First visit")
    api.patch(f"/api/v1/tickets/{first['id']}/assign", json={"agent_id": agent["id"]})
    assert api.patch(f"/api/v1/tickets/{first['id']}/status", json={"status": "RESOLVED"}).status_code == 200
    second = make_ticket(customer["id"], subject="Second visit")

    other_customer = make_customer()
    make_ticket(other_customer["id"], subject="Somebody else")

    history = api.get(f"/api/v1/customers/{customer['id']}/tickets").json()
    assert history["total"] == 2
    assert [t["id"] for t in history["items"]] == [second["id"], first["id"]]  # newest first
    assert [t["status"] for t in history["items"]] == ["OPEN", "RESOLVED"]

    resolved_only = api.get(f"/api/v1/customers/{customer['id']}/tickets", params={"status": "RESOLVED"}).json()
    assert [t["id"] for t in resolved_only["items"]] == [first["id"]]

    assert db.count("tickets", "customer_id = :c", c=customer["id"]) == 2
    assert_error(api.get(f"/api/v1/customers/{uuid.uuid4()}/tickets"), 404, "CUSTOMER_NOT_FOUND")
