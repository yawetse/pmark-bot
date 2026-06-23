"""Cross-module port definitions (Protocols).

Adapters in venues/, llm/, storage/, observability/, wallet/ implement
these. Domain code only refers to ports — never to concrete implementations.

M1 scope: Venue (read-only subset) + HealthStatus dataclass.
M2 scope: Strategist + StrategistContext + NewsSnippet.

Traces: REQ-VEN-001..008, REQ-LLM-001, HLD §3.1 hexagonal architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict

from claude_poly_bot.domain.models import (
    Book,
    Bot,
    CheckResult,
    CheckType,
    Geo,
    Market,
    ScanScore,
    SubAgent,
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


# ---------------------------------------------------------------------------
# Strategist port — LLM adapter (REQ-LLM-001)
# ---------------------------------------------------------------------------


class NewsSnippet(BaseModel):
    """One news result available to a strategist call."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    title: str
    source: str
    url: str | None = None
    published_at: AwareDatetime | None = None
    excerpt: str | None = None


class StrategistContext(BaseModel):
    """Bundle of per-call inputs passed alongside the Market to `evaluate`.

    Per-check inputs:
    - `target_wallets_hits`: Polymarket whale check input (REQ-BRN-003).
    - `unusual_volume`: Alpaca unusual_volume check input (REQ-BRN-004).
    - `recent_news`: surfaced for prompts; may be empty (model may invoke
      its own web_search tool when enabled).
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    book: Book | None
    scan_score: ScanScore
    target_wallets_hits: int | None = None
    unusual_volume: Decimal | None = None
    recent_news: list[NewsSnippet] = []
    historical_analogs: list[str] = []
    prior_check_results: list[CheckResult] = []


@runtime_checkable
class Strategist(Protocol):
    """LLM strategist port. Concrete impls: AnthropicStrategist,
    OpenAIStrategist (M6), FakeStrategist (tests).

    `bot` identifies which side of the comparison this adapter represents.
    """

    bot: Bot

    async def evaluate(
        self,
        check_type: CheckType,
        venue: VenueName,
        market: Market,
        context: StrategistContext,
        *,
        sub_agent: SubAgent | None = None,
        web_search: bool = False,
        model_id: str | None = None,
    ) -> CheckResult:
        """Run one LLM call. Never raises on provider error — returns a
        SKIP CheckResult with `error` populated (REQ-LLM-008). The sole
        exception is sustained-error halt, which propagates so the bot
        loop can stop decisioning (REQ-BRN-015).
        """
        ...

    async def consecutive_error_count(self) -> int:
        """Current consecutive-error count for halt monitoring (REQ-BRN-015)."""
        ...
