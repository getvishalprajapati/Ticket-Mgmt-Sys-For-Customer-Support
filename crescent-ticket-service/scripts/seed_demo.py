"""Insert fictional demo data into the database configured by DATABASE_URL.

Safe to run repeatedly: existing demo records are left unchanged.
All names, phone numbers (+1 NPA 555-01XX is reserved for fiction) and email
addresses (example.com) are fictional.

Usage (project root, virtual environment active, migrations applied):
    python scripts/seed_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import DatabaseSettings  # noqa: E402
from app.core.database import create_db_engine, create_session_factory, session_scope  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.models.enums import TicketPriority, TicketStatus  # noqa: E402
from app.repositories import agent_repository, customer_repository, ticket_repository  # noqa: E402
from app.repositories.ticket_repository import TicketFilters  # noqa: E402
from app.schemas.agent import AgentCreate  # noqa: E402
from app.schemas.customer import CustomerCreate  # noqa: E402
from app.schemas.ticket import MessageCreate, TicketCreate  # noqa: E402
from app.services import agent_service, company_service, customer_service, ticket_service  # noqa: E402


class SeedSettings(DatabaseSettings):
    company_name: str = "Crescent Motors"


DEMO_AGENTS = [
    AgentCreate(name="Aarav Demo", email="aarav.demo@example.com"),
    AgentCreate(name="Meera Demo", email="meera.demo@example.com"),
    AgentCreate(name="Inactive Demo Agent", email="inactive.demo@example.com", is_active=False),
]
DEMO_CUSTOMERS = [
    CustomerCreate(name="Demo Customer One", phone_number="+12025550101"),
    CustomerCreate(name="Demo Customer Two", phone_number="+12025550102"),
    CustomerCreate(name="Demo Customer Three", phone_number="+12025550103"),
]


def main() -> int:
    settings = SeedSettings()  # type: ignore[call-arg]
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    created: list[str] = []
    try:
        with session_scope(factory) as session:
            company = company_service.get_configured_company(session, settings.company_name)

            agents = {}
            for data in DEMO_AGENTS:
                agent = agent_repository.get_by_email(session, company.id, data.email)
                if agent is None:
                    agent = agent_service.create_agent(session, company, data)
                    created.append(f"agent    {agent.name} <{agent.email}> active={agent.is_active}")
                agents[data.email] = agent

            customers = []
            for data in DEMO_CUSTOMERS:
                customer = customer_repository.get_by_phone(session, company.id, data.phone_number)
                if customer is None:
                    customer = customer_service.create_customer(session, company, data)
                    created.append(f"customer {customer.name} {customer.phone_number}")
                customers.append(customer)

            def has_tickets(customer_id: object) -> bool:
                _, total = ticket_repository.list_tickets(
                    session, company.id, TicketFilters(customer_id=customer_id), limit=1, offset=0  # type: ignore[arg-type]
                )
                return total > 0

            # Customer One: an OPEN ticket waiting for an agent.
            if not has_tickets(customers[0].id):
                ticket = ticket_service.create_ticket(
                    session,
                    company,
                    TicketCreate(
                        customer_id=customers[0].id,
                        subject="Periodic service booking",
                        description="Customer wants to book the 20,000 km service.",
                        priority=TicketPriority.LOW,
                    ),
                )
                created.append(f"ticket   {ticket.subject!r} {ticket.status}")

            # Customer Two: an IN_PROGRESS ticket handled by Aarav, with a conversation.
            if not has_tickets(customers[1].id):
                ticket = ticket_service.create_ticket(
                    session,
                    company,
                    TicketCreate(
                        customer_id=customers[1].id,
                        subject="Car service delayed",
                        description="The car was promised for Friday and is still at the workshop.",
                        priority=TicketPriority.HIGH,
                    ),
                )
                ticket = ticket_service.assign_agent(session, company, ticket.id, agents["aarav.demo@example.com"].id)
                for sender, text in (
                    ("CUSTOMER", "When will my car be ready?"),
                    ("AGENT", "A replacement part arrives tomorrow; we will call you."),
                    ("INTERNAL", "Part ordered from the regional warehouse."),
                ):
                    ticket_service.add_message(
                        session, company, ticket.id, MessageCreate(sender_type=sender, message_text=text)
                    )
                created.append(f"ticket   {ticket.subject!r} {TicketStatus.IN_PROGRESS} (3 messages)")
    except AppError as exc:
        print(f"Seeding failed: {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    if created:
        print("Created demo records:")
        print("\n".join(f"  {line}" for line in created))
    else:
        print("Demo data already present; nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
