"""Unit tests for FakeStrategist.

Traces: REQ-LLM-009.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from claude_poly_bot.domain.clock import FakeClock
from claude_poly_bot.domain.models import (
    Book,
    Bot,
    CheckType,
    Geo,
    PolymarketMarket,
    PolymarketScoreFields,
    ScanScore,
    SubAgent,
    VenueName,
    Verdict,
)
from claude_poly_bot.domain.protocols import Strategist, StrategistContext
from claude_poly_bot.llm.mocks import FakeStrategist


def _market() -> PolymarketMarket:
    return PolymarketMarket(
        external_id="0xabc",
        name="Will it rain?",
        geo=Geo.US,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        question="Will it rain in NYC by 2026-06-01?",
        resolution_rules="Yes if measurable rain at JFK",
        resolution_time=datetime(2026, 6, 1, tzinfo=UTC),
        outcomes=["YES", "NO"],
        token_ids={"YES": "0x1", "NO": "0x2"},
    )


def _context() -> StrategistContext:
    return StrategistContext(
        book=Book(
            venue=VenueName.POLYMARKET,
            market_id="0xabc",
            bids=[(Decimal("0.4"), 100)],
            asks=[(Decimal("0.42"), 100)],
            midpoint=Decimal("0.41"),
            timestamp=datetime(2026, 5, 10, tzinfo=UTC),
        ),
        scan_score=ScanScore(
            market_id="0xabc",
            venue=VenueName.POLYMARKET,
            fields=PolymarketScoreFields(
                gap=Decimal("0.08"),
                depth=Decimal("12000"),
                hours_to_resolution=Decimal("240"),
            ),
            accepted=True,
        ),
        target_wallets_hits=4,
    )


def test_satisfies_strategist_protocol() -> None:
    fake = FakeStrategist(Bot.CLAUDE, clock=FakeClock(datetime(2026, 5, 10, tzinfo=UTC)))
    assert isinstance(fake, Strategist)


@pytest.mark.asyncio
async def test_default_skip_when_no_script_queued() -> None:
    fake = FakeStrategist(Bot.CLAUDE, clock=FakeClock(datetime(2026, 5, 10, tzinfo=UTC)))
    result = await fake.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())
    assert result.verdict == Verdict.SKIP
    assert "no_script" in result.rationale


@pytest.mark.asyncio
async def test_pops_scripted_response_fifo() -> None:
    fake = FakeStrategist(Bot.CLAUDE, clock=FakeClock(datetime(2026, 5, 10, tzinfo=UTC)))
    fake.queue_response(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        Verdict.BUY,
        Decimal("0.85"),
        Decimal("0.62"),
        rationale="first",
    )
    fake.queue_response(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        Verdict.SELL,
        Decimal("0.70"),
        Decimal("0.30"),
        rationale="second",
    )
    a = await fake.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())
    b = await fake.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())
    assert a.verdict == Verdict.BUY
    assert a.rationale == "first"
    assert b.verdict == Verdict.SELL
    assert b.rationale == "second"


@pytest.mark.asyncio
async def test_market_id_specific_queue_overrides_wildcard() -> None:
    fake = FakeStrategist(Bot.CLAUDE, clock=FakeClock(datetime(2026, 5, 10, tzinfo=UTC)))
    # Wildcard queue
    fake.queue_response(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        Verdict.SELL,
        Decimal("0.5"),
        Decimal("0.3"),
        rationale="wildcard",
    )
    # Market-specific
    fake.queue_response(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        Verdict.BUY,
        Decimal("0.9"),
        Decimal("0.8"),
        market_id="0xabc",
        rationale="specific",
    )
    result = await fake.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())
    assert result.rationale == "specific"


@pytest.mark.asyncio
async def test_raises_scripted_error_and_bumps_counter() -> None:
    fake = FakeStrategist(Bot.CLAUDE, clock=FakeClock(datetime(2026, 5, 10, tzinfo=UTC)))
    boom = RuntimeError("boom")
    fake.queue_response(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        Verdict.SKIP,
        Decimal("0"),
        Decimal("0.5"),
        raise_error=boom,
    )
    with pytest.raises(RuntimeError, match="boom"):
        await fake.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())
    assert await fake.consecutive_error_count() == 1


@pytest.mark.asyncio
async def test_sub_agent_dispatch_uses_sub_agent_key() -> None:
    fake = FakeStrategist(Bot.CLAUDE, clock=FakeClock(datetime(2026, 5, 10, tzinfo=UTC)))
    # Same check_type, different sub_agent → distinct queues.
    fake.queue_response(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        Verdict.BUY,
        Decimal("0.85"),
        Decimal("0.62"),
        sub_agent=SubAgent.ARBITRAGE,
        rationale="arb",
    )
    fake.queue_response(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        Verdict.SELL,
        Decimal("0.70"),
        Decimal("0.30"),
        sub_agent=SubAgent.CONVERGENCE,
        rationale="conv",
    )
    a = await fake.evaluate(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        _market(),
        _context(),
        sub_agent=SubAgent.ARBITRAGE,
    )
    b = await fake.evaluate(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        _market(),
        _context(),
        sub_agent=SubAgent.CONVERGENCE,
    )
    assert a.rationale == "arb"
    assert b.rationale == "conv"
