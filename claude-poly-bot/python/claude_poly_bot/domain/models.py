"""Domain models — Pydantic v2 frozen data contracts.

This module is pure: no I/O, no time-of-day reads (use the Clock port).
Money/Price/Probability use Decimal everywhere.

M1 scope: enums + Polymarket market + Book + ScanScore + Candidate +
MarketScanRun. Other models (Order, Position, Thesis, etc.) land with
their respective milestones.

Traces: REQ-SCAN-005, REQ-SCAN-008, REQ-VEN-001, REQ-CFG-001 (subset).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Bot(StrEnum):
    """Identifies the LLM-driven bot."""

    CLAUDE = "claude"
    OPENAI = "openai"


class VenueName(StrEnum):
    """Trading venue identifier. Underpins the Venue port."""

    POLYMARKET = "polymarket"
    ALPACA = "alpaca"


class Geo(StrEnum):
    """Polymarket geo segment. Default US per spec."""

    US = "us"
    INTERNATIONAL = "international"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class Verdict(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    SKIP = "SKIP"


class CheckType(StrEnum):
    """The 4 brain checks. `whale` runs on Polymarket; `unusual_volume` on Alpaca."""

    BASE_RATE = "base_rate"
    NEWS = "news"
    WHALE = "whale"
    UNUSUAL_VOLUME = "unusual_volume"
    DISPOSITION = "disposition"


class SubAgent(StrEnum):
    """The 3 strategy sub-agents that vote on size."""

    ARBITRAGE = "arbitrage"
    CONVERGENCE = "convergence"
    WHALE_COPY = "whale_copy"  # Polymarket
    FLOW_COPY = "flow_copy"  # Alpaca


class ClaimStatus(StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Decimal aliases
# ---------------------------------------------------------------------------

# REQ: HLD DD-004 - decimal everywhere for money/prices.
Money = Annotated[Decimal, Field(ge=0, decimal_places=8, max_digits=24)]
Probability = Annotated[Decimal, Field(ge=0, le=1, decimal_places=8)]
Price = Annotated[Decimal, Field(ge=0, decimal_places=8)]


# ---------------------------------------------------------------------------
# Base config for frozen, strict, extras-forbidden models
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    """Frozen Pydantic models. Construct-once, never mutate.

    `strict=True` rejects float→Decimal and naive datetimes by default.
    `extra='forbid'` ensures schema drift surfaces as ValidationError.
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------


class Market(_Frozen):
    """Base market type. Discriminator for venue-specific subclasses."""

    venue: VenueName
    external_id: str
    name: str
    geo: Geo | None = None
    created_at: AwareDatetime


class PolymarketMarket(Market):
    """Polymarket prediction market."""

    venue: Literal[VenueName.POLYMARKET] = VenueName.POLYMARKET
    question: str
    resolution_rules: str
    resolution_time: AwareDatetime
    outcomes: list[str]
    token_ids: dict[str, str]


class AlpacaMarket(Market):
    """Alpaca equity instrument. Land in M7 but enum is here for parity."""

    venue: Literal[VenueName.ALPACA] = VenueName.ALPACA
    ticker: str
    sector: str | None = None
    last_earnings_date: date | None = None
    shares_outstanding: int | None = None
    is_etf: bool = False


# ---------------------------------------------------------------------------
# Book / Score
# ---------------------------------------------------------------------------


class Book(_Frozen):
    """Top-of-book + depth snapshot. For Alpaca, bids/asks have one entry each."""

    venue: VenueName
    market_id: str
    bids: list[tuple[Price, int]]
    asks: list[tuple[Price, int]]
    midpoint: Price
    timestamp: AwareDatetime


class PolymarketScoreFields(_Frozen):
    """Score fields specific to Polymarket markets."""

    venue: Literal[VenueName.POLYMARKET] = VenueName.POLYMARKET
    gap: Decimal
    depth: Money
    hours_to_resolution: Decimal


