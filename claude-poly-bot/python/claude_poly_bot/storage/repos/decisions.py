"""Decisions repository — every LLM call persists one row.

Traces: REQ-BRN-007.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claude_poly_bot.domain.models import (
    Bot,
    CheckResult,
    CheckType,
    Probability,
    SubAgent,
    VenueName,
    Verdict,
)
from claude_poly_bot.storage.orm import Decisions


class SqlAlchemyDecisionRepo:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    # REQ: REQ-BRN-007 - persist every LLM call.
    async def record(self, result: CheckResult, *, thesis_id: UUID | None = None) -> UUID:
        decision_id = uuid4()
        async with self._sm() as session, session.begin():
            session.add(
                Decisions(
                    id=decision_id,
                    bot=result.bot.value,
                    venue=result.venue.value,
                    market_id=result.market_id,
                    check_type=result.check_type.value,
                    sub_agent=result.sub_agent.value if result.sub_agent else None,
                    verdict=result.verdict.value,
                    confidence=result.confidence,
                    p_win=result.p_win,
                    rationale=result.rationale,
                    model_id=result.model_id,
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    tokens_cached=result.tokens_cached,
                    cost_usd=result.cost_usd,
                    latency_ms=result.latency_ms,
                    web_search_used=result.web_search_used,
                    correlation_id=result.correlation_id,
                    raw_response=result.raw_response,
                    error=result.error,
                    created_at=datetime.now(UTC),
                    thesis_id=thesis_id,
                )
            )
        return decision_id

    async def list_for_correlation(self, correlation_id: UUID) -> list[CheckResult]:
        async with self._sm() as session:
            rows = (
                (
                    await session.execute(
                        select(Decisions).where(Decisions.correlation_id == correlation_id)
                    )
                )
                .scalars()
                .all()
            )
        return [_to_check_result(r) for r in rows]


def _to_check_result(r: Decisions) -> CheckResult:
    return CheckResult(
        bot=Bot(r.bot),
        venue=VenueName(r.venue),
        market_id=r.market_id,
        check_type=CheckType(r.check_type),
        sub_agent=SubAgent(r.sub_agent) if r.sub_agent else None,
        verdict=Verdict(r.verdict),
        confidence=Probability(r.confidence),
        p_win=Probability(r.p_win),
        rationale=r.rationale,
        model_id=r.model_id,
        tokens_in=r.tokens_in,
        tokens_out=r.tokens_out,
        tokens_cached=r.tokens_cached,
        cost_usd=r.cost_usd,
        latency_ms=r.latency_ms,
        web_search_used=r.web_search_used,
        correlation_id=r.correlation_id,
        raw_response=r.raw_response,
        error=r.error,
    )
