"""Thesis aggregation: combine 4-check consensus + 3-sub-agent consensus
into a single Thesis or a typed reason for not producing one.

Traces: REQ-BRN-009, REQ-BRN-010, REQ-BRN-007 (Alpaca extras), DD-019
(deterministic decision_correlation_id).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict

from claude_poly_bot.domain.consensus import (
    CheckConsensus,
    SubAgentConsensus,
    aggregate_check_results,
    aggregate_sub_agent_votes,
)
from claude_poly_bot.domain.models import (
    Bot,
    CheckResult,
    CheckType,
    Price,
    Probability,
    SubAgent,
    Thesis,
    VenueName,
    Verdict,
)


class ThesisInput(BaseModel):
    """Input for `generate_thesis`. Construct once per candidate
    evaluation. Strict-validated; field shape errors fail fast."""

    model_config = ConfigDict(frozen=True, strict=True)

    bot: Bot
    venue: VenueName
    market_id: str
    check_results: list[CheckResult]
    sub_agent_results: list[CheckResult]
    scan_correlation_id: UUID
    confidence_threshold: Probability
    target_price: Price | None = None
    stop_price: Price | None = None
    horizon_hours: int | None = None


class ThesisOutcome(BaseModel):
    """Result of `generate_thesis`. `thesis is None` ⇒ explained by `decision`."""

    model_config = ConfigDict(frozen=True, strict=True)

    thesis: Thesis | None
    decision: Literal[
        "PRODUCED",
        "BELOW_CONFIDENCE",
        "NO_CHECK_CONSENSUS",
        "SUB_AGENT_SKIP",
        "VERDICT_MISMATCH",
    ]
    check_consensus: CheckConsensus
    sub_agent_consensus: SubAgentConsensus


# REQ: DD-019 - deterministic decision_correlation_id per (scan, bot).
def derive_decision_correlation_id(scan_correlation_id: UUID, bot: Bot) -> UUID:
    return uuid5(NAMESPACE_URL, f"{scan_correlation_id}:{bot.value}")


# Per-venue expected check sets (REQ-BRN-001 / REQ-BRN-004 - whale ↔ unusual_volume).
_POLYMARKET_CHECKS = frozenset(
    {CheckType.BASE_RATE, CheckType.NEWS, CheckType.WHALE, CheckType.DISPOSITION}
)
_ALPACA_CHECKS = frozenset(
    {CheckType.BASE_RATE, CheckType.NEWS, CheckType.UNUSUAL_VOLUME, CheckType.DISPOSITION}
)


# REQ: REQ-BRN-009, REQ-BRN-010 - thesis generation with confidence threshold.
def generate_thesis(input: ThesisInput, *, now: datetime) -> ThesisOutcome:
    """Aggregate checks + sub-agents, validate venue-specific shape, and
    return a Thesis or a typed reason for skipping.
    """
    # Boundary validation (defensive-depth at module boundary per LLD §1.8.2).
    if len(input.check_results) != 4:
        raise ValueError(f"check_results must have 4 entries, got {len(input.check_results)}")
    if len(input.sub_agent_results) != 3:
        raise ValueError(
            f"sub_agent_results must have 3 entries, got {len(input.sub_agent_results)}"
        )
    check_types = {r.check_type for r in input.check_results}
    if len(check_types) != 4:
        raise ValueError(f"check_results must have 4 distinct check_types, got {check_types}")
    expected = _POLYMARKET_CHECKS if input.venue == VenueName.POLYMARKET else _ALPACA_CHECKS
    if check_types != expected:
        raise ValueError(
            f"check_results for {input.venue.value} must match {expected}, got {check_types}"
        )
    sub_agents = {r.sub_agent for r in input.sub_agent_results if r.sub_agent is not None}
    if len(sub_agents) != 3:
        raise ValueError(f"sub_agent_results must have 3 distinct sub_agents, got {sub_agents}")

    cc = aggregate_check_results(input.check_results)
    sc = aggregate_sub_agent_votes(input.sub_agent_results)

    if cc.verdict == Verdict.SKIP:
        return ThesisOutcome(
            thesis=None, decision="NO_CHECK_CONSENSUS", check_consensus=cc, sub_agent_consensus=sc
        )
    if cc.mean_confidence < input.confidence_threshold:
        return ThesisOutcome(
            thesis=None, decision="BELOW_CONFIDENCE", check_consensus=cc, sub_agent_consensus=sc
        )
    if sc.size_multiplier == "SKIP":
        return ThesisOutcome(
            thesis=None, decision="SUB_AGENT_SKIP", check_consensus=cc, sub_agent_consensus=sc
        )
    if sc.verdict != cc.verdict:
        # Sub-agents say BUY but checks say SELL (or vice versa) — refuse.
        return ThesisOutcome(
            thesis=None, decision="VERDICT_MISMATCH", check_consensus=cc, sub_agent_consensus=sc
        )

    # Alpaca theses must include target/stop/horizon (REQ-BRN-007).
    if input.venue == VenueName.ALPACA and (
        input.target_price is None or input.stop_price is None or input.horizon_hours is None
    ):
        raise ValueError("Alpaca thesis requires target_price, stop_price, and horizon_hours")

    decision_correlation_id = derive_decision_correlation_id(input.scan_correlation_id, input.bot)

    thesis = Thesis(
        bot=input.bot,
        venue=input.venue,
        market_id=input.market_id,
        verdict=cc.verdict,
        p_win=cc.mean_p_win,
        confidence=cc.mean_confidence,
        size_multiplier=sc.size_multiplier,
        target_price=input.target_price,
        stop_price=input.stop_price,
        horizon_hours=input.horizon_hours,
        scan_correlation_id=input.scan_correlation_id,
        decision_correlation_id=decision_correlation_id,
        created_at=now if now.tzinfo is not None else now.astimezone(),
    )
    return ThesisOutcome(
        thesis=thesis, decision="PRODUCED", check_consensus=cc, sub_agent_consensus=sc
    )


# silence unused-import warnings for types kept for caller convenience
_ = (SubAgent,)
