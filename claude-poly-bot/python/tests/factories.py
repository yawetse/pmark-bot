"""Factories for test data.

Populated as domain models land in M1+. For M0 scaffolding this file exists
so tests can import factories namespace; concrete factories will be added
when their referenced domain models exist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4


def utc_now() -> datetime:
    """Default timezone-aware "now" for factory defaults."""
    return datetime.now(UTC)


def fresh_uuid() -> UUID:
    """Default UUID generator for factory defaults."""
    return uuid4()


# Future factories (added in M1+):
# - PolymarketMarketFactory
# - AlpacaMarketFactory
# - BookFactory
# - CheckResultFactory
# - ThesisFactory
# - OrderSpecFactory
# - PositionFactory
# - CandidateFactory
