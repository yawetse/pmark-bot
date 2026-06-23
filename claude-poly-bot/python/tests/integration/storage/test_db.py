"""Integration tests for storage.db (transaction + retrying_db).

Traces: HLD §5.1 (RDS retry-with-pause), TST-XCUT-006.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from claude_poly_bot.storage.db import retrying_db, run_with_retry, transaction
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


@pytest.mark.asyncio
async def test_transaction_commits_on_success(_engine: AsyncEngine) -> None:
    """Transaction context commits on normal flow."""
    sm = async_sessionmaker(_engine, expire_on_commit=False)
    async with transaction(sm) as session:
        result = await session.execute(text("SELECT 42 AS answer"))
        assert result.scalar_one() == 42


@pytest.mark.asyncio
async def test_transaction_rolls_back_on_exception(_engine: AsyncEngine) -> None:
    """Exception inside `transaction()` rolls back; caller sees the error."""
    sm = async_sessionmaker(_engine, expire_on_commit=False)
    with pytest.raises(RuntimeError, match="boom"):
        async with transaction(sm) as session:
            await session.execute(text("SELECT 1"))
            raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_retrying_db_succeeds_after_transient_error() -> None:
    """First call raises OperationalError, second succeeds. run_with_retry
    retries the whole operation.

    Validates HLD §5.1 — loops PAUSE during transient DB unavailability.
    """
    attempts = 0

    async def inside() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            # Mimic a connection-lost OperationalError.
            raise OperationalError("SELECT 1", {}, Exception("conn lost"))
        return "ok"

    result = await run_with_retry(
        "test_op",
        inside,
        base_delay_sec=0.01,
        max_delay_sec=0.02,
    )
    assert result == "ok"
    assert attempts == 2


@pytest.mark.asyncio
async def test_retrying_db_does_not_retry_integrity_error() -> None:
    """IntegrityError indicates a programmer/data bug; not retried."""
    with pytest.raises(IntegrityError):
        async with retrying_db("test_op", max_attempts=3, base_delay_sec=0.01):
            raise IntegrityError("dup", {}, Exception("dup key"))


@pytest.mark.asyncio
async def test_retrying_db_exhausts_after_max_attempts() -> None:
    """After max_attempts retries, the original exception propagates."""
    sentinel_calls = AsyncMock()

    async def always_fails() -> None:
        await sentinel_calls()
        raise OperationalError("x", {}, Exception("conn lost"))

    with pytest.raises(OperationalError):
        await run_with_retry(
            "test_op",
            always_fails,
            max_attempts=2,
            base_delay_sec=0.01,
            max_delay_sec=0.02,
        )
    assert sentinel_calls.await_count == 2
