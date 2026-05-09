"""Candidate-queue repository — publish + queue depth.

M1 surface: just `publish` and `queue_depth`. `claim_next` (per-bot
candidate_claims) lands in M2 alongside the brain loop.

Traces: REQ-SCAN-005, HLD §5.6 (queue backpressure).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claude_poly_bot.domain.models import Candidate, VenueName
from claude_poly_bot.storage.orm import CandidateQueue


class SqlAlchemyCandidateRepo:
    """Concrete CandidateRepo backed by Postgres via SQLAlchemy.

    Per HLD §5.6, this is the source of truth for candidate state. Bots
    poll via `claim_next` (M2); scanner publishes via `publish`.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    # REQ: REQ-SCAN-005 - scanner publishes accepted candidates.
    async def publish(self, candidate: Candidate) -> None:
        """Insert one candidate row. Idempotent on duplicate
        scan_correlation_id (the same scan won't double-publish)."""
        async with self._sm() as session, session.begin():
            row = CandidateQueue(
                scan_correlation_id=candidate.scan_correlation_id,
                venue=candidate.venue.value,
                market_id=candidate.market_id,
                market_snapshot=candidate.market_snapshot.model_dump(mode="json"),
                book_snapshot=(
                    candidate.book_snapshot.model_dump(mode="json")
                    if candidate.book_snapshot is not None
                    else None
                ),
                scan_score=candidate.scan_score.model_dump(mode="json"),
                created_at=candidate.created_at,
            )
            session.add(row)

    # REQ: HLD §5.6 - backpressure check
    async def queue_depth(self, venue: VenueName | None = None) -> int:
        """Count of currently-published candidates. M2 will refine this to
        per-bot unprocessed depth via the candidate_claims table.
        """
        async with self._sm() as session:
            stmt = select(func.count()).select_from(CandidateQueue)
            if venue is not None:
                stmt = stmt.where(CandidateQueue.venue == venue.value)
            result = await session.execute(stmt)
            return int(result.scalar_one())
