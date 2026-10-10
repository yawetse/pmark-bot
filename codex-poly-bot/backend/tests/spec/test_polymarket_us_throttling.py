"""Synthetic regressions for stopping US order-book reads after throttling."""

from datetime import UTC, datetime

import httpx
import pytest

from app.domain import Venue
from app.services.market_data_provider import ProviderBackedMarketDataFetcher


def _fetcher(statuses: list[int], *, market_count: int = 20):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/markets":
            offset = int(request.url.params["offset"])
            limit = int(request.url.params["limit"])
            return httpx.Response(200, json={"markets": [
                {
                    "id": f"market-{index:04d}",
                    "slug": f"market-{index:04d}",
                    "question": "Synthetic market",
                    "endDate": "2026-11-01T12:00:00Z",
                    "active": True,
                    "closed": False,
                    "hidden": False,
                    "ep3Status": "OPEN",
                    "marketSides": [{"id": f"side-{index}", "description": "Yes", "long": True, "tradable": True}],
                }
                for index in range(offset, min(offset + limit, market_count))
            ]})
        assert request.url.path.endswith("/book")
        slug = request.url.path.removeprefix("/v1/markets/").removesuffix("/book")
        status = statuses[len(calls)] if len(calls) < len(statuses) else 200
        calls.append(slug)
        if status != 200:
            return httpx.Response(status, headers={"Retry-After": "60"}, json={"message": "Synthetic error"})
        return httpx.Response(200, json={"marketData": {
            "marketSlug": slug,
            "transactTime": "2026-10-08T12:00:00Z",
            "bids": [{"px": {"value": "0.44", "currency": "USD"}, "qty": "1000"}],
            "offers": [{"px": {"value": "0.46", "currency": "USD"}, "qty": "1000"}],
        }})

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "POLYMARKET_GATEWAY_BASE_URL": "https://synthetic.invalid",
            "POLYMARKET_US_MARKET_SOURCE_LIMIT": str(market_count),
            "POLYMARKET_US_MARKET_PAGE_SIZE": "100",
        },
        transport=httpx.MockTransport(handler),
    )
    return fetcher, calls


def _pull(fetcher, *, limit: int = 25):
    return fetcher.fetch(
        venue=Venue.POLYMARKET_US.value,
        config_payload={"scanner": {"polymarket": {"market_data_limit": limit}}},
        pulled_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
    )


@pytest.mark.parametrize("successful_books", [0, 1, 9])
def test_us_throttle_stops_remaining_books_and_keeps_partial_candidates(successful_books):
    fetcher, calls = _fetcher([200] * successful_books + [429] * (1000 - successful_books), market_count=1000)
    result = _pull(fetcher)

    assert len(calls) == successful_books + 1
    assert result.status == ("partial" if successful_books else "rate_limited")
    assert result.error_code == "provider_rate_limited"
    assert [candidate["marketSlug"] for candidate in result.candidates] == calls[:-1]
    assert "coverage is incomplete" in result.message
    assert "Retry on a later pull" in result.message


def test_us_throttle_after_another_error_reports_throttling_and_preserves_successes():
    fetcher, calls = _fetcher([500, 200, 429])
    result = _pull(fetcher)

    assert len(calls) == 3
    assert result.status == "partial"
    assert result.error_code == "provider_rate_limited"
    assert [candidate["marketSlug"] for candidate in result.candidates] == ["market-0001"]
    assert "2 provider calls failed" in result.message


def test_us_non_throttle_errors_continue_and_keep_original_partial_status():
    fetcher, calls = _fetcher([500, 200, 404, 200])
    result = _pull(fetcher, limit=2)

    assert len(calls) == 4
    assert result.status == "partial"
    assert result.error_code == "provider_http_500"
    assert [candidate["marketSlug"] for candidate in result.candidates] == ["market-0001", "market-0003"]
    assert "Retry on a later pull" not in result.message


def test_us_success_still_stops_at_candidate_cap_and_preserves_order_and_prices():
    fetcher, calls = _fetcher([])
    result = _pull(fetcher, limit=2)

    assert calls == ["market-0000", "market-0001"]
    assert result.status == "pulled"
    assert result.error_code is None
    assert [candidate["marketSlug"] for candidate in result.candidates] == calls
    assert result.candidates[0]["bestBid"] == "0.44"
    assert result.candidates[0]["bestAsk"] == "0.46"


def test_us_later_pull_can_recover_without_sticky_failure_or_immediate_retry():
    fetcher, calls = _fetcher([429])
    first = _pull(fetcher, limit=2)
    assert first.status == "rate_limited"
    assert len(calls) == 1

    later = _pull(fetcher, limit=2)
    assert later.status == "pulled"
    assert calls == ["market-0000", "market-0000", "market-0001"]
    assert later.error_code is None
