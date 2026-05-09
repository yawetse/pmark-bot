"""Market-scan-runs repository.

Persists per-scan summary rows for the dashboard's `/markets/scans` page.

Traces: REQ-SCAN-008.
"""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claude_poly_bot.domain.models import MarketScanRun, VenueName
from claude_poly_bot.storage.orm import MarketScanRunRow


class SqlAlchemyMarketScanRepo:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    # REQ: REQ-SCAN-008 - record scan-run summary.
    async def record(self, run: MarketScanRun) -> None:
        async with self._sm() as session, session.begin():
            session.add(
                MarketScanRunRow(
                    scan_correlation_id=run.scan_correlation_id,
                    venue=run.venue.value,
                    started_at=run.started_at,
                    ended_at=run.ended_at,
                    fetched=run.fetched,
                    accepted=run.accepted,
                    rejected=run.rejected,
                    error=run.error,
                )
            )

    async def list_recent(
        self, venue: VenueName | None = None, *, limit: int = 50
    ) -> list[MarketScanRun]:
        """Most-recent-first list for the dashboard."""
        async with self._sm() as session:
            stmt = select(MarketScanRunRow).order_by(desc(MarketScanRunRow.started_at)).limit(limit)
            if venue is not None:
                stmt = stmt.where(MarketScanRunRow.venue == venue.value)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                MarketScanRun(
                    scan_correlation_id=r.scan_correlation_id,
                    venue=VenueName(r.venue),
                    started_at=r.started_at,
                    ended_at=r.ended_at,
                    fetched=r.fetched,
                    accepted=r.accepted,
                    rejected=r.rejected,
                    error=r.error,
                )
                for r in rows
            ]
