"""Unit tests for domain.scoring (Polymarket).

Boundary tests cover REQ-SCAN-003 explicitly. Hypothesis property tests
verify scoring output structure across the input domain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from claude_poly_bot.domain.models import (
    Book,
    PolymarketMarket,
    PolymarketScoreFields,
    VenueName,
)
from claude_poly_bot.domain.scoring import (
    PolymarketFilters,
    apply_polymarket_filters,
    score_polymarket_market,
)
from hypothesis import given, settings
from hypothesis import strategies as st


def _market(resolution_in_hours: float = 24) -> PolymarketMarket:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    return PolymarketMarket(
        external_id="0xabc",
        name="Test market",
        created_at=now,
        question="?",
        resolution_rules=".",
        resolution_time=now + timedelta(hours=resolution_in_hours),
        outcomes=["YES", "NO"],
        token_ids={"YES": "tok-yes", "NO": "tok-no"},
    )


def _book(
    midpoint: Decimal = Decimal("0.5"),
    bid_sizes: tuple[int, ...] = (300, 200),
    ask_sizes: tuple[int, ...] = (300, 200),
) -> Book:
    return Book(
        venue=VenueName.POLYMARKET,
        market_id="m1",
        bids=[(midpoint - Decimal("0.01"), s) for s in bid_sizes],
        asks=[(midpoint + Decimal("0.01"), s) for s in ask_sizes],
        midpoint=midpoint,
        timestamp=datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
    )


def test_score_computes_gap_depth_hours() -> None:
    """TST-SCAN-002-01: score function produces expected dimensions."""
    market = _market(resolution_in_hours=24)
    book = _book(midpoint=Decimal("0.5"))
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    fields = score_polymarket_market(market, book, estimated_probability=Decimal("0.6"), now=now)
    assert fields.gap == Decimal("0.10")
    assert fields.depth == Decimal("500")  # 300+200 on the smaller side
    assert fields.hours_to_resolution == Decimal("24")


def test_score_rejects_naive_now() -> None:
    market = _market()
    book = _book()
    with pytest.raises(ValueError, match="timezone-aware"):
        score_polymarket_market(
            market, book, estimated_probability=Decimal("0.5"), now=datetime(2026, 4, 26, 12, 0)
        )


def test_filter_rejects_low_gap() -> None:
    """TST-SCAN-003-01: gap < 0.07 rejected as insufficient_gap."""
    fields = PolymarketScoreFields(
        gap=Decimal("0.06"), depth=Decimal("1000"), hours_to_resolution=Decimal("24")
    )
    score = apply_polymarket_filters("m1", fields, PolymarketFilters())
    assert score.accepted is False
    assert score.rejection_reason == "insufficient_gap"


def test_filter_accepts_at_min_gap_boundary() -> None:
    """TST-SCAN-003-02: gap == 0.07 boundary inclusive."""
    fields = PolymarketScoreFields(
        gap=Decimal("0.07"), depth=Decimal("1000"), hours_to_resolution=Decimal("24")
    )
    score = apply_polymarket_filters("m1", fields, PolymarketFilters())
    assert score.accepted is True


def test_filter_rejects_low_depth() -> None:
    """TST-SCAN-003-03: depth < 500 USDC rejected."""
    fields = PolymarketScoreFields(
        gap=Decimal("0.10"), depth=Decimal("499"), hours_to_resolution=Decimal("24")
    )
    score = apply_polymarket_filters("m1", fields, PolymarketFilters())
    assert score.rejection_reason == "insufficient_depth"


def test_filter_rejects_too_close_to_resolution() -> None:
    """TST-SCAN-003-04: hours < 4 rejected."""
    fields = PolymarketScoreFields(
        gap=Decimal("0.10"), depth=Decimal("1000"), hours_to_resolution=Decimal("3")
    )
    score = apply_polymarket_filters("m1", fields, PolymarketFilters())
    assert score.rejection_reason == "too_close_to_resolution"


def test_filter_rejects_too_far_from_resolution() -> None:
    """TST-SCAN-003-05: hours > 168 rejected."""
    fields = PolymarketScoreFields(
        gap=Decimal("0.10"), depth=Decimal("1000"), hours_to_resolution=Decimal("169")
    )
    score = apply_polymarket_filters("m1", fields, PolymarketFilters())
    assert score.rejection_reason == "too_far_from_resolution"


def test_filter_short_circuits_on_first_failure() -> None:
    """When multiple filters fail, the first failing reason is returned."""
    fields = PolymarketScoreFields(
        gap=Decimal("0.01"), depth=Decimal("100"), hours_to_resolution=Decimal("1")
    )
    score = apply_polymarket_filters("m1", fields, PolymarketFilters())
    assert score.rejection_reason == "insufficient_gap"


def test_filter_at_max_hours_boundary_accepts() -> None:
    """hours == max (168) inclusive → accept."""
    fields = PolymarketScoreFields(
        gap=Decimal("0.10"), depth=Decimal("1000"), hours_to_resolution=Decimal("168")
    )
    score = apply_polymarket_filters("m1", fields, PolymarketFilters())
    assert score.accepted is True


@settings(max_examples=200)
@given(
    gap=st.decimals(min_value=Decimal("0"), max_value=Decimal("1"), places=4),
    depth=st.decimals(min_value=Decimal("0"), max_value=Decimal("100000"), places=2),
    hours=st.decimals(min_value=Decimal("0"), max_value=Decimal("500"), places=2),
)
def test_property_filter_rejection_has_reason(gap: Decimal, depth: Decimal, hours: Decimal) -> None:
    """Property: a rejected score always has a non-None rejection_reason;
    an accepted score always has rejection_reason None."""
    fields = PolymarketScoreFields(gap=gap, depth=depth, hours_to_resolution=hours)
    score = apply_polymarket_filters("m1", fields, PolymarketFilters())
    if score.accepted:
        assert score.rejection_reason is None
    else:
        assert score.rejection_reason is not None
