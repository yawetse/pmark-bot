"""Polymarket Venue adapter — read paths only.

Implements the read subset of the Venue Protocol against the Polymarket
gamma + clob HTTP APIs. Order signing / placement lands in M4 (TASK-005);
WebSocket subscription lands in M5 (TASK-006).

Traces: REQ-POLY-001..006, REQ-VEN-002 (Polymarket variant), HLD §3.4.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from claude_poly_bot.domain.clock import Clock
from claude_poly_bot.domain.exceptions import VenueUnreachableError
from claude_poly_bot.domain.models import (
    Book,
    Geo,
    Market,
    PolymarketMarket,
    Price,
    VenueName,
)
from claude_poly_bot.domain.protocols import HealthStatus

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DEFAULT_TIMEOUT_SEC = 10.0


class PolymarketVenue:
    """Polymarket implementation of the Venue Protocol (read subset).

    Construct one per bot/process. Holds a single httpx.AsyncClient.
    """

    name = VenueName.POLYMARKET

    def __init__(
        self,
        client: httpx.AsyncClient,
        clock: Clock,
        *,
        gamma_base: str = GAMMA_BASE,
        clob_base: str = CLOB_BASE,
        max_retries: int = 3,
        backoff_base_sec: float = 0.5,
        backoff_max_sec: float = 4.0,
    ) -> None:
        self._client = client
        self._clock = clock
        self._gamma = gamma_base.rstrip("/")
        self._clob = clob_base.rstrip("/")
        self._max_retries = max_retries
        self._backoff_base = backoff_base_sec
        self._backoff_max = backoff_max_sec

    # REQ: REQ-POLY-003 - REST polling for market lists.
    # REQ: REQ-VEN-001 - list_active_markets returns Markets.
    async def list_active_markets(self, *, geo: Geo | None = None) -> list[Market]:
        markets: list[Market] = []
        offset = 0
        page_size = 500
        while True:
            url = f"{self._gamma}/markets"
            params: dict[str, str | int] = {
                "active": "true",
                "closed": "false",
                "limit": page_size,
                "offset": offset,
            }
            data = await self._get_json(url, params=params)
            items: list[Any] = []
            if isinstance(data, list):
                items = list(data)
            elif isinstance(data, dict):
                # Some Polymarket API revisions wrap results in `{"data": [...]}`
                wrapped = data.get("data")
                if isinstance(wrapped, list):
                    items = list(wrapped)
            if not items:
                break
            for item in items:
                if isinstance(item, dict):
                    parsed = self._parse_market(item, geo)
                    if parsed is not None:
                        markets.append(parsed)
            if len(items) < page_size:
                break
            offset += page_size
            # Defensive guard: don't iterate forever on a misbehaving API.
            if offset >= 5000:
                logger.warning("polymarket_pagination_cap_hit", extra={"offset": offset})
                break
        return markets

    async def get_book(self, market_id: str) -> Book:
        """Fetch the order book for a given CLOB token id."""
        url = f"{self._clob}/book"
        data: Any = await self._get_json(url, params={"token_id": market_id})
        if not isinstance(data, dict):
            data = {}
        bids: list[tuple[Decimal, int]] = [
            (Price(Decimal(level["price"])), int(Decimal(level["size"])))
            for level in data.get("bids") or []
        ]
        asks: list[tuple[Decimal, int]] = [
            (Price(Decimal(level["price"])), int(Decimal(level["size"])))
            for level in data.get("asks") or []
        ]
        # Midpoint = (best_bid + best_ask) / 2, or 0.5 fallback if either side empty
        if bids and asks:
            best_bid = bids[0][0]
            best_ask = asks[0][0]
            midpoint = Price((Decimal(best_bid) + Decimal(best_ask)) / Decimal(2))
        else:
            midpoint = Price(Decimal("0.5"))
        return Book(
            venue=VenueName.POLYMARKET,
            market_id=market_id,
            bids=bids,
            asks=asks,
            midpoint=midpoint,
            timestamp=self._clock.now(),
        )

    async def is_market_open(self) -> bool:
        """Polymarket trades 24/7; markets resolve individually but the
        venue itself is always open."""
        return True

    async def health_check(self) -> HealthStatus:
        started = self._clock.now()
        try:
            await self._get_json(f"{self._gamma}/markets", params={"limit": 1})
        except VenueUnreachableError as e:
            return HealthStatus(
                status="error",
                latency_ms=(self._clock.now() - started).total_seconds() * 1000,
                checked_at=self._clock.now(),
                error=str(e),
            )
        return HealthStatus(
            status="ok",
            latency_ms=(self._clock.now() - started).total_seconds() * 1000,
            checked_at=self._clock.now(),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    # REQ: REQ-POLY-005 - exponential-backoff retry up to max_retries.
    # REQ: REQ-SCAN-007 - scanner-side retry behavior on 5xx.
    async def _get_json(
        self, url: str, *, params: dict[str, str | int] | None = None
    ) -> dict[str, Any] | list[Any]:
        attempt = 1
        delay = self._backoff_base
        last_exc: Exception | None = None
        while attempt <= self._max_retries:
            try:
                resp = await self._client.get(url, params=params, timeout=DEFAULT_TIMEOUT_SEC)
                if resp.status_code >= 500:
                    raise VenueUnreachableError(f"Polymarket {url} returned {resp.status_code}")
                resp.raise_for_status()
                parsed = resp.json()
                # Defensive cast for mypy strict — Polymarket returns
                # either a list (markets endpoint) or a dict (book).
                if isinstance(parsed, list | dict):
                    return parsed
                raise VenueUnreachableError(f"Polymarket {url} returned non-JSON-object body")
            except (httpx.HTTPError, VenueUnreachableError) as e:
                last_exc = e
                if attempt >= self._max_retries:
                    break
                logger.warning(
                    "polymarket_get_retry",
                    extra={"url": url, "attempt": attempt, "error": str(e)},
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._backoff_max)
                attempt += 1
        raise VenueUnreachableError(f"Polymarket {url} unreachable: {last_exc}")

    def _parse_market(
        self, item: dict[str, Any], geo_filter: Geo | None
    ) -> PolymarketMarket | None:
        """Map Polymarket gamma response item → PolymarketMarket. Skip
        items that fail validation (logged, not raised)."""
        try:
            external_id = str(item.get("id") or item.get("conditionId") or "")
            if not external_id:
                return None
            question = str(item.get("question") or item.get("description") or "")
            resolution_rules = str(item.get("description") or "")
            end_date_raw = item.get("endDate") or item.get("end_date_iso")
            if not end_date_raw:
                return None
            resolution_time = datetime.fromisoformat(str(end_date_raw).replace("Z", "+00:00"))
            if resolution_time.tzinfo is None:
                resolution_time = resolution_time.replace(tzinfo=UTC)
            outcomes_raw = item.get("outcomes") or '["YES","NO"]'
            outcomes_list = (
                outcomes_raw if isinstance(outcomes_raw, list) else _safe_json_list(outcomes_raw)
            )
            outcomes: list[str] = [str(o) for o in outcomes_list]
            token_ids_raw = item.get("clobTokenIds") or item.get("clob_token_ids") or "[]"
            token_id_list = (
                token_ids_raw if isinstance(token_ids_raw, list) else _safe_json_list(token_ids_raw)
            )
            token_ids: dict[str, str] = {
                outcomes[i]: str(tok) for i, tok in enumerate(token_id_list) if i < len(outcomes)
            }
            # Geo filter: Polymarket returns a single feed; per-market geo
            # restrictions surface as `geoBlockedCountries`. For M1 we accept
            # all markets; precise geo is enforced at order-placement time
            # (M4) when Polymarket itself rejects geo-blocked orders.
            geo: Geo | None = geo_filter  # passthrough
            return PolymarketMarket(
                external_id=external_id,
                name=question[:200],
                geo=geo,
                created_at=self._clock.now(),
                question=question,
                resolution_rules=resolution_rules,
                resolution_time=resolution_time,
                outcomes=outcomes,
                token_ids=token_ids,
            )
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("polymarket_parse_skip", extra={"error": str(e)})
            return None


def _safe_json_list(s: object) -> list[object]:
    """Polymarket returns nested JSON arrays as JSON-encoded strings on
    some endpoints. Return [] on any parse failure rather than raising."""
    import json

    if not isinstance(s, str):
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
