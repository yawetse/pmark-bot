"""Cross-module port definitions (Protocols).

Adapters in venues/, llm/, storage/, observability/, wallet/ implement
these. Domain code only refers to ports — never to concrete implementations.

M1 scope: Venue (read-only subset) + HealthStatus dataclass. Other ports
land with their respective milestones.

Traces: REQ-VEN-001..008, HLD §3.1 hexagonal architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from claude_poly_bot.domain.models import (
    Book,
    Geo,
    Market,
    VenueName,
)


@dataclass(frozen=True)
class HealthStatus:
    """Per-venue health probe result returned by `Venue.health_check`."""

    status: str  # "ok" | "degraded" | "error"
    latency_ms: float
    checked_at: datetime
    error: str | None = None


@runtime_checkable
class Venue(Protocol):
    """Trading venue port. Concrete implementations: PolymarketVenue,
    AlpacaVenue, FakeVenue.

    M1 surface is read-only; place_order/cancel_order/get_positions land
    with M3-M4 (executor + real Polymarket execution).
    """

    name: VenueName

    async def list_active_markets(self, *, geo: Geo | None = None) -> list[Market]:
        """Return all active markets, optionally filtered by geo (Polymarket only)."""
        ...

    async def get_book(self, market_id: str) -> Book:
        """Fetch the current order book for a single market."""
        ...

    async def is_market_open(self) -> bool:
        """True if the venue is currently accepting trades."""
        ...

    async def health_check(self) -> HealthStatus:
        """Light probe used by the dashboard health page."""
        ...
