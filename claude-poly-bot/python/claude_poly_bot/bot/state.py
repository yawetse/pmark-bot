"""ServiceState wired at startup; passed to loops.

M1 carries only the dependencies the scanner needs. M2+ extends with
strategist, repos for orders/positions/decisions, etc.

Traces: REQ-INF-005 (5 services), HLD §3.3.
"""

from __future__ import annotations

from dataclasses import dataclass

from claude_poly_bot.domain.clock import Clock
from claude_poly_bot.storage.repos.queue import SqlAlchemyCandidateRepo
from claude_poly_bot.storage.repos.scans import SqlAlchemyMarketScanRepo
from claude_poly_bot.venues.registry import VenueRegistry


@dataclass
class ServiceState:
    """All wired adapters for a service. Constructed once in `bot.runner`."""

    service: str  # "scanner" | "claude-bot" | "openai-bot" | "dashboard-api" | "data-refresh"
    env: str  # "dev" | "prod"
    clock: Clock
    venues: VenueRegistry
    candidate_repo: SqlAlchemyCandidateRepo
    scan_repo: SqlAlchemyMarketScanRepo
    # bot, strategist, position_repo, order_repo, etc. land in M2+.
