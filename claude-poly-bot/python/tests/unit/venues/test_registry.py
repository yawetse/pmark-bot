"""Unit tests for venues.registry.

Traces: REQ-VEN-003, REQ-VEN-007.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from claude_poly_bot.domain.clock import FakeClock
from claude_poly_bot.domain.models import VenueName
from claude_poly_bot.venues.mocks.fake_venue import FakeVenue
from claude_poly_bot.venues.registry import VenueNotRegisteredError, VenueRegistry


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 4, 26, 12, 0, tzinfo=UTC))


def test_get_returns_registered_venue() -> None:
    fv = FakeVenue(VenueName.POLYMARKET, _clock())
    reg = VenueRegistry(venues={VenueName.POLYMARKET: fv})
    assert reg.get(VenueName.POLYMARKET) is fv


def test_get_unknown_raises() -> None:
    reg = VenueRegistry(venues={})
    with pytest.raises(VenueNotRegisteredError):
        reg.get(VenueName.POLYMARKET)


def test_list_all_returns_all_registered() -> None:
    pm = FakeVenue(VenueName.POLYMARKET, _clock())
    al = FakeVenue(VenueName.ALPACA, _clock())
    reg = VenueRegistry(venues={VenueName.POLYMARKET: pm, VenueName.ALPACA: al})
    assert set(reg.list_all()) == {pm, al}


@pytest.mark.asyncio
async def test_health_check_all_aggregates() -> None:
    pm = FakeVenue(VenueName.POLYMARKET, _clock())
    al = FakeVenue(VenueName.ALPACA, _clock())
    reg = VenueRegistry(venues={VenueName.POLYMARKET: pm, VenueName.ALPACA: al})
    statuses = await reg.health_check_all()
    assert statuses[VenueName.POLYMARKET].status == "ok"
    assert statuses[VenueName.ALPACA].status == "ok"
