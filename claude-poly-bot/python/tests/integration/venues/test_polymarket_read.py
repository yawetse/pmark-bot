"""Integration tests for PolymarketVenue read paths.

HTTP mocked via respx — no real network access.

Traces: REQ-POLY-001..006, REQ-VEN-001 (read subset), REQ-SCAN-007.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from claude_poly_bot.domain.clock import FakeClock
from claude_poly_bot.domain.exceptions import VenueUnreachableError
from claude_poly_bot.domain.models import PolymarketMarket, VenueName
from claude_poly_bot.venues.polymarket.venue import (
    CLOB_BASE,
    GAMMA_BASE,
    PolymarketVenue,
)


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 4, 26, 12, 0, tzinfo=UTC))


def _markets_payload(n: int = 2) -> list[dict[str, str]]:
    end_iso = (datetime(2026, 4, 26, 12, 0, tzinfo=UTC) + timedelta(hours=24)).isoformat()
    return [
        {
            "id": f"m{i}",
            "question": f"Will event {i} happen?",
            "description": "Resolution rules.",
            "endDate": end_iso,
            "outcomes": json.dumps(["YES", "NO"]),
            "clobTokenIds": json.dumps([f"tok-yes-{i}", f"tok-no-{i}"]),
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
@respx.mock
async def test_list_active_markets_parses_payload() -> None:
    respx.get(f"{GAMMA_BASE}/markets").mock(
        return_value=httpx.Response(200, json=_markets_payload(3))
    )
    async with httpx.AsyncClient() as client:
        v = PolymarketVenue(client=client, clock=_clock())
        markets = await v.list_active_markets()
    assert len(markets) == 3
    m0 = markets[0]
    assert isinstance(m0, PolymarketMarket)
    assert m0.external_id == "m0"
    assert m0.outcomes == ["YES", "NO"]
    assert m0.token_ids == {"YES": "tok-yes-0", "NO": "tok-no-0"}


@pytest.mark.asyncio
@respx.mock
async def test_list_active_markets_handles_pagination() -> None:
    """First page is full → second page is fetched. Empty page terminates loop."""
    full_page = _markets_payload(500)
    route = respx.get(f"{GAMMA_BASE}/markets")
    route.side_effect = [
        httpx.Response(200, json=full_page),
        httpx.Response(200, json=[]),  # terminator
    ]
    async with httpx.AsyncClient() as client:
        v = PolymarketVenue(client=client, clock=_clock())
        markets = await v.list_active_markets()
    assert len(markets) == 500


@pytest.mark.asyncio
@respx.mock
async def test_list_active_skips_unparseable_items() -> None:
    """An item missing endDate is skipped, not raised."""
    bad = [{"id": "bad", "question": "?"}]  # missing endDate
    good = _markets_payload(1)
    respx.get(f"{GAMMA_BASE}/markets").mock(return_value=httpx.Response(200, json=bad + good))
    async with httpx.AsyncClient() as client:
        v = PolymarketVenue(client=client, clock=_clock())
        markets = await v.list_active_markets()
    assert len(markets) == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_active_5xx_retries_then_succeeds() -> None:
    """REQ-POLY-005 / REQ-SCAN-007: 5xx is retried up to max_retries."""
    route = respx.get(f"{GAMMA_BASE}/markets")
    route.side_effect = [
        httpx.Response(503, json={}),
        httpx.Response(503, json={}),
        httpx.Response(200, json=_markets_payload(1)),
    ]
    async with httpx.AsyncClient() as client:
        v = PolymarketVenue(
            client=client, clock=_clock(), backoff_base_sec=0.001, backoff_max_sec=0.001
        )
        markets = await v.list_active_markets()
    assert len(markets) == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_active_5xx_after_max_retries_raises() -> None:
    """3 consecutive 5xx → VenueUnreachableError."""
    route = respx.get(f"{GAMMA_BASE}/markets")
    route.side_effect = [
        httpx.Response(503, json={}),
        httpx.Response(503, json={}),
        httpx.Response(503, json={}),
    ]
    async with httpx.AsyncClient() as client:
        v = PolymarketVenue(
            client=client, clock=_clock(), backoff_base_sec=0.001, backoff_max_sec=0.001
        )
        with pytest.raises(VenueUnreachableError):
            await v.list_active_markets()


@pytest.mark.asyncio
@respx.mock
async def test_get_book_parses_payload() -> None:
    payload = {
        "bids": [{"price": "0.49", "size": "100"}, {"price": "0.48", "size": "50"}],
        "asks": [{"price": "0.51", "size": "100"}, {"price": "0.52", "size": "50"}],
    }
    respx.get(f"{CLOB_BASE}/book").mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as client:
        v = PolymarketVenue(client=client, clock=_clock())
        book = await v.get_book("tok-yes-0")
    assert len(book.bids) == 2
    assert book.midpoint == (book.bids[0][0] + book.asks[0][0]) / 2
    assert book.venue == VenueName.POLYMARKET


@pytest.mark.asyncio
@respx.mock
async def test_health_check_ok() -> None:
    respx.get(f"{GAMMA_BASE}/markets").mock(return_value=httpx.Response(200, json=[]))
    async with httpx.AsyncClient() as client:
        v = PolymarketVenue(client=client, clock=_clock())
        health = await v.health_check()
    assert health.status == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_health_check_error() -> None:
    route = respx.get(f"{GAMMA_BASE}/markets")
    route.side_effect = [httpx.Response(503, json={})] * 5
    async with httpx.AsyncClient() as client:
        v = PolymarketVenue(client=client, clock=_clock(), max_retries=1, backoff_base_sec=0.001)
        health = await v.health_check()
    assert health.status == "error"


@pytest.mark.asyncio
async def test_is_market_open_always_true() -> None:
    async with httpx.AsyncClient() as client:
        v = PolymarketVenue(client=client, clock=_clock())
        assert await v.is_market_open() is True
