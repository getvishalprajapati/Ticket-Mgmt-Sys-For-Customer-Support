# Crescent Motors Customer Support Ticket Management System

Ticket Management Backend (**Microservice 2**, Version 1) for Crescent Motors.
A FastAPI service that manages customers, human support agents and support
tickets: creation, assignment, status changes, resolution, message history and
an audit trail of ticket events. Inbound customer messages are simulated
through a REST endpoint that a future WhatsApp webhook service will call.

Data is stored in **PGlite** (embedded PostgreSQL 18 running in Node.js) through
its PostgreSQL wire-protocol socket server, so the service runs locally with no
Docker, no database installation and no cloud account. The database layer is
standard SQLAlchemy + Alembic and is designed to move to **Supabase PostgreSQL**
later.

---

## Contents

1. [Version 1 scope](#version-1-scope)
2. [Architecture](#architecture)
3. [Requirements](#requirements)
4. [Installation (Ubuntu / Linux)](#installation-ubuntu--linux)
5. [Running the service](#running-the-service)
6. [Configuration](#configuration)
7. [API overview](#api-overview)
8. [Ticket lifecycle and business rules](#ticket-lifecycle-and-business-rules)
9. [Testing](#testing)
10. [Stopping and resetting](#stopping-and-resetting)
11. [Windows (PowerShell) notes](#windows-powershell-notes)
12. [Troubleshooting](#troubleshooting)
13. [Limitations](#limitations)
14. [Project layout](#project-layout)

Further documentation: [docs/architecture.md](docs/architecture.md),
[docs/api_examples.md](docs/api_examples.md), [docs/dependencies.md](docs/dependencies.md).

---

## Version 1 scope

**Included**

- Company information (one company, Crescent Motors, created by the migrations)
- Customer creation, listing and lookup by phone number (normalized, no duplicates)
- Support agent creation and listing (active / inactive)
- Ticket creation, details, listing with filters (status, priority, customer, agent) and pagination
- Agent assignment (active agents of the same company only)
- Status transitions `OPEN -> IN_PROGRESS -> RESOLVED`, with `resolved_at`
- Ticket messages (customer, agent, internal notes) in chronological order
- Ticket event history (`TICKET_CREATED`, `AGENT_ASSIGNED`, `STATUS_CHANGED`, `TICKET_RESOLVED`)
- Simulated inbound customer messages with automatic ticket creation/reuse and duplicate protection
- Health (`/health`) and database readiness (`/health/ready`) endpoints
- API-key protection, consistent JSON errors, Alembic migrations, automated tests against real PGlite

**Not implemented in Version 1** (by design): WhatsApp webhooks or the Meta
WhatsApp Business API, sending any messages, frontend/dashboard, AI chatbots or
agents, Redis or background queues, SMS/email notifications, payments,
WebSockets, Supabase deployment, Docker, analytics, multi-tenant account
management, end-user authentication.

## Architecture

```
Swagger UI / Postman / curl / tests
              |
              v
      FastAPI REST API            app/api/          routes, request/response shaping
              |
      Pydantic validation         app/schemas/      input rules, phone/email normalization
              |
      Business services           app/services/     rules, transactions, events
              |
      Repositories / ORM          app/repositories/ app/models/
              |
      SQLAlchemy 2 + psycopg2     app/core/database.py
              |   PostgreSQL wire protocol, 127.0.0.1:55432
      PGlite socket server        database/start-db.mjs (Node.js 22)
              |
      Persistent PGlite database  database/pgdata/app/
```

The PGlite socket server is database infrastructure, not a second business
service. See [docs/architecture.md](docs/architecture.md) for design decisions,
the PGlite limitations that were verified, and the future WhatsApp and Supabase
extension points.

### Database

Six tables, created by Alembic migrations in `migrations/versions/`:

| Table | Purpose | Key rules |
|---|---|---|
| `companies` | Company record | unique name; Crescent Motors seeded by migration `0002` |
| `customers` | Customers | unique `(company_id, phone_number)`; phone stored normalized (`+` and 8-15 digits) |
| `agents` | Human support agents | unique `(company_id, email)` (lower-cased); `is_active` |
| `tickets` | Support tickets | status/priority CHECKs; `resolved_at` set exactly when RESOLVED; **one active ticket per customer** (partial unique index); customer and agent must belong to the ticket's company (composite foreign keys) |
| `ticket_messages` | Customer/agent messages and internal notes | unique `(company_id, source, external_message_id)` for duplicate protection |
| `ticket_events` | Audit trail of ticket changes | event type CHECK |

All primary keys are UUIDs and all timestamps are `timestamptz`; the API always
returns timestamps in UTC (`...Z`).

## Requirements

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 or 3.13 | `.python-version` = 3.13. Verified with 3.13.7 (Windows 11) and 3.12.3 (Ubuntu 24.04) |
| Node.js | 22.x | Runs the PGlite database. Recommended: **v22.23.3** (latest Node 22 on or before 2026-09-25). Verified with v22.23.3 (Ubuntu) and v22.20.0 (Windows) |
| npm | bundled with Node.js 22 | |
| curl | any | for the API examples |

On a fresh Ubuntu 24.04, `python3 -m venv` needs the `python3.12-venv`
package (`sudo apt install python3.12-venv`). No database server, Docker or
global Python packages are needed.

## Installation (Ubuntu / Linux)

All commands start in the project directory **`crescent-ticket-service/`**
(the folder that contains this README) unless a `cd` says otherwise.

1. Check the Python and Node.js versions:

   ```bash
   python3 --version          # Python 3.12.x or 3.13.x
   node --version             # v22.x
   npm --version
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the Python dependencies (exact pins; `--uploaded-prior-to` makes pip
   refuse anything published after the 2026-09-25 cutoff):

   ```bash
   python -m pip install "pip==26.2.1"
   python -m pip install --uploaded-prior-to 2026-09-26T00:00:00Z -r requirements-dev.txt
   python -m pip check
   python scripts/check_dependencies.py --offline
   ```

   `requirements.txt` holds the runtime set; `requirements-dev.txt` adds the test tools.
   Run `python scripts/check_dependencies.py` (without `--offline`) to re-verify the
   publication dates and known vulnerabilities online.

4. Install the PGlite database packages (exact versions from `package-lock.json`):

   ```bash
   cd database
   npm ci
   cd ..
   ```

5. Create `.env` from the template and generate a random API key:

   ```bash
   cp .env.example .env
   API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
   sed -i "s|^API_KEY=.*|API_KEY=${API_KEY}|" .env
   grep -E '^(API_KEY|DATABASE_URL)=' .env
   ```

## Running the service

Use three terminals, each starting in `crescent-ticket-service/`.

**Terminal 1 - start the PGlite database** (keeps running in the foreground):

```bash
cd database
npm start
```

Wait for `[pglite] READY host=127.0.0.1 port=55432`. Data is stored in
`database/pgdata/app/`. The server only binds to localhost and refuses
non-loopback addresses.

**Terminal 2 - migrate, seed and start the API:**

```bash
source .venv/bin/activate
alembic upgrade head
alembic current                  # 0002 (head)
python scripts/seed_demo.py      # optional fictional demo data, safe to re-run
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

**Open Swagger UI:** <http://127.0.0.1:8000/docs> - click **Authorize** and
paste the `API_KEY` value from `.env`. The OpenAPI schema is at
<http://127.0.0.1:8000/openapi.json>.

**Terminal 3 - check it works:**

```bash
source .venv/bin/activate
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/health/ready
python scripts/smoke_test.py
```

The smoke test runs the full documented business flow against the running API
with fresh fictional records and prints `PASS`/`FAIL` for each step.

## Configuration

Settings are read from environment variables, or from `.env` in the project
root (see [.env.example](.env.example)). Environment variables take precedence.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | *required* | `postgresql+psycopg2://...`. Local PGlite: `...@127.0.0.1:55432/postgres?sslmode=disable`. Non-local hosts **must** use `sslmode=require`/`verify-ca`/`verify-full` |
| `API_KEY` | *required* | Shared secret for the `X-API-Key` header; at least 16 characters; the `.env.example` placeholder is rejected |
| `COMPANY_NAME` | `Crescent Motors` | The company served by this instance (must exist; created by migration `0002`) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `1` / `0` | Conservative pool for PGlite |
| `DB_POOL_TIMEOUT_SECONDS` | `10` | Wait for a pooled connection before answering 503 |
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | TCP connect timeout |
| `APP_ENV` | `development` | `development`, `test` or `production` (informational) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SMOKE_TEST_BASE_URL` | `http://127.0.0.1:8000` | Used by `scripts/smoke_test.py` only |

PGlite database server options (`database/start-db.mjs`, flag or variable):
`--data-dir`/`PGLITE_DATA_DIR` (default `./pgdata/app`), `--port`/`PGLITE_PORT`
(default `55432`), `--host`/`PGLITE_HOST` (default `127.0.0.1`, loopback only),
`--max-connections`/`PGLITE_MAX_CONNECTIONS` (default `4`).

## API overview

All business endpoints are under `/api/v1` and require `X-API-Key`.
Full, runnable curl examples: [docs/api_examples.md](docs/api_examples.md).

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/health` | Liveness (no database access, no key) | 200 |
| GET | `/health/ready` | Database reachable, migrations at head, company present (no key) | 200 / 503 |
| GET | `/api/v1/company` | Configured company | 200 |
| POST | `/api/v1/customers` | Create customer | 201 |
| GET | `/api/v1/customers` | List customers (`phone_number` lookup, `limit`, `offset`) | 200 |
| GET | `/api/v1/customers/{customer_id}` | Customer details | 200 |
| GET | `/api/v1/customers/{customer_id}/tickets` | Ticket history, newest first (`status` filter) | 200 |
| POST | `/api/v1/agents` | Create support agent | 201 |
| GET | `/api/v1/agents` | List agents (`is_active` filter) | 200 |
| POST | `/api/v1/tickets` | Create ticket for an existing customer | 201 |
| GET | `/api/v1/tickets` | List tickets (`status`, `priority`, `customer_id`, `assigned_agent_id`, `limit`, `offset`) | 200 |
| GET | `/api/v1/tickets/{ticket_id}` | Ticket details incl. customer and agent | 200 |
| PATCH | `/api/v1/tickets/{ticket_id}/assign` | Assign an active agent | 200 |
| PATCH | `/api/v1/tickets/{ticket_id}/status` | Change status | 200 |
| POST | `/api/v1/tickets/{ticket_id}/messages` | Add message / internal note | 201 |
| GET | `/api/v1/tickets/{ticket_id}/messages` | Messages, chronological | 200 |
| GET | `/api/v1/tickets/{ticket_id}/events` | Event history, chronological | 200 |
| POST | `/api/v1/intake/messages` | Simulated inbound customer message | 201 new / 200 duplicate |

Lists return `{"items": [...], "total": n, "limit": l, "offset": o}`. `limit`
is 1-100 (default 20) for customers, agents and tickets and 1-500 (default
100) for messages and events.

Every error has the same shape:

```json
{"error": {"code": "TICKET_NOT_FOUND", "message": "Ticket not found", "details": null}}
```

| HTTP | Codes |
|---|---|
| 401 | `UNAUTHORIZED` (missing or wrong `X-API-Key`) |
| 404 | `CUSTOMER_NOT_FOUND`, `AGENT_NOT_FOUND`, `TICKET_NOT_FOUND`, `NOT_FOUND` |
| 409 | `DUPLICATE_CUSTOMER`, `DUPLICATE_AGENT`, `ACTIVE_TICKET_EXISTS`, `AGENT_INACTIVE`, `INVALID_STATUS_TRANSITION`, `TICKET_RESOLVED`, `EXTERNAL_MESSAGE_ID_CONFLICT`, `INTAKE_CONFLICT` |
| 422 | `VALIDATION_ERROR` (missing/invalid fields, unknown fields, invalid status or priority values, bad UUIDs) |
| 500 | `INTERNAL_ERROR` (details are logged, never returned) |
| 503 | `DATABASE_UNAVAILABLE`, `DATABASE_NOT_MIGRATED`, `COMPANY_NOT_CONFIGURED` |

## Ticket lifecycle and business rules

```
            assign agent (or PATCH status)          PATCH status
   OPEN  ----------------------------------->  IN_PROGRESS  -------------> RESOLVED
                                                                 (resolved_at set; never reopened)
```

1. New tickets start `OPEN`, priority `MEDIUM` unless given, no agent.
2. Assigning an **active** agent of the same company moves an `OPEN` ticket to
   `IN_PROGRESS` (re-assignment keeps the status). Inactive, unknown or
   other-company agents are rejected; resolved tickets cannot be assigned.
3. Resolving sets `status=RESOLVED` and `resolved_at`, and records
   `STATUS_CHANGED` and `TICKET_RESOLVED` events.
4. Only `OPEN -> IN_PROGRESS -> RESOLVED` is allowed; anything else (skipping,
   going back, reopening, no-op) is `409 INVALID_STATUS_TRANSITION`.
5. A customer has at most **one active** (`OPEN`/`IN_PROGRESS`) ticket,
   enforced by the service and a partial unique index. Resolved tickets stay in
   the history forever (nothing is deleted).
6. Resolved tickets accept only `INTERNAL` notes; new customer enquiries go
   through intake and open a new ticket.
7. **Intake** (`POST /api/v1/intake/messages`): find the customer by normalized
   phone number (create if new, existing names are not overwritten); append to
   the active ticket, or open a new ticket if there is none (including after a
   resolution); store the message. Everything happens in one transaction.
8. **Duplicates**: repeating an `external_message_id` returns `200` with
   `"duplicate": true` and the original ids, and writes nothing. Reusing the id
   for a *different* message is `409 EXTERNAL_MESSAGE_ID_CONFLICT`. A database
   unique index backs this up for concurrent requests.

## Testing

```bash
# cwd: crescent-ticket-service/, virtual environment active, database/node_modules installed
python -m pytest
python -m pytest -v tests/test_intake.py        # one file
```

The suite needs **no running services**: it starts its own PGlite server
(`node database/start-db.mjs`) with a separate data directory
`database/pgdata/test/` on an OS-assigned port, applies the real Alembic
migrations, and empties the tables before each test. It never connects to the
application database, `.env`, the internet or any cloud service. Additional
temporary PGlite servers are started for the migration, persistence, restart
and locking tests.

What is covered (assertions on real database rows, not only status codes):
customers (normalization, duplicates, lookup, history), agents, ticket creation,
assignment rules (inactive / unknown / other-company agents), every valid and
invalid status transition, `resolved_at` persistence, messages and ordering,
events, filters and pagination, intake (reuse, new ticket after resolution,
duplicates, conflicting ids, a simulated race on the unique index, transaction
rollback on failure), database constraints, migrations (schema, model/migration
drift via `alembic check`, downgrade/upgrade round trip), persistence across a
database restart, data-directory locking, localhost-only binding, readiness,
database outage (503) and recovery, API-key checks, configuration safeguards,
and dependency pinning.

The smoke test (`python scripts/smoke_test.py`) is separate: it needs the
database and API running (see [Running the service](#running-the-service)).

## Stopping and resetting

- **Stop the API:** press `Ctrl+C` in terminal 2.
- **Stop the database:** press `Ctrl+C` in terminal 1. PGlite flushes and closes
  the data directory and removes its lock file (`[pglite] stopped`). Stop the
  API first so it does not report database errors.
- **Reset only the test database** (it is also wiped automatically at the start
  of every `pytest` run):

  ```bash
  rm -rf database/pgdata/test database/pgdata/test.lock
  ```

- **Reset the application database** (deletes all local data; stop the database first):

  ```bash
  rm -rf database/pgdata/app database/pgdata/app.lock
  ```

  Then start the database again and run `alembic upgrade head`.

## Windows (PowerShell) notes

The same steps work on Windows 10/11 with PowerShell (verified with Python
3.13.7 and Node.js 22.20.0), using these equivalents:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "pip==26.2.1"
python -m pip install --uploaded-prior-to 2026-09-26T00:00:00Z -r requirements-dev.txt
cd database; npm ci; cd ..
Copy-Item .env.example .env     # then edit API_KEY in .env (python -c "import secrets; print(secrets.token_urlsafe(32))")
# terminal 1: cd database; npm start
# terminal 2: alembic upgrade head; uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
python -m pytest
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/health/ready` or API returns `503 DATABASE_UNAVAILABLE` | PGlite is not running or not on the port in `DATABASE_URL`. Start it (`cd database && npm start`). |
| `503 DATABASE_NOT_MIGRATED` or readiness shows `"migrations": "pending"` | Run `alembic upgrade head`. |
| `503 COMPANY_NOT_CONFIGURED` | `COMPANY_NAME` does not match a row in `companies`; keep the default `Crescent Motors` or check migration `0002` ran. |
| Startup error mentioning `API_KEY` | Set a real random key in `.env` (placeholder and keys shorter than 16 characters are rejected). |
| Startup error `sslmode=require` | A non-local `DATABASE_URL` must use TLS. Local PGlite must use `127.0.0.1`/`localhost` with `sslmode=disable`. |
| `[pglite] ERROR: data directory ... is already in use by process N` | Another PGlite process uses the same directory. Stop it, or (if it crashed) the stale lock is removed automatically on the next start. |
| `EADDRINUSE` when starting PGlite | Port 55432 is taken. Use `npm start -- --port 55440` and change the port in `DATABASE_URL`. |
| `npm ci` fails with `EBADENGINE` | Node.js is not version 22 (`engine-strict`); install Node.js 22. |
| Tests fail with `PGliteStartError: Node.js 22 is required` / `npm ci` | `node` is not on `PATH`, or `database/node_modules` is missing. |
| Requests hang until another tool disconnects | Another client keeps a transaction open on PGlite (e.g. a `psql` session left inside `BEGIN`). PGlite runs one transaction at a time and queues everything else; commit/roll back or close that client. |
| Requests return 503 after about 10 s under load | All pooled connections were busy for `DB_POOL_TIMEOUT_SECONDS`. With PGlite, requests are processed one at a time by design. |
| `python3 -m venv` fails on Ubuntu | `sudo apt install python3.12-venv` |

## Limitations

- **Authentication**: a single shared API key is an initial *internal-service*
  safeguard, not user authentication. There are no users, roles, per-agent
  permissions, key rotation or rate limiting. Do not expose the service
  publicly as is; put it behind a private network or gateway.
- **PGlite is a development database**: one query at a time and one
  transaction at a time across all connections, no TLS, no query cancellation,
  ignores startup options (e.g. time zone), single database per server. Fine
  for local development and tests; use PostgreSQL/Supabase for production.
  Details and evidence: [docs/architecture.md](docs/architecture.md#pglite-verified-behaviour-and-limitations).
- **Driver**: `psycopg2-binary` (psycopg 3 is incompatible with the PGlite
  socket server's error recovery). For production the psycopg project
  recommends building `psycopg2` from source instead of the binary wheel.
- **Single company**: Version 1 serves one company selected by `COMPANY_NAME`;
  there is no tenant management.
- **No agent deactivation endpoint**: agents are created active or inactive;
  changing it later requires a future endpoint (or SQL).
- **Known dependency vulnerability**: `certifi 2026.7.22` (dev/test only)
  has an advisory fixed only after the dependency cutoff; see
  [docs/dependencies.md](docs/dependencies.md#known-vulnerability-certifi).
- Linux instructions were executed on Ubuntu 24.04 (WSL2). Other distributions
  and macOS were not tested.

## Project layout

```
crescent-ticket-service/
|-- app/
|   |-- main.py                 FastAPI application factory
|   |-- api/                    routes: company, customers, agents, tickets, intake, health, deps
|   |-- schemas/                Pydantic request/response models and validators
|   |-- services/               business rules and transactions
|   |-- repositories/           SQLAlchemy queries
|   |-- models/                 ORM models and enums
|   |-- core/                   config, database, security, errors
|-- database/                   PGlite socket server (package.json, package-lock.json, .npmrc, start-db.mjs)
|-- migrations/                 Alembic env and versions (0001 schema, 0002 company seed)
|-- tests/                      pytest suite + PGlite test-server harness
|-- scripts/                    seed_demo.py, smoke_test.py, check_dependencies.py
|-- docs/                       architecture.md, api_examples.md, dependencies.md
|-- .env.example  .gitignore  .python-version  alembic.ini  pyproject.toml
|-- requirements.txt  requirements-dev.txt
```
