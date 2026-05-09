"""Integration tests for SqlAlchemyCandidateRepo.publish + queue_depth.

Traces: REQ-SCAN-005, HLD §5.6 (backpressure metric).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from claude_poly_bot.domain.models import (
    Book,
    Candidate,
    PolymarketMarket,
    PolymarketScoreFields,
    ScanScore,
    VenueName,
)
from claude_poly_bot.storage.repos.queue import SqlAlchemyCandidateRepo
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


def _candidate(market_id: str = "m1") -> Candidate:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    market = PolymarketMarket(
        external_id="0xabc",
        name="Test",
        created_at=now,
        question="?",
        resolution_rules=".",
        resolution_time=now + timedelta(hours=24),
        outcomes=["YES", "NO"],
        token_ids={"YES": "tok-yes", "NO": "tok-no"},
    )
    book = Book(
        venue=VenueName.POLYMARKET,
        market_id=market_id,
        bids=[(Decimal("0.49"), 500)],
        asks=[(Decimal("0.51"), 500)],
        midpoint=Decimal("0.5"),
        timestamp=now,
    )
    score = ScanScore(
        market_id=market_id,
        venue=VenueName.POLYMARKET,
        fields=PolymarketScoreFields(
            gap=Decimal("0.10"), depth=Decimal("500"), hours_to_resolution=Decimal("24")
        ),
        accepted=True,
    )
    return Candidate(
        venue=VenueName.POLYMARKET,
        market_id=market_id,
        market_snapshot=market,
        book_snapshot=book,
        scan_score=score,
        created_at=now,
    )


@pytest.mark.asyncio
async def test_publish_inserts_row(_engine: AsyncEngine) -> None:
    """REQ-SCAN-005: publish inserts a row in candidate_queue."""
    sm = async_sessionmaker(_engine, expire_on_commit=False)
    repo = SqlAlchemyCandidateRepo(sm)
    candidate = _candidate("m-publish-1")

    await repo.publish(candidate)
    depth = await repo.queue_depth(VenueName.POLYMARKET)
    assert depth >= 1


@pytest.mark.asyncio
async def test_queue_depth_filters_by_venue(_engine: AsyncEngine) -> None:
    sm = async_sessionmaker(_engine, expire_on_commit=False)
    repo = SqlAlchemyCandidateRepo(sm)
    base = await repo.queue_depth(VenueName.POLYMARKET)
    await repo.publish(_candidate("m-venue-filter"))
    after = await repo.queue_depth(VenueName.POLYMARKET)
    assert after == base + 1
