"""SQLAlchemy engine and session management.

The same code is used for the local PGlite socket server and for a regular
PostgreSQL server (for example Supabase); only DATABASE_URL and the pool
settings change.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DatabaseSettings

APPLICATION_NAME = "crescent-ticket-service"


def create_db_engine(settings: DatabaseSettings) -> Engine:
    """Create the engine with a conservative pool.

    PGlite is a single-connection database. Its socket server multiplexes
    client connections and runs one query at a time, giving an open
    transaction exclusive access until it commits or rolls back. A small pool
    (default size 1) keeps the application predictable on PGlite.
    """
    return create_engine(
        settings.sqlalchemy_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_pre_ping=True,  # transparently replaces connections after a database restart
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
            "application_name": APPLICATION_NAME,
        },
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Session for scripts: always closed, rolled back unless committed by the caller."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def ping_database(engine: Engine) -> None:
    """Raise an SQLAlchemy error if the database cannot answer a trivial query."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
