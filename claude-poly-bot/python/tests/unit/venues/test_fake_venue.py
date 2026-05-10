"""Unit tests for venues.mocks.FakeVenue.

Traces: REQ-VEN-008.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from claude_poly_bot.domain.clock import FakeClock
from claude_poly_bot.domain.models import (
    Book,
    Geo,
    PolymarketMarket,
    VenueName,
)
from claude_poly_bot.domain.protocols import Venue
from claude_poly_bot.venues.mocks.fake_venue import FakeVenue


def _market(geo: Geo | None = None) -> PolymarketMarket:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    return PolymarketMarket(
        external_id="m1",
        name="x",
        geo=geo,
        created_at=now,
        question="?",
        resolution_rules=".",
        resolution_time=now + timedelta(hours=24),
        outcomes=["YES", "NO"],
        token_ids={"YES": "tok-yes", "NO": "tok-no"},
    )


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 4, 26, 12, 0, tzinfo=UTC))


def test_fake_venue_satisfies_venue_protocol() -> None:
    fv = FakeVenue(VenueName.POLYMARKET, _clock())
    assert isinstance(fv, Venue)


@pytest.mark.asyncio
async def test_list_active_markets_returns_added() -> None:
    fv = FakeVenue(VenueName.POLYMARKET, _clock())
    fv.add_market(_market())
    markets = await fv.list_active_markets()
    assert len(markets) == 1


@pytest.mark.asyncio
async def test_list_active_markets_geo_filter() -> None:
    fv = FakeVenue(VenueName.POLYMARKET, _clock())
    fv.add_market(_market(geo=Geo.US))
    fv.add_market(_market(geo=Geo.INTERNATIONAL))
    fv.add_market(_market(geo=None))  # passthrough
    us = await fv.list_active_markets(geo=Geo.US)
    assert len(us) == 2  # US + None passthrough


@pytest.mark.asyncio
async def test_list_active_markets_raises_when_configured() -> None:
    fv = FakeVenue(VenueName.POLYMARKET, _clock(), list_active_should_raise=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await fv.list_active_markets()


@pytest.mark.asyncio
async def test_get_book_returns_set_book() -> None:
    fv = FakeVenue(VenueName.POLYMARKET, _clock())
    book = Book(
        venue=VenueName.POLYMARKET,
        market_id="tok-yes",
        bids=[(Decimal("0.49"), 100)],
        asks=[(Decimal("0.51"), 100)],
        midpoint=Decimal("0.5"),
        timestamp=datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
    )
    fv.set_book("tok-yes", book)
    out = await fv.get_book("tok-yes")
    assert out == book


@pytest.mark.asyncio
async def test_get_book_missing_raises_keyerror() -> None:
    fv = FakeVenue(VenueName.POLYMARKET, _clock())
    with pytest.raises(KeyError):
        await fv.get_book("missing")


@pytest.mark.asyncio
async def test_market_open_toggle() -> None:
    fv = FakeVenue(VenueName.POLYMARKET, _clock(), is_open=False)
    assert (await fv.is_market_open()) is False
    fv.set_market_open(True)
    assert (await fv.is_market_open()) is True


@pytest.mark.asyncio
async def test_health_check_ok() -> None:
    fv = FakeVenue(VenueName.POLYMARKET, _clock())
    health = await fv.health_check()
    assert health.status == "ok"
