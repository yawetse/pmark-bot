"""SQLAlchemy session factory helpers.

REQ: REQ-DB-001, REQ-DB-007
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker


DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_POOL_TIMEOUT_SECONDS = 10


class PersistenceConfigurationError(ValueError):
    """Raised when database bootstrap configuration is invalid."""


def create_session_factory(database_url: str) -> sessionmaker:
    """Create a SQLAlchemy session factory for a Postgres database URL.

    REQ: REQ-DB-001, REQ-DB-007
    """

    try:
        url = make_url(database_url)
    except ArgumentError as exc:
        raise PersistenceConfigurationError("database_url must be a valid Postgres DSN") from exc
    if url.get_backend_name() != "postgresql":
        raise PersistenceConfigurationError("database_url must use the postgresql backend")
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    try:
        engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_timeout=DEFAULT_POOL_TIMEOUT_SECONDS,
            connect_args={"connect_timeout": DEFAULT_CONNECT_TIMEOUT_SECONDS},
        )
    except (ImportError, SQLAlchemyError) as exc:
        raise PersistenceConfigurationError("database_url could not initialize a Postgres engine") from exc
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
