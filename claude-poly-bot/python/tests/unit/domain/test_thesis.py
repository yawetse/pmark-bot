"""Unit tests for domain.thesis.

Traces: REQ-BRN-009, REQ-BRN-010, REQ-BRN-007, DD-019.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from claude_poly_bot.domain.models import (
    Bot,
    CheckResult,
    CheckType,
    SubAgent,
    VenueName,
    Verdict,
)
from claude_poly_bot.domain.thesis import (
    ThesisInput,
    derive_decision_correlation_id,
    generate_thesis,
)


def _now() -> datetime:
    return datetime(2026, 5, 10, 12, 0, tzinfo=UTC)


def _check(
    check_type: CheckType,
    verdict: Verdict,
    *,
    confidence: Decimal = Decimal("0.85"),
) -> CheckResult:
    return CheckResult(
        bot=Bot.CLAUDE,
        venue=VenueName.POLYMARKET,
        market_id="m1",
        check_type=check_type,
        verdict=verdict,
        confidence=confidence,
        p_win=Decimal("0.7"),
        rationale="t",
        model_id="m",
        correlation_id=uuid4(),
    )


def _sub(verdict: Verdict, sub_agent: SubAgent) -> CheckResult:
    return CheckResult(
        bot=Bot.CLAUDE,
        venue=VenueName.POLYMARKET,
        market_id="m1",
        check_type=CheckType.BASE_RATE,
        sub_agent=sub_agent,
        verdict=verdict,
        confidence=Decimal("0.85"),
        p_win=Decimal("0.7"),
        rationale="t",
        model_id="m",
        correlation_id=uuid4(),
    )


def _polymarket_input(
    *,
    check_verdicts: list[Verdict] | None = None,
    sub_verdicts: list[Verdict] | None = None,
    confidence_threshold: Decimal = Decimal("0.75"),
) -> ThesisInput:
    cv = check_verdicts or [Verdict.BUY] * 4
    sv = sub_verdicts or [Verdict.BUY, Verdict.BUY, Verdict.SKIP]
    types = [CheckType.BASE_RATE, CheckType.NEWS, CheckType.WHALE, CheckType.DISPOSITION]
    sub_agents = [SubAgent.ARBITRAGE, SubAgent.CONVERGENCE, SubAgent.WHALE_COPY]
    return ThesisInput(
        bot=Bot.CLAUDE,
        venue=VenueName.POLYMARKET,
        market_id="m1",
        check_results=[_check(t, v) for t, v in zip(types, cv, strict=True)],
        sub_agent_results=[_sub(v, a) for v, a in zip(sv, sub_agents, strict=True)],
        scan_correlation_id=uuid4(),
        confidence_threshold=confidence_threshold,
    )


def test_decision_correlation_id_is_deterministic() -> None:
    """DD-019: same (scan_id, bot) ⇒ same decision_correlation_id."""
    scan_id = uuid4()
    a = derive_decision_correlation_id(scan_id, Bot.CLAUDE)
    b = derive_decision_correlation_id(scan_id, Bot.CLAUDE)
    c = derive_decision_correlation_id(scan_id, Bot.OPENAI)
    assert a == b
    assert a != c


def test_thesis_produced_for_4_buy_2_buy_subagents() -> None:
    outcome = generate_thesis(_polymarket_input(), now=_now())
    assert outcome.decision == "PRODUCED"
    assert outcome.thesis is not None
    assert outcome.thesis.verdict == Verdict.BUY
    assert outcome.thesis.size_multiplier == "FULL"


def test_thesis_skipped_when_below_confidence() -> None:
    outcome = generate_thesis(
        _polymarket_input(
            check_verdicts=[Verdict.BUY] * 4,
            confidence_threshold=Decimal("0.95"),
        ),
        now=_now(),
    )
    assert outcome.decision == "BELOW_CONFIDENCE"
    assert outcome.thesis is None


def test_thesis_skipped_when_no_check_consensus() -> None:
    outcome = generate_thesis(
        _polymarket_input(check_verdicts=[Verdict.BUY, Verdict.BUY, Verdict.SELL, Verdict.SELL]),
        now=_now(),
    )
    assert outcome.decision == "NO_CHECK_CONSENSUS"


def test_thesis_skipped_when_subagents_skip() -> None:
    outcome = generate_thesis(
        _polymarket_input(
            sub_verdicts=[Verdict.SKIP, Verdict.SKIP, Verdict.SKIP],
        ),
        now=_now(),
    )
    assert outcome.decision == "SUB_AGENT_SKIP"


def test_thesis_verdict_mismatch_returns_typed_decision() -> None:
    """Checks say BUY, sub-agents say SELL → VERDICT_MISMATCH (refuse, log warning)."""
    outcome = generate_thesis(
        _polymarket_input(
            check_verdicts=[Verdict.BUY] * 4,
            sub_verdicts=[Verdict.SELL, Verdict.SELL, Verdict.SKIP],
        ),
        now=_now(),
    )
    assert outcome.decision == "VERDICT_MISMATCH"


def test_thesis_rejects_duplicate_check_types() -> None:
    """LLD §1.8.2 boundary validation."""
    inp = _polymarket_input()
    # Replace one check with a duplicate of base_rate.
    dup = _check(CheckType.BASE_RATE, Verdict.BUY)
    inp = inp.model_copy(update={"check_results": [dup, dup, *inp.check_results[2:]]})
    with pytest.raises(ValueError, match="distinct check_types"):
        generate_thesis(inp, now=_now())


def test_thesis_rejects_alpaca_check_set_for_polymarket_venue() -> None:
    """Wrong check set for venue is fail-fast."""
    inp = _polymarket_input()
    # Swap whale → unusual_volume (Alpaca's check); Polymarket should reject.
    new_checks = list(inp.check_results)
    new_checks[2] = _check(CheckType.UNUSUAL_VOLUME, Verdict.BUY)
    inp = inp.model_copy(update={"check_results": new_checks})
    with pytest.raises(ValueError, match="must match"):
        generate_thesis(inp, now=_now())


def test_thesis_alpaca_requires_target_stop_horizon() -> None:
    """REQ-BRN-007."""
    types = [CheckType.BASE_RATE, CheckType.NEWS, CheckType.UNUSUAL_VOLUME, CheckType.DISPOSITION]
    sub_agents = [SubAgent.ARBITRAGE, SubAgent.CONVERGENCE, SubAgent.FLOW_COPY]
    alpaca_checks = [
        CheckResult(
            bot=Bot.CLAUDE,
            venue=VenueName.ALPACA,
            market_id="AAPL",
            check_type=t,
            verdict=Verdict.BUY,
            confidence=Decimal("0.85"),
            p_win=Decimal("0.7"),
            rationale="t",
            model_id="m",
            correlation_id=uuid4(),
        )
        for t in types
    ]
    alpaca_subs = [
        CheckResult(
            bot=Bot.CLAUDE,
            venue=VenueName.ALPACA,
            market_id="AAPL",
            check_type=CheckType.BASE_RATE,
            sub_agent=sa,
            verdict=Verdict.BUY,
            confidence=Decimal("0.85"),
            p_win=Decimal("0.7"),
            rationale="t",
            model_id="m",
            correlation_id=uuid4(),
        )
        for sa in sub_agents
    ]
    inp = ThesisInput(
        bot=Bot.CLAUDE,
        venue=VenueName.ALPACA,
        market_id="AAPL",
        check_results=alpaca_checks,
        sub_agent_results=alpaca_subs,
        scan_correlation_id=uuid4(),
        confidence_threshold=Decimal("0.75"),
        # missing target/stop/horizon
    )
    with pytest.raises(ValueError, match="target_price"):
        generate_thesis(inp, now=_now())
