"""Unit tests for domain.consensus.

Traces: REQ-BRN-009, REQ-EXE-004, TST-BRN-009-*, TST-EXE-004-*.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from claude_poly_bot.domain.consensus import (
    aggregate_check_results,
    aggregate_sub_agent_votes,
)
from claude_poly_bot.domain.models import (
    Bot,
    CheckResult,
    CheckType,
    SubAgent,
    VenueName,
    Verdict,
)


def _check(
    check_type: CheckType,
    verdict: Verdict,
    *,
    confidence: Decimal = Decimal("0.8"),
    p_win: Decimal = Decimal("0.7"),
) -> CheckResult:
    return CheckResult(
        bot=Bot.CLAUDE,
        venue=VenueName.POLYMARKET,
        market_id="m1",
        check_type=check_type,
        verdict=verdict,
        confidence=confidence,
        p_win=p_win,
        rationale="t",
        model_id="m",
        correlation_id=uuid4(),
    )


def _sub(verdict: Verdict, sub_agent: SubAgent = SubAgent.ARBITRAGE) -> CheckResult:
    return CheckResult(
        bot=Bot.CLAUDE,
        venue=VenueName.POLYMARKET,
        market_id="m1",
        check_type=CheckType.BASE_RATE,
        sub_agent=sub_agent,
        verdict=verdict,
        confidence=Decimal("0.8"),
        p_win=Decimal("0.7"),
        rationale="t",
        model_id="m",
        correlation_id=uuid4(),
    )


def test_check_consensus_3_buy_1_skip_returns_buy() -> None:
    """3-of-4 BUY → verdict=BUY; mean confidence over BUYs only."""
    results = [
        _check(CheckType.BASE_RATE, Verdict.BUY, confidence=Decimal("0.9")),
        _check(CheckType.NEWS, Verdict.BUY, confidence=Decimal("0.8")),
        _check(CheckType.WHALE, Verdict.BUY, confidence=Decimal("0.7")),
        _check(CheckType.DISPOSITION, Verdict.SKIP),
    ]
    cc = aggregate_check_results(results)
    assert cc.verdict == Verdict.BUY
    assert cc.agreeing_count == 3
    assert cc.mean_confidence == Decimal("0.8")  # (0.9 + 0.8 + 0.7) / 3


def test_check_consensus_2_2_split_returns_skip() -> None:
    """No 3-of-4 majority → SKIP."""
    results = [
        _check(CheckType.BASE_RATE, Verdict.BUY),
        _check(CheckType.NEWS, Verdict.BUY),
        _check(CheckType.WHALE, Verdict.SELL),
        _check(CheckType.DISPOSITION, Verdict.SELL),
    ]
    cc = aggregate_check_results(results)
    assert cc.verdict == Verdict.SKIP


def test_check_consensus_all_skip_returns_skip() -> None:
    results = [
        _check(CheckType.BASE_RATE, Verdict.SKIP),
        _check(CheckType.NEWS, Verdict.SKIP),
        _check(CheckType.WHALE, Verdict.SKIP),
        _check(CheckType.DISPOSITION, Verdict.SKIP),
    ]
    assert aggregate_check_results(results).verdict == Verdict.SKIP


def test_check_consensus_empty_returns_skip() -> None:
    assert aggregate_check_results([]).verdict == Verdict.SKIP


def test_sub_agent_2_agree_returns_full() -> None:
    """2-of-3 agree on BUY → FULL."""
    votes = [
        _sub(Verdict.BUY, SubAgent.ARBITRAGE),
        _sub(Verdict.BUY, SubAgent.CONVERGENCE),
        _sub(Verdict.SKIP, SubAgent.WHALE_COPY),
    ]
    sc = aggregate_sub_agent_votes(votes)
    assert sc.size_multiplier == "FULL"
    assert sc.verdict == Verdict.BUY


def test_sub_agent_1_only_returns_half() -> None:
    """Exactly one non-SKIP → HALF."""
    votes = [
        _sub(Verdict.BUY, SubAgent.ARBITRAGE),
        _sub(Verdict.SKIP, SubAgent.CONVERGENCE),
        _sub(Verdict.SKIP, SubAgent.WHALE_COPY),
    ]
    sc = aggregate_sub_agent_votes(votes)
    assert sc.size_multiplier == "HALF"
    assert sc.verdict == Verdict.BUY


def test_sub_agent_split_buy_sell_returns_skip() -> None:
    """1 BUY + 1 SELL + 1 SKIP → SKIP (no 2-of-3 agreement)."""
    votes = [
        _sub(Verdict.BUY, SubAgent.ARBITRAGE),
        _sub(Verdict.SELL, SubAgent.CONVERGENCE),
        _sub(Verdict.SKIP, SubAgent.WHALE_COPY),
    ]
    sc = aggregate_sub_agent_votes(votes)
    assert sc.size_multiplier == "SKIP"


def test_sub_agent_all_skip_returns_skip() -> None:
    votes = [
        _sub(Verdict.SKIP, SubAgent.ARBITRAGE),
        _sub(Verdict.SKIP, SubAgent.CONVERGENCE),
        _sub(Verdict.SKIP, SubAgent.WHALE_COPY),
    ]
    assert aggregate_sub_agent_votes(votes).size_multiplier == "SKIP"


# silence unused-import warnings
_ = (datetime, UTC, pytest)
