"""Pure scoring functions for the scanner.

Polymarket scoring lands in M1; Alpaca scoring lands in M7.

Traces: REQ-SCAN-002, REQ-SCAN-003.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from claude_poly_bot.domain.models import (
    Book,
    Money,
    PolymarketMarket,
    PolymarketScoreFields,
    Probability,
    ScanScore,
    VenueName,
)

# Top-N book levels considered for depth scoring. Caps O(book.depth) work.
_DEPTH_LEVELS = 10


class PolymarketFilters(BaseModel):
    """Filter thresholds applied after scoring.

    Defaults align with REQ-SCAN-003 (gap 0.07, depth 500 USDC, 4-168h).
    """

    model_config = ConfigDict(strict=True, frozen=True)
    min_gap: Decimal = Field(default=Decimal("0.07"))
    min_depth_usdc: Money = Decimal("500")
    min_hours_to_resolution: int = 4
    max_hours_to_resolution: int = 168


# REQ: REQ-SCAN-002 - score Polymarket market on gap/depth/hours.
def score_polymarket_market(
    market: PolymarketMarket,
    book: Book,
    *,
    estimated_probability: Probability,
    now: datetime,
) -> PolymarketScoreFields:
    """Compute the three scoring dimensions.

    `gap` = |estimate - midpoint|.
    `depth` = min(top-10 bid sum, top-10 ask sum) in USDC.
    `hours_to_resolution` = (resolution_time - now) / 3600.

    No filtering yet — see `apply_polymarket_filters`.
    """
    if now.tzinfo is None:
        raise ValueError("score_polymarket_market requires a timezone-aware `now`")

    gap = abs(Decimal(estimated_probability) - book.midpoint)

    bid_depth = sum((Decimal(size) for _, size in book.bids[:_DEPTH_LEVELS]), Decimal(0))
    ask_depth = sum((Decimal(size) for _, size in book.asks[:_DEPTH_LEVELS]), Decimal(0))
    depth = min(bid_depth, ask_depth)

    delta = market.resolution_time - now
    hours_to_resolution = Decimal(delta.total_seconds()) / Decimal(3600)

    return PolymarketScoreFields(
        gap=gap,
        depth=depth,
        hours_to_resolution=hours_to_resolution,
    )


# REQ: REQ-SCAN-003 - apply min/max filters; return ScanScore with accept + reason.
def apply_polymarket_filters(
    market_id: str,
    fields: PolymarketScoreFields,
    filters: PolymarketFilters,
) -> ScanScore:
    """Short-circuit on first failure. Returns ScanScore.accepted=False
    with the first matching `rejection_reason`. Boundary semantics:
    `min_*` is inclusive; `max_*` is inclusive.
    """
    if fields.gap < filters.min_gap:
        return _reject(market_id, fields, "insufficient_gap")
    if fields.depth < filters.min_depth_usdc:
        return _reject(market_id, fields, "insufficient_depth")
    if fields.hours_to_resolution < filters.min_hours_to_resolution:
        return _reject(market_id, fields, "too_close_to_resolution")
    if fields.hours_to_resolution > filters.max_hours_to_resolution:
        return _reject(market_id, fields, "too_far_from_resolution")
    return ScanScore(
        market_id=market_id,
        venue=VenueName.POLYMARKET,
        fields=fields,
        accepted=True,
    )


def _reject(market_id: str, fields: PolymarketScoreFields, reason: str) -> ScanScore:
    return ScanScore(
        market_id=market_id,
        venue=VenueName.POLYMARKET,
        fields=fields,
        accepted=False,
        rejection_reason=reason,
    )


__all__ = [
    "PolymarketFilters",
    "apply_polymarket_filters",
    "score_polymarket_market",
]
# silence unused-import lint warning — AwareDatetime kept for future extensions
_ = AwareDatetime
