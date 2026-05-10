"""Process entry points dispatched by `python -m claude_poly_bot <service>`.

M1 implements only `run_scanner`. Other services (claude-bot, openai-bot,
dashboard-api, data-refresh) get stubs that exit with a "not yet
implemented in this milestone" message — fail-loud rather than silently
no-op so docker-compose surfaces the gap.

Traces: REQ-INF-005 (5 always-on services + 1 scheduled).
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack

import httpx

from claude_poly_bot.bot.loops.scanner import scan_once, scanner_loop
from claude_poly_bot.bot.state import ServiceState
from claude_poly_bot.domain.clock import RealClock
from claude_poly_bot.domain.models import VenueName
from claude_poly_bot.storage.db import DbSettings, create_engine, session_factory
from claude_poly_bot.storage.repos.queue import SqlAlchemyCandidateRepo
from claude_poly_bot.storage.repos.scans import SqlAlchemyMarketScanRepo
from claude_poly_bot.venues.polymarket.venue import PolymarketVenue
from claude_poly_bot.venues.registry import VenueRegistry

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Lightweight stdlib logging config until the structlog wiring lands in M11."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def build_scanner_state(env: str) -> tuple[ServiceState, AsyncExitStack]:
    """Wire ServiceState for the scanner service. Caller owns the
    returned AsyncExitStack and must `aclose()` it."""
    stack = AsyncExitStack()
    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(DbSettings(url=db_url))
    stack.push_async_callback(engine.dispose)

    sm = session_factory(engine)
    candidate_repo = SqlAlchemyCandidateRepo(sm)
    scan_repo = SqlAlchemyMarketScanRepo(sm)
    clock = RealClock()

    http_client = httpx.AsyncClient()
    stack.push_async_callback(http_client.aclose)

    polymarket = PolymarketVenue(client=http_client, clock=clock)
    registry = VenueRegistry(venues={VenueName.POLYMARKET: polymarket})

    state = ServiceState(
        service="scanner",
        env=env,
        clock=clock,
        venues=registry,
        candidate_repo=candidate_repo,
        scan_repo=scan_repo,
    )
    return state, stack


async def run_scanner(once: bool = False) -> int:
    """Scanner service entry point.

    Returns process exit code. `once=True` runs a single scan and exits
    (used by `claude-poly-bot scanner --once` for the M1 demo).
    """
    _setup_logging()
    env = os.environ.get("CLAUDE_POLY_BOT_ENV", "dev")
    state, stack = await build_scanner_state(env)
    try:
        polymarket = state.venues.get(VenueName.POLYMARKET)
        if once:
            result = await scan_once(state, polymarket)
            logger.info(
                "scanner_one_shot_done",
                extra={
                    "fetched": result.fetched,
                    "accepted": result.accepted,
                    "rejected": result.rejected,
                    "error": result.error,
                },
            )
            return 0 if result.error is None else 1
        # Cadence-driven loop. Block forever until cancellation.
        async with asyncio.TaskGroup() as tg:
            tg.create_task(scanner_loop(state, polymarket))
        return 0
    finally:
        await stack.aclose()


async def main(service: str, *, once: bool = False) -> int:
    """Top-level dispatcher."""
    if service == "scanner":
        return await run_scanner(once=once)
    if service in {"claude-bot", "openai-bot", "dashboard-api", "data-refresh"}:
        logger.error(
            "service_not_yet_implemented",
            extra={"service": service, "available_in": _milestone_for(service)},
        )
        return 2
    logger.error("unknown_service", extra={"service": service})
    return 2


def _milestone_for(service: str) -> str:
    return {
        "claude-bot": "M2 (Claude brain)",
        "openai-bot": "M6 (OpenAI bot)",
        "dashboard-api": "M8 (dashboard MVP)",
        "data-refresh": "M11 (observability + alerts)",
    }.get(service, "later milestone")
