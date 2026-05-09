"""Unit tests for domain.models.

Traces: REQ-SCAN-005, REQ-SCAN-008, HLD DD-004 (decimal precision),
DD-021 (timezone-aware datetimes).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from claude_poly_bot.domain.models import (
    AlpacaMarket,
    AlpacaScoreFields,
    Book,
    Bot,
    Candidate,
    Geo,
    MarketScanRun,
    PolymarketMarket,
    PolymarketScoreFields,
    ScanScore,
    Side,
    VenueName,
    Verdict,
)
from pydantic import ValidationError


def _ts() -> datetime:
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)


def test_enums_have_expected_string_values() -> None:
    """Sanity: enums serialize as expected strings."""
    assert Bot.CLAUDE.value == "claude"
    assert VenueName.POLYMARKET.value == "polymarket"
    assert Geo.US.value == "us"
    assert Side.BUY.value == "buy"
    assert Verdict.BUY.value == "BUY"


def test_polymarket_market_construction() -> None:
    m = PolymarketMarket(
        external_id="0xabc",
        name="Will it rain?",
        geo=Geo.US,
        created_at=_ts(),
        question="Will it rain in NYC tomorrow?",
        resolution_rules="National Weather Service ruling.",
        resolution_time=_ts(),
        outcomes=["YES", "NO"],
        token_ids={"YES": "tok-yes", "NO": "tok-no"},
    )
    assert m.venue == VenueName.POLYMARKET


def test_polymarket_market_is_frozen() -> None:
    """Models are immutable per HLD invariants — construct once, never mutate."""
    m = PolymarketMarket(
        external_id="0xabc",
        name="x",
        created_at=_ts(),
        question="?",
        resolution_rules=".",
        resolution_time=_ts(),
        outcomes=["YES", "NO"],
        token_ids={},
    )
    with pytest.raises(ValidationError):
        m.question = "mutated"  # type: ignore[misc]


def test_book_requires_timezone_aware_timestamp() -> None:
    """TST-DOMAIN-MODELS-01: naive datetime rejected (DD-021)."""
    with pytest.raises(ValidationError):
        Book(
            venue=VenueName.POLYMARKET,
            market_id="m1",
            bids=[(Decimal("0.5"), 100)],
            asks=[(Decimal("0.51"), 100)],
            midpoint=Decimal("0.505"),
            timestamp=datetime(2026, 4, 26, 12, 0),  # naive
        )


def test_money_field_rejects_float() -> None:
    """TST-DOMAIN-MODELS-02: HLD DD-004 - Decimal-only money. Strict mode bans floats."""
    with pytest.raises(ValidationError):
        Book(
            venue=VenueName.POLYMARKET,
            market_id="m1",
            bids=[(0.5, 100)],  # type: ignore[list-item]
            asks=[(Decimal("0.51"), 100)],
            midpoint=Decimal("0.505"),
            timestamp=_ts(),
        )


def test_polymarket_score_fields_construction() -> None:
    pf = PolymarketScoreFields(
        gap=Decimal("0.10"), depth=Decimal("1000"), hours_to_resolution=Decimal("24")
    )
    assert pf.venue == VenueName.POLYMARKET


def test_alpaca_score_fields_construction() -> None:
    af = AlpacaScoreFields(
        relative_volume=Decimal("2.0"),
        price_momentum=Decimal("0.05"),
        dollar_volume=Decimal("100000"),
        last_price=Decimal("150"),
    )
    assert af.venue == VenueName.ALPACA


def test_scan_score_venue_matches_fields_venue() -> None:
    """TST-DOMAIN-MODELS-03: validator enforces consistency between
    ScanScore.venue and the discriminated fields' venue.
    """
    pf = PolymarketScoreFields(
        gap=Decimal("0.10"), depth=Decimal("1000"), hours_to_resolution=Decimal("24")
    )
    with pytest.raises(ValidationError):
        ScanScore(market_id="m1", venue=VenueName.ALPACA, fields=pf, accepted=True)


def test_scan_score_accepted_must_not_have_rejection_reason() -> None:
    pf = PolymarketScoreFields(
        gap=Decimal("0.10"), depth=Decimal("1000"), hours_to_resolution=Decimal("24")
    )
    with pytest.raises(ValidationError):
        ScanScore(
            market_id="m1",
            venue=VenueName.POLYMARKET,
            fields=pf,
            accepted=True,
            rejection_reason="should not be set",
        )


def test_scan_score_rejected_with_reason_ok() -> None:
    pf = PolymarketScoreFields(
        gap=Decimal("0.05"), depth=Decimal("100"), hours_to_resolution=Decimal("2")
    )
    s = ScanScore(
        market_id="m1",
        venue=VenueName.POLYMARKET,
        fields=pf,
        accepted=False,
        rejection_reason="insufficient_gap",
    )
    assert s.rejection_reason == "insufficient_gap"


def test_candidate_default_correlation_id_is_unique() -> None:
    pf = PolymarketScoreFields(
        gap=Decimal("0.10"), depth=Decimal("1000"), hours_to_resolution=Decimal("24")
    )
    score = ScanScore(market_id="m1", venue=VenueName.POLYMARKET, fields=pf, accepted=True)
    market = PolymarketMarket(
        external_id="0xabc",
        name="x",
        created_at=_ts(),
        question="?",
        resolution_rules=".",
        resolution_time=_ts(),
        outcomes=["YES", "NO"],
        token_ids={},
    )
    c1 = Candidate(
        venue=VenueName.POLYMARKET,
        market_id="m1",
        market_snapshot=market,
        scan_score=score,
        created_at=_ts(),
    )
    c2 = Candidate(
        venue=VenueName.POLYMARKET,
        market_id="m1",
        market_snapshot=market,
        scan_score=score,
        created_at=_ts(),
    )
    assert c1.scan_correlation_id != c2.scan_correlation_id


def test_market_scan_run_construction() -> None:
    run = MarketScanRun(
        venue=VenueName.POLYMARKET,
        started_at=_ts(),
        ended_at=_ts(),
        fetched=500,
        accepted=35,
        rejected=465,
    )
    assert run.fetched == 500


def test_alpaca_market_construction_and_defaults() -> None:
    m = AlpacaMarket(
        external_id="AAPL",
        name="Apple",
        created_at=_ts(),
        ticker="AAPL",
    )
    assert m.is_etf is False
    assert m.venue == VenueName.ALPACA
