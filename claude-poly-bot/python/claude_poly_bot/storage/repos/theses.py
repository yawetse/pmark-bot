"""Theses repository.

Traces: REQ-BRN-009 (persist generated thesis), DD-019 (decision_correlation_id).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claude_poly_bot.domain.models import (
    Bot,
    Price,
    Probability,
    Thesis,
    VenueName,
    Verdict,
)
from claude_poly_bot.storage.orm import Theses


class SqlAlchemyThesisRepo:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def save(self, thesis: Thesis) -> None:
        async with self._sm() as session, session.begin():
            session.add(
                Theses(
                    id=thesis.id,
                    bot=thesis.bot.value,
                    venue=thesis.venue.value,
                    market_id=thesis.market_id,
                    verdict=thesis.verdict.value,
                    p_win=thesis.p_win,
                    confidence=thesis.confidence,
                    size_multiplier=thesis.size_multiplier,
                    target_price=thesis.target_price,
                    stop_price=thesis.stop_price,
                    horizon_hours=thesis.horizon_hours,
                    scan_correlation_id=thesis.scan_correlation_id,
                    decision_correlation_id=thesis.decision_correlation_id,
                    created_at=thesis.created_at,
                )
            )

    async def get(self, id: UUID) -> Thesis | None:
        async with self._sm() as session:
            row = (
                await session.execute(select(Theses).where(Theses.id == id))
            ).scalar_one_or_none()
            if row is None:
                return None
            return _to_thesis(row)

    async def list_pending_for_bot(self, bot: Bot, *, limit: int = 50) -> list[Thesis]:
        """Theses produced but not yet executed (executed_at IS NULL)."""
        async with self._sm() as session:
            rows = (
                (
                    await session.execute(
                        select(Theses)
                        .where(Theses.bot == bot.value, Theses.executed_at.is_(None))
                        .order_by(Theses.created_at)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [_to_thesis(r) for r in rows]

    async def mark_executed(self, id: UUID) -> None:
        async with self._sm() as session, session.begin():
            await session.execute(
                update(Theses).where(Theses.id == id).values(executed_at=datetime.now(UTC))
            )


def _to_thesis(r: Theses) -> Thesis:
    size = r.size_multiplier
    return Thesis(
        id=r.id,
        bot=Bot(r.bot),
        venue=VenueName(r.venue),
        market_id=r.market_id,
        verdict=Verdict(r.verdict),
        p_win=Probability(r.p_win),
        confidence=Probability(r.confidence),
        size_multiplier=cast(Literal["FULL", "HALF", "SKIP"], size),
        target_price=Price(r.target_price) if r.target_price is not None else None,
        stop_price=Price(r.stop_price) if r.stop_price is not None else None,
        horizon_hours=r.horizon_hours,
        scan_correlation_id=r.scan_correlation_id,
        decision_correlation_id=r.decision_correlation_id,
        created_at=r.created_at,
    )
