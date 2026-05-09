"""M0 DB smoke test: testcontainers Postgres + Alembic upgrade head."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_db_session_is_alive(db_session: AsyncSession) -> None:
    """The per-test DB session works and rolls back automatically.

    AC: Postgres testcontainer + Alembic migrations + transaction-rollback
    fixture form a clean foundation for repo-level integration tests in M1+.
    """
    result = await db_session.execute(text("SELECT 1 AS one"))
    row = result.one()
    assert row.one == 1


@pytest.mark.asyncio
async def test_alembic_upgrade_head_succeeds(db_session: AsyncSession) -> None:
    """Implicit: if `_engine` fixture started successfully, alembic upgrade
    head ran without error. This test simply asserts the connection is in a
    usable state after migrations.
    """
    result = await db_session.execute(text("SELECT current_database()"))
    db_name = result.scalar_one()
    assert isinstance(db_name, str)
    assert len(db_name) > 0
