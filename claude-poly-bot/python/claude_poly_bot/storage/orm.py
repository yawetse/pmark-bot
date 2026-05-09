"""SQLAlchemy ORM tables.

M1 scope: only candidate_queue and market_scans. Other tables (orders,
positions, trades, decisions, etc.) land with their respective milestones.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, Index, Integer, Numeric, String, Text
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


# Surface for Alembic autogenerate / programmatic migration usage in M1+.
target_metadata = Base.metadata


# Silence unused-import warnings for types kept for future migrations
_ = (Decimal, NUMERIC_24_8)
