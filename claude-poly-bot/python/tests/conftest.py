"""Pytest fixtures for claude-poly-bot.

Session-scoped Postgres testcontainer + per-test transaction rollback for
fast isolation. FakeClock + state factories wired here.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Test fixtures expose the FakeClock implementation that the production code
# will pull from `claude_poly_bot.domain.clock` once that module lands in M1.
# For now we provide a minimal FakeClock here so M0 scaffolding tests can
# import it; M1 will replace this with the real Clock port + FakeClock.


class _FakeClock:
    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._now = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta) -> None:  # type: ignore[no-untyped-def]
        self._now = self._now + delta

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._now = at.astimezone(UTC)


@pytest.fixture
def fake_clock() -> _FakeClock:
    """A clock fixed at 2026-04-26 12:00:00 UTC by default."""
    return _FakeClock(datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC))


@pytest.fixture(scope="session")
def _postgres_url() -> Iterator[str]:
    """Session-scoped Postgres testcontainer.

    Yields a SQLAlchemy URL pointing to a fresh ephemeral Postgres. The
    container starts once per pytest session and is torn down after.
    """
    if os.getenv("DISABLE_TESTCONTAINERS") == "1":
        # Allow CI to skip integration tests when not running in a Docker-capable env
        pytest.skip("DISABLE_TESTCONTAINERS=1 set; skipping integration tests")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        os.environ["DATABASE_URL"] = url
        yield url


@pytest_asyncio.fixture(scope="session")
async def _engine(_postgres_url: str) -> AsyncIterator[AsyncEngine]:
    """Session-scoped engine that runs Alembic migrations to head once."""
    engine = create_async_engine(_postgres_url, future=True)
    # Run alembic upgrade head once at session start
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _postgres_url.replace("+asyncpg", ""))
    cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "alembic"))
    command.upgrade(cfg, "head")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test session inside a transaction that rolls back on teardown.

    This gives each test a clean DB state cheaply (no recreate, no
    migrate-down/up).
    """
    sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.connect() as conn:
        trans = await conn.begin()
        async with sessionmaker(bind=conn) as session:
            try:
                yield session
            finally:
                await trans.rollback()
