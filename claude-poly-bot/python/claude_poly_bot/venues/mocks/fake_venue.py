"""In-memory FakeVenue for tests + local DRY_RUN exercise.

Configurable behaviors: scripted markets/books, market-open toggle,
disconnect simulation. Production-equivalent surface for the read-only
operations needed by M1; M3+ adds order placement.

Traces: REQ-VEN-008.
"""

from __future__ import annotations

from datetime import UTC, datetime

from claude_poly_bot.domain.clock import Clock
from claude_poly_bot.domain.models import (
    Book,
    Geo,
    Market,
    VenueName,
)
from claude_poly_bot.domain.protocols import HealthStatus


class FakeVenue:
    """Implements the read-only Venue surface in pure memory."""

    def __init__(
        self,
        name: VenueName,
        clock: Clock,
        *,
        markets: list[Market] | None = None,
        books: dict[str, Book] | None = None,
        is_open: bool = True,
        list_active_should_raise: Exception | None = None,
    ) -> None:
        self.name = name
        self._clock = clock
        self._markets: list[Market] = list(markets) if markets else []
        self._books: dict[str, Book] = dict(books) if books else {}
        self._is_open = is_open
        self._raise_on_list = list_active_should_raise

    # ---- Test helpers (not part of Venue Protocol) ----

    def add_market(self, market: Market) -> None:
        self._markets.append(market)

    def set_book(self, market_id: str, book: Book) -> None:
        self._books[market_id] = book

    def set_market_open(self, is_open: bool) -> None:
        self._is_open = is_open

    def set_list_active_error(self, exc: Exception | None) -> None:
        self._raise_on_list = exc

    # ---- Venue Protocol ----

    async def list_active_markets(self, *, geo: Geo | None = None) -> list[Market]:
        if self._raise_on_list is not None:
            raise self._raise_on_list
        if geo is None:
            return list(self._markets)
        return [m for m in self._markets if m.geo is None or m.geo == geo]

    async def get_book(self, market_id: str) -> Book:
        try:
            return self._books[market_id]
        except KeyError as e:
            raise KeyError(f"FakeVenue has no book for {market_id}") from e

    async def is_market_open(self) -> bool:
        return self._is_open

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            status="ok",
            latency_ms=0.0,
            checked_at=datetime.now(UTC) if not hasattr(self._clock, "now") else self._clock.now(),
        )
