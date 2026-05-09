"""Integration tests for SqlAlchemyMarketScanRepo.

Traces: REQ-SCAN-008.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from claude_poly_bot.domain.models import MarketScanRun, VenueName
from claude_poly_bot.storage.repos.scans import SqlAlchemyMarketScanRepo
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


@pytest.mark.asyncio
async def test_record_and_list_recent(_engine: AsyncEngine) -> None:
    sm = async_sessionmaker(_engine, expire_on_commit=False)
    repo = SqlAlchemyMarketScanRepo(sm)

    started = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    run = MarketScanRun(
        venue=VenueName.POLYMARKET,
        started_at=started,
        ended_at=started + timedelta(seconds=15),
        fetched=500,
        accepted=35,
        rejected=465,
    )
    await repo.record(run)

    recent = await repo.list_recent(VenueName.POLYMARKET, limit=10)
    assert any(r.scan_correlation_id == run.scan_correlation_id for r in recent)