class AlpacaScoreFields(_Frozen):
    """Score fields specific to Alpaca instruments. Lands fully in M7."""

    venue: Literal[VenueName.ALPACA] = VenueName.ALPACA
    relative_volume: Decimal
    price_momentum: Decimal
    dollar_volume: Money
    last_price: Price


class ScanScore(_Frozen):
    """Per-market scoring outcome with venue-specific fields and accept/reject."""

    market_id: str
    venue: VenueName
    fields: PolymarketScoreFields | AlpacaScoreFields
    accepted: bool
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def _venue_matches_fields(self) -> ScanScore:
        if self.venue != self.fields.venue:
            raise ValueError(
                f"ScanScore.venue ({self.venue}) must match fields.venue ({self.fields.venue})"
            )
        if self.accepted and self.rejection_reason is not None:
            raise ValueError("Accepted scan score must not have a rejection_reason")
        return self


# ---------------------------------------------------------------------------
# Candidate / Scan run
# ---------------------------------------------------------------------------


class Candidate(_Frozen):
    """Scanner output published to candidate_queue for both bots to consume."""

    scan_correlation_id: UUID = Field(default_factory=uuid4)
    venue: VenueName
    market_id: str
    market_snapshot: PolymarketMarket | AlpacaMarket
    book_snapshot: Book | None = None
    scan_score: ScanScore
    created_at: AwareDatetime


class MarketScanRun(_Frozen):
    """Per-scan-run summary persisted for dashboard health (REQ-SCAN-008)."""

    scan_correlation_id: UUID = Field(default_factory=uuid4)
    venue: VenueName
    started_at: AwareDatetime
    ended_at: AwareDatetime
    fetched: int
    accepted: int
    rejected: int
    error: str | None = None


# ---------------------------------------------------------------------------
# Brain models — CheckResult, Thesis, CandidateClaim, TargetWallet
# ---------------------------------------------------------------------------


class CheckResult(_Frozen):
    """Output of one LLM call (one check or one sub-agent vote).

    Stored verbatim in the `decisions` table — every field maps to a
    column for the comparison-experiment query surface.
    """

    bot: Bot
    venue: VenueName
    market_id: str
    check_type: CheckType
    sub_agent: SubAgent | None = None
    verdict: Verdict
    confidence: Probability
    p_win: Probability
    rationale: str
    model_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    cost_usd: Money = Decimal("0")
    latency_ms: int = 0
    web_search_used: bool = False
    correlation_id: UUID
    raw_response: dict[str, Any] | None = None
    error: str | None = None


class Thesis(_Frozen):
    """Aggregated decision: 4 checks consensus + 3 sub-agents consensus.

    Persisted in `theses` table; downstream `executor` consumes.
    Traces: REQ-BRN-009, DD-019.
    """

    id: UUID = Field(default_factory=uuid4)
    bot: Bot
    venue: VenueName
    market_id: str
    verdict: Verdict
    p_win: Probability
    confidence: Probability
    size_multiplier: Literal["FULL", "HALF", "SKIP"]
    target_price: Price | None = None  # Alpaca only
    stop_price: Price | None = None  # Alpaca only
    horizon_hours: int | None = None  # Alpaca only
    scan_correlation_id: UUID
    decision_correlation_id: UUID
    created_at: AwareDatetime


class CandidateClaim(_Frozen):
    """Per-(candidate, bot) claim row implementing DD-017.

    Both bots independently process every accepted candidate; their
    progress is tracked here.
    """

    scan_correlation_id: UUID
    bot: Bot
    status: ClaimStatus
    decision_correlation_id: UUID
    claimed_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    error: str | None = None


class TargetWallet(_Frozen):
    """A Polymarket wallet flagged by daily data refresh as smart-money.

    Whale-check input; daily-refresh job upserts the full set.
    Traces: REQ-DATA-007.
    """

    address: str
    total_trades: int
    win_rate: Probability
    total_pnl: Money
    refreshed_at: AwareDatetime
