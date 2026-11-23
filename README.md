# Customer_Support_Ticket_Mgmt_Sys

Customer support ticket management system for Crescent Motors.

| Folder | What it is | Status |
|---|---|---|
| [`crescent-ticket-service/`](crescent-ticket-service/) | Ticket Management Backend (Microservice 2): FastAPI + SQLAlchemy + Alembic on a local PGlite database | Version 1 |
| _(future)_ | WhatsApp Webhook Service (Microservice 1) | Not built |

## Getting started

```bash
git clone https://github.com/getvishalprajapati/Customer_Support_Ticket_Mgmt_Sys.git
cd Customer_Support_Ticket_Mgmt_Sys/crescent-ticket-service
```

Then follow [`crescent-ticket-service/README.md`](crescent-ticket-service/README.md)
(Python 3.12 or 3.13, Node.js 22; no Docker or cloud account needed).

More documentation:

- [Architecture, PGlite limitations, WhatsApp and Supabase plans](crescent-ticket-service/docs/architecture.md)
- [curl walkthrough of the full ticket flow](crescent-ticket-service/docs/api_examples.md)
- [Pinned dependencies and publication-date evidence](crescent-ticket-service/docs/dependencies.md)
