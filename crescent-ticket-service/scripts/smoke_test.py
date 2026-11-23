"""End-to-end smoke test against a RUNNING API (standard library only).

Runs the documented business flow (docs/api_examples.md) with fresh fictional
records, checking status codes and response fields at every step.

Usage (project root; PGlite and the API must be running):
    python scripts/smoke_test.py
Configuration: SMOKE_TEST_BASE_URL (default http://127.0.0.1:8000) and API_KEY,
read from the environment or the project .env file.

Exit code 0 when every step passes, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_config() -> tuple[str, str]:
    values: dict[str, str] = {}
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        from dotenv import dotenv_values  # installed with pydantic-settings

        values = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
    base_url = os.environ.get("SMOKE_TEST_BASE_URL") or values.get("SMOKE_TEST_BASE_URL") or "http://127.0.0.1:8000"
    api_key = os.environ.get("API_KEY") or values.get("API_KEY")
    if not api_key:
        sys.exit("API_KEY is not set (environment or .env)")
    return base_url.rstrip("/"), api_key


class Api:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def call(self, method: str, path: str, body: Any = None, *, key: bool = True) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        if key:
            headers["X-API-Key"] = self.api_key
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)


passed = 0


def check(step: str, condition: bool, detail: Any = "") -> None:
    global passed
    if not condition:
        print(f"FAIL  {step}\n      {detail}")
        sys.exit(1)
    passed += 1
    print(f"PASS  {step}")


def main() -> int:
    base_url, api_key = load_config()
    api = Api(base_url, api_key)
    run = f"{int(time.time())}{secrets.randbelow(100):02d}"  # 12 digits, unique per run
    phone = f"+999{run}"  # +999 is an unassigned country code: fictional
    print(f"Smoke test against {base_url} (run {run})\n")

    try:
        status, body = api.call("GET", "/health", key=False)
    except urllib.error.URLError as exc:
        print(f"FAIL  API not reachable at {base_url}: {exc.reason}")
        return 1
    check("GET /health -> 200 ok", status == 200 and body["status"] == "ok", body)
    status, body = api.call("GET", "/health/ready", key=False)
    check("GET /health/ready -> 200 ready", status == 200 and body["status"] == "ready", body)
    status, body = api.call("GET", "/api/v1/company", key=False)
    check("request without API key -> 401 UNAUTHORIZED", status == 401 and body["error"]["code"] == "UNAUTHORIZED", body)

    status, customer = api.call("POST", "/api/v1/customers", {"name": "Smoke Test Customer", "phone_number": phone})
    check("1. create customer -> 201", status == 201 and customer["phone_number"] == phone, customer)

    status, agent = api.call(
        "POST", "/api/v1/agents", {"name": "Smoke Test Agent", "email": f"smoke.{run}@example.com"}
    )
    check("2. create support agent -> 201 (active)", status == 201 and agent["is_active"] is True, agent)

    status, ticket = api.call(
        "POST",
        "/api/v1/tickets",
        {"customer_id": customer["id"], "subject": "Car service delayed", "description": "Promised for Friday."},
    )
    check("3. create ticket -> 201", status == 201, ticket)
    ticket_id = ticket["id"]

    status, body = api.call("GET", f"/api/v1/tickets/{ticket_id}")
    check("4. ticket is OPEN and unassigned", status == 200 and body["status"] == "OPEN" and body["assigned_agent"] is None, body)

    status, body = api.call("PATCH", f"/api/v1/tickets/{ticket_id}/assign", {"agent_id": agent["id"]})
    check("5. assign agent -> 200", status == 200 and body["assigned_agent_id"] == agent["id"], body)

    status, body = api.call("GET", f"/api/v1/tickets/{ticket_id}")
    check("6. ticket is IN_PROGRESS", body["status"] == "IN_PROGRESS" and body["assigned_agent"]["id"] == agent["id"], body)

    status, message = api.call(
        "POST",
        f"/api/v1/tickets/{ticket_id}/messages",
        {"sender_type": "CUSTOMER", "message_text": "Any update on my car?"},
    )
    check("7. add customer message -> 201", status == 201 and message["sender_type"] == "CUSTOMER", message)

    status, body = api.call("PATCH", f"/api/v1/tickets/{ticket_id}/status", {"status": "RESOLVED"})
    check("8. resolve ticket -> 200", status == 200, body)

    status, body = api.call("GET", f"/api/v1/tickets/{ticket_id}")
    check("9. ticket is RESOLVED with resolved_at", body["status"] == "RESOLVED" and body["resolved_at"], body)

    intake_body = {
        "customer_name": "Smoke Test Customer",
        "phone_number": phone,
        "message_text": "New problem: the air conditioning is not cooling",
        "external_message_id": f"smoke-{run}-1",
    }
    status, intake = api.call("POST", "/api/v1/intake/messages", intake_body)
    check("10. submit new simulated customer message -> 201", status == 201 and intake["duplicate"] is False, intake)
    check(
        "11. a NEW ticket was created",
        intake["new_ticket_created"] is True and intake["ticket_id"] != ticket_id and intake["customer_id"] == customer["id"],
        intake,
    )

    status, old = api.call("GET", f"/api/v1/tickets/{ticket_id}")
    check("12. old ticket remains RESOLVED", old["status"] == "RESOLVED" and old["resolved_at"] == body["resolved_at"], old)

    status, history = api.call("GET", f"/api/v1/customers/{customer['id']}/tickets")
    check(
        "    customer history has both tickets (newest first)",
        [t["id"] for t in history["items"]] == [intake["ticket_id"], ticket_id],
        history,
    )

    # Idempotency: the same external_message_id submitted twice is stored once.
    dup_body = {**intake_body, "message_text": "Duplicate check", "external_message_id": f"smoke-{run}-dup"}
    status1, first = api.call("POST", "/api/v1/intake/messages", dup_body)
    status2, second = api.call("POST", "/api/v1/intake/messages", dup_body)
    check("duplicate: first submission -> 201", status1 == 201 and first["duplicate"] is False, first)
    check(
        "duplicate: second submission -> 200 duplicate, same ids",
        status2 == 200 and second["duplicate"] is True and second["message_id"] == first["message_id"],
        second,
    )
    status, messages = api.call("GET", f"/api/v1/tickets/{first['ticket_id']}/messages")
    stored = [m for m in messages["items"] if m["external_message_id"] == f"smoke-{run}-dup"]
    check("duplicate: exactly one message stored", len(stored) == 1, messages)

    print(f"\nAll {passed} smoke test checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
