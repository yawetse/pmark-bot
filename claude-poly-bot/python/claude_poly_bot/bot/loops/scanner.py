"""Scanner loop: fetch markets, score, filter, publish accepted candidates.

One coroutine per venue. Cadence is configurable; default 300s per
REQ-SCAN-001. Per-market failures isolated (DD-005); whole-scan failure
(API unreachable) emits an error log + skips this cycle.

Traces: REQ-SCAN-001, REQ-SCAN-004, REQ-SCAN-005, REQ-SCAN-007, REQ-SCAN-008,
HLD §5.1 (retrying_db).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from claude_poly_bot.bot.state import ServiceState
from claude_poly_bot.domain.exceptions import VenueUnreachableError
from claude_poly_bot.domain.models import (
    Book,
    Candidate,
    Market,
    MarketScanRun,
    PolymarketMarket,
    PolymarketScoreFields,
    ScanScore,
    VenueName,
)
from claude_poly_bot.domain.protocols import Venue
from claude_poly_bot.domain.scoring import (
    PolymarketFilters,
    apply_polymarket_filters,
    score_polymarket_market,
)

logger = logging.getLogger(__name__)


@dataclass
class ScanRunResult:
    venue: VenueName
    fetched: int
    accepted: int
    rejected: int
    duration_sec: float
    error: str | None = None


# REQ: REQ-SCAN-001 - cadence-driven scan.
async def scanner_loop(state: ServiceState, venue: Venue, *, cadence_sec: int = 300) -> None:
    """Run scanner forever (or until cancelled). One coroutine per venue."""
    logger.info("scanner_loop_started", extra={"venue": venue.name.value, "cadence": cadence_sec})
    while True:
        try:
            if not await venue.is_market_open():
                logger.debug("scanner_skip_closed", extra={"venue": venue.name.value})
            else:
                await scan_once(state, venue)
        except asyncio.CancelledError:
            logger.info("scanner_loop_cancelled", extra={"venue": venue.name.value})
            raise
        except Exception as e:
            # Tiered error handling per HLD §5.1: don't crash on scan failure.
            logger.exception(
                "scanner_loop_iteration_failed",
                extra={"venue": venue.name.value, "error": str(e)},
            )
        await asyncio.sleep(cadence_sec)


# REQ: REQ-SCAN-001 - one-shot scan; returns summary.
async def scan_once(state: ServiceState, venue: Venue) -> ScanRunResult:
    """Single scan pass. Used by `scanner_loop` and the CLI debug command."""
    started_at = state.clock.now()
    fetched = 0
    accepted = 0
    rejected = 0
    error: str | None = None

    try:
        if venue.name == VenueName.POLYMARKET:
            fetched, accepted, rejected = await _scan_polymarket(state, venue, started_at)
        else:
            # Alpaca scanning lands in M7; M1 scope is Polymarket-only.
            logger.info("scanner_venue_unsupported_in_m1", extra={"venue": venue.name.value})
    except VenueUnreachableError as e:
        error = f"venue_unreachable: {e}"
        logger.error(
            "scanner_venue_unreachable",
            extra={"venue": venue.name.value, "error": str(e)},
        )

    ended_at = state.clock.now()
    run = MarketScanRun(
        venue=venue.name,
        started_at=started_at,
        ended_at=ended_at,
        fetched=fetched,
        accepted=accepted,
        rejected=rejected,
        error=error,
    )
    # REQ: REQ-SCAN-008 - persist scan-run summary.
    await state.scan_repo.record(run)

    duration_sec = (ended_at - started_at).total_seconds()
    return ScanRunResult(
        venue=venue.name,
        fetched=fetched,
        accepted=accepted,
        rejected=rejected,
        duration_sec=duration_sec,
        error=error,
    )


async def _scan_polymarket(
    state: ServiceState, venue: Venue, started_at: datetime
) -> tuple[int, int, int]:
    """Fetch + score + filter + publish for the Polymarket venue."""
    markets = await venue.list_active_markets()
    fetched = len(markets)
    accepted = 0
    rejected = 0
    filters = PolymarketFilters()  # M1 uses defaults; M9 will load from config.

    # Bound book-fetch concurrency to avoid hammering Polymarket.
    semaphore = asyncio.Semaphore(20)

    async def process(market: Market) -> None:
        nonlocal accepted, rejected
        if not isinstance(market, PolymarketMarket):
            return
        # Use the first outcome's CLOB token id as the book-lookup key.
        token_ids = list(market.token_ids.values())
        if not token_ids:
            rejected += 1
            return
        token_id = token_ids[0]
        async with semaphore:
            try:
                book = await venue.get_book(token_id)
            except Exception as e:
                # Per-market failure isolation per DD-005.
                logger.warning(
                    "scanner_book_fetch_failed",
                    extra={"market_id": market.external_id, "error": str(e)},
                )
                rejected += 1
                return
        # M1: estimate = midpoint (gap=0). Real LLM-driven estimates
        # come from the brain (M2). Structural filters (depth/hours)
        # dominate at scan time per LLD Batch 1 open-item.
        score_fields = score_polymarket_market(
            market,
            book,
            estimated_probability=book.midpoint,
            now=started_at,
        )
        score = apply_polymarket_filters(market.external_id, score_fields, filters)
        if score.accepted:
            await _publish_candidate(state, market, book, score)
            accepted += 1
        else:
            rejected += 1
            logger.debug(
                "scanner_market_rejected",
                extra={
                    "market_id": market.external_id,
                    "reason": score.rejection_reason,
                },
            )

    await asyncio.gather(*[process(m) for m in markets], return_exceptions=False)
    return fetched, accepted, rejected


async def _publish_candidate(
    state: ServiceState,
    market: PolymarketMarket,
    book: Book,
    score: ScanScore,
) -> None:
    """Construct a Candidate and publish to the queue.

    For M1 we publish the score-fields-shaped score directly; book is
    snapshotted alongside.
    """
    # Defensive: ensure score.fields is a PolymarketScoreFields instance.
    if not isinstance(score.fields, PolymarketScoreFields):
        return
    candidate = Candidate(
        venue=VenueName.POLYMARKET,
        market_id=market.external_id,
        market_snapshot=market,
        book_snapshot=book,
        scan_score=score,
        created_at=state.clock.now(),
    )
    await state.candidate_repo.publish(candidate)


# Silence unused-import warnings — `Decimal` kept for future scoring tweaks.
_ = Decimal
