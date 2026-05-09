"""DB engine, session factory, transaction context, retrying wrapper.

Single source of truth for SQLAlchemy connectivity. Loops use
`retrying_db()` to PAUSE during RDS failover rather than crashing on the
first transient error (HLD §5.1).

Traces: HLD §5.1 (RDS retry-with-pause), REQ-INF-003.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DbSettings:
    """Connection settings for the async engine.

    `url` is a Tier-2 (env-var) field per REQ-CFG-007.
    """

    url: str
    pool_size: int = 10
    max_overflow: int = 5
    pool_recycle_sec: int = 1800
    echo: bool = False
    statement_timeout_ms: int = 30_000


def create_engine(settings: DbSettings) -> AsyncEngine:
    """Construct an asyncpg-backed engine with sensible defaults.

    `pool_pre_ping=True` so dead connections are detected before use, which
    matters for surviving RDS failover.
    """
    return create_async_engine(
        settings.url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_recycle=settings.pool_recycle_sec,
        pool_pre_ping=True,
        echo=settings.echo,
        connect_args={"server_settings": {"statement_timeout": str(settings.statement_timeout_ms)}},
    )


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an async session factory bound to the engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Open a session and run within a transaction.

    Commits on success, rolls back on exception. Caller never sees a
    half-applied state.
    """
    async with sessionmaker() as session, session.begin():
        yield session


@asynccontextmanager
async def retrying_db(
    op_name: str,
    *,
    max_attempts: int = 5,
    base_delay_sec: float = 1.0,
    max_delay_sec: float = 8.0,
) -> AsyncIterator[None]:
    """Wrap a DB operation in exponential-backoff retry.

    Loops use this to PAUSE on transient RDS errors (failover window) rather
    than crashing the process on first failure. `IntegrityError` is NOT
    retried — those indicate programmer/data bugs, not transient state.

    Raises after exhausting attempts so the caller can decide to crash.
    """
    attempt = 1
    delay = base_delay_sec
    while True:
        try:
            yield
            return
        except (OperationalError, DBAPIError) as e:
            transient = isinstance(e, OperationalError) or getattr(
                e, "connection_invalidated", False
            )
            if not transient or attempt >= max_attempts:
                logger.error(
                    "db_op_failed",
                    extra={
                        "op": op_name,
                        "attempt": attempt,
                        "exhausted": attempt >= max_attempts,
                    },
                )
                raise
            logger.warning(
                "db_op_retry",
                extra={
                    "op": op_name,
                    "attempt": attempt,
                    "delay_sec": delay,
                    "error_type": type(e).__name__,
                },
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay_sec)
            attempt += 1


__all__ = [
    "DbSettings",
    "create_engine",
    "retrying_db",
    "session_factory",
    "transaction",
]
