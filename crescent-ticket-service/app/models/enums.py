"""Enumerations shared by models, schemas and services.

Values are stored as VARCHAR with CHECK constraints (not PostgreSQL ENUM types)
so new values can be added with a simple, portable migration.
"""

from enum import StrEnum


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


ACTIVE_TICKET_STATUSES = (TicketStatus.OPEN, TicketStatus.IN_PROGRESS)


class TicketPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SenderType(StrEnum):
    CUSTOMER = "CUSTOMER"
    AGENT = "AGENT"
    INTERNAL = "INTERNAL"


class MessageSource(StrEnum):
    # Created through POST /api/v1/tickets/{id}/messages
    API = "API"
    # Created through the simulated intake POST /api/v1/intake/messages.
    # A future WhatsApp webhook service would add e.g. WHATSAPP (migration required).
    SIMULATED = "SIMULATED"


class TicketEventType(StrEnum):
    TICKET_CREATED = "TICKET_CREATED"
    AGENT_ASSIGNED = "AGENT_ASSIGNED"
    STATUS_CHANGED = "STATUS_CHANGED"
    TICKET_RESOLVED = "TICKET_RESOLVED"


def sql_in_list(enum_cls: type[StrEnum]) -> str:
    """Render "'A', 'B'" for CHECK constraints (values are fixed enum members, never user input)."""
    return ", ".join(f"'{member.value}'" for member in enum_cls)
