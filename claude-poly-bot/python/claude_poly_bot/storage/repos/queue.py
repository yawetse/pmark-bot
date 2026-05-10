"""Candidate-queue repository.

M1 surface: `publish` and `queue_depth`.
M2 surface: `claim_next` (per-bot candidate_claims, DD-017),
            `complete`, `fail`.

Traces: REQ-SCAN-005, DD-017, DD-019, HLD §5.6 (queue backpressure).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claude_poly_bot.domain.models import (
    Bot,
    Candidate,
    CandidateClaim,
    ClaimStatus,
    VenueName,
)
from claude_poly_bot.domain.thesis import derive_decision_correlation_id
from claude_poly_bot.storage.orm import CandidateClaims, CandidateQueue


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
    async def queue_depth(self, venue: VenueName | None = None, *, bot: Bot | None = None) -> int:
        """Per-bot unprocessed depth: candidates without a `done` claim row.

        If `bot=None`, falls back to a simple count of all published
        candidates (the M1 semantic, retained for the dashboard's
        venue-level surface).
        """
        async with self._sm() as session:
            if bot is None:
                stmt = select(func.count()).select_from(CandidateQueue)
                if venue is not None:
                    stmt = stmt.where(CandidateQueue.venue == venue.value)
                result = await session.execute(stmt)
                return int(result.scalar_one())
            # Per-bot: candidates not claimed-done by this bot.
            sql = text("""
                SELECT count(*) FROM candidate_queue cq
                LEFT JOIN candidate_claims cc
                  ON cc.scan_correlation_id = cq.scan_correlation_id
                  AND cc.bot = :bot
                WHERE (:venue IS NULL OR cq.venue = :venue)
                  AND (cc.status IS NULL OR cc.status NOT IN ('done', 'error'))
            """)
            result = await session.execute(
                sql,
                {"bot": bot.value, "venue": venue.value if venue else None},
            )
            return int(result.scalar_one())

    # REQ: DD-017 - per-bot claim row, FOR UPDATE SKIP LOCKED for atomic claim.
    async def claim_next(
        self, bot: Bot, *, limit: int = 1
    ) -> list[tuple[Candidate, CandidateClaim]]:
        """Lazy-create per-(candidate, bot) claim rows for any candidates
        not yet known to this bot, then atomically claim up to `limit` rows
        in `new` status.
        """
        async with self._sm() as session, session.begin():
            # 1) Ensure a candidate_claims row exists for every candidate we
            #    might claim. Use ON CONFLICT to no-op for already-seen rows.
            unseen = (
                await session.execute(
                    text("""
                    SELECT cq.scan_correlation_id FROM candidate_queue cq
                    LEFT JOIN candidate_claims cc
                      ON cc.scan_correlation_id = cq.scan_correlation_id
                      AND cc.bot = :bot
                    WHERE cc.scan_correlation_id IS NULL
                    LIMIT :prefetch
                """),
                    {"bot": bot.value, "prefetch": limit * 4},
                )
            ).all()
            for row in unseen:
                scan_id = row[0]
                stmt = pg_insert(CandidateClaims).values(
                    scan_correlation_id=scan_id,
                    bot=bot.value,
                    status=ClaimStatus.NEW.value,
                    decision_correlation_id=derive_decision_correlation_id(scan_id, bot),
                )
                stmt = stmt.on_conflict_do_nothing(
                    constraint="pk_candidate_claims",
                )
                await session.execute(stmt)

            # 2) Atomically claim up to `limit` rows.
            now = datetime.now(UTC)
            claimed = await session.execute(
                text("""
                    UPDATE candidate_claims
                    SET status = 'processing', claimed_at = :now
                    WHERE (scan_correlation_id, bot) IN (
                        SELECT scan_correlation_id, bot FROM candidate_claims
                        WHERE bot = :bot AND status = 'new'
                        FOR UPDATE SKIP LOCKED
                        LIMIT :lim
                    )
                    RETURNING scan_correlation_id, bot, status, decision_correlation_id,
                              claimed_at, completed_at, error
                """),
                {"bot": bot.value, "lim": limit, "now": now},
            )
            claimed_rows = claimed.all()
            if not claimed_rows:
                return []

            scan_ids = [r[0] for r in claimed_rows]
            cqs = (
                (
                    await session.execute(
                        select(CandidateQueue).where(
                            CandidateQueue.scan_correlation_id.in_(scan_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            cq_by_id = {c.scan_correlation_id: c for c in cqs}

            out: list[tuple[Candidate, CandidateClaim]] = []
            for row in claimed_rows:
                cq = cq_by_id.get(row[0])
                if cq is None:
                    continue
                candidate = Candidate.model_validate(_candidate_payload(cq))
                claim = CandidateClaim(
                    scan_correlation_id=row[0],
                    bot=Bot(row[1]),
                    status=ClaimStatus(row[2]),
                    decision_correlation_id=row[3],
                    claimed_at=row[4],
                    completed_at=row[5],
                    error=row[6],
                )
                out.append((candidate, claim))
            return out

    async def complete(self, scan_correlation_id: str, bot: Bot) -> None:
        async with self._sm() as session, session.begin():
            await session.execute(
                update(CandidateClaims)
                .where(
                    CandidateClaims.scan_correlation_id == scan_correlation_id,
                    CandidateClaims.bot == bot.value,
                )
                .values(status=ClaimStatus.DONE.value, completed_at=datetime.now(UTC))
            )

    async def fail(self, scan_correlation_id: str, bot: Bot, error: str) -> None:
        async with self._sm() as session, session.begin():
            await session.execute(
                update(CandidateClaims)
                .where(
                    CandidateClaims.scan_correlation_id == scan_correlation_id,
                    CandidateClaims.bot == bot.value,
                )
                .values(
                    status=ClaimStatus.ERROR.value,
                    completed_at=datetime.now(UTC),
                    error=error[:500],
                )
            )


def _candidate_payload(cq: CandidateQueue) -> dict[str, object]:
    """Reconstruct a Candidate model from the JSONB columns + scalar metadata."""
    return {
        "scan_correlation_id": cq.scan_correlation_id,
        "venue": cq.venue,
        "market_id": cq.market_id,
        "market_snapshot": cq.market_snapshot,
        "book_snapshot": cq.book_snapshot,
        "scan_score": cq.scan_score,
        "created_at": cq.created_at,
    }
