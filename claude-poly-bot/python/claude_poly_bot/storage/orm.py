"""SQLAlchemy ORM tables.

M1: candidate_queue, market_scans.
M2: candidate_claims, decisions, theses, target_wallets.
Other tables (orders, positions, trades, etc.) land with their milestones.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NUMERIC_24_8 = Numeric(precision=24, scale=8)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM tables."""


class CandidateQueue(Base):
    """Markets accepted by the scanner; both bots independently consume.

    Traces: REQ-SCAN-005.
    """

    __tablename__ = "candidate_queue"

    scan_correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    market_id: Mapped[str] = mapped_column(String(128), nullable=False)
    market_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    book_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    scan_score: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_candidate_queue_venue_created", "venue", "created_at"),)


class MarketScanRunRow(Base):
    """Per-scan-run summary row used by the dashboard's market scans page.

    Traces: REQ-SCAN-008.
    """

    __tablename__ = "market_scans"

    scan_correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_market_scans_venue_started", "venue", "started_at"),)


class CandidateClaims(Base):
    """Per-(candidate, bot) claim row implementing DD-017.

    Each scanner-produced candidate gets one row per bot. Bots independently
    transition status NEW → PROCESSING → DONE / ERROR.
    """

    __tablename__ = "candidate_claims"

    scan_correlation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("candidate_queue.scan_correlation_id"),
        nullable=False,
    )
    bot: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    decision_correlation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("scan_correlation_id", "bot", name="pk_candidate_claims"),
        Index("ix_candidate_claims_bot_status", "bot", "status"),
    )


class Decisions(Base):
    """One LLM call → one row. Stores prompt/response context for the
    Claude-vs-OpenAI comparison query surface (REQ-BRN-007)."""

    __tablename__ = "decisions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    bot: Mapped[str] = mapped_column(String(16), nullable=False)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    market_id: Mapped[str] = mapped_column(String(128), nullable=False)
    check_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sub_agent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verdict: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(NUMERIC_24_8, nullable=False)
    p_win: Mapped[Decimal] = mapped_column(NUMERIC_24_8, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_cached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(NUMERIC_24_8, nullable=False, default=Decimal(0))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    web_search_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    thesis_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("theses.id"), nullable=True
    )

    __table_args__ = (
        Index("ix_decisions_bot_venue_created", "bot", "venue", "created_at"),
        Index("ix_decisions_correlation", "correlation_id"),
        Index("ix_decisions_thesis_id", "thesis_id"),
    )


class Theses(Base):
    """Aggregated decision per (candidate, bot)."""

    __tablename__ = "theses"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    bot: Mapped[str] = mapped_column(String(16), nullable=False)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    market_id: Mapped[str] = mapped_column(String(128), nullable=False)
    verdict: Mapped[str] = mapped_column(String(8), nullable=False)
    p_win: Mapped[Decimal] = mapped_column(NUMERIC_24_8, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(NUMERIC_24_8, nullable=False)
    size_multiplier: Mapped[str] = mapped_column(String(8), nullable=False)
    target_price: Mapped[Decimal | None] = mapped_column(NUMERIC_24_8, nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(NUMERIC_24_8, nullable=True)
    horizon_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scan_correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    decision_correlation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_theses_bot_venue_created", "bot", "venue", "created_at"),
        Index("ix_theses_pending", "bot", "executed_at"),
    )


class TargetWallets(Base):
    """Top-N Polymarket wallets passing daily-refresh thresholds."""

    __tablename__ = "target_wallets"

    address: Mapped[str] = mapped_column(String(64), primary_key=True)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    win_rate: Mapped[Decimal] = mapped_column(NUMERIC_24_8, nullable=False)
    total_pnl: Mapped[Decimal] = mapped_column(NUMERIC_24_8, nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# Surface for Alembic autogenerate / programmatic migration usage in M1+.
target_metadata = Base.metadata


# Silence unused-import warnings for types kept for future migrations
_ = (Decimal, NUMERIC_24_8)
