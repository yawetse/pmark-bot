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
from typing import Annotated, Literal
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
