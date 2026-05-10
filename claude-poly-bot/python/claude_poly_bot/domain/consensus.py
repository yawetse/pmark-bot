"""Pure consensus aggregation for the brain.

`aggregate_check_results` operates on the 4 base checks (3-of-4 majority).
`aggregate_sub_agent_votes` operates on the 3 sub-agents (FULL / HALF / SKIP).

Traces: REQ-BRN-009 (3-of-4 check majority), REQ-BRN-011 (model config),
REQ-EXE-004 (sub-agent consensus sizing).
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from claude_poly_bot.domain.models import (
    CheckResult,
    Probability,
    Verdict,
)


class CheckConsensus(BaseModel):
    """Result of aggregating the 4 base checks."""

    model_config = ConfigDict(frozen=True, strict=True)
    verdict: Verdict
    agreeing_count: int
    total_count: int
    mean_confidence: Probability
    mean_p_win: Probability


class SubAgentConsensus(BaseModel):
    """Result of aggregating the 3 sub-agent votes."""

    model_config = ConfigDict(frozen=True, strict=True)
    size_multiplier: Literal["FULL", "HALF", "SKIP"]
    verdict: Verdict
    agreeing_count: int
    total_count: int


# REQ: REQ-BRN-009 - 3-of-4 majority on the 4 base checks.
def aggregate_check_results(results: list[CheckResult]) -> CheckConsensus:
    """3-of-4 majority verdict; mean confidence & p_win across agreeing
    checks. SKIP if no majority.

    Defensive: this function does NOT enforce list length here (caller's
    responsibility — see `domain.thesis.generate_thesis` for boundary
    validation). Operates on whatever is passed.
    """
    if not results:
        return CheckConsensus(
            verdict=Verdict.SKIP,
            agreeing_count=0,
            total_count=0,
            mean_confidence=Decimal("0"),
            mean_p_win=Decimal("0.5"),
        )

    counts = Counter(r.verdict for r in results)
    total = len(results)
    threshold = max(3, (total // 2) + 1)  # at least 3 of 4 by default
    if counts.get(Verdict.BUY, 0) >= threshold:
        winner = Verdict.BUY
    elif counts.get(Verdict.SELL, 0) >= threshold:
        winner = Verdict.SELL
    else:
        winner = Verdict.SKIP

    if winner == Verdict.SKIP:
        return CheckConsensus(
            verdict=winner,
            agreeing_count=0,
            total_count=total,
            mean_confidence=Decimal("0"),
            mean_p_win=Decimal("0.5"),
        )

    agreeing = [r for r in results if r.verdict == winner]
    mean_confidence = sum((Decimal(r.confidence) for r in agreeing), Decimal(0)) / Decimal(
        len(agreeing)
    )
    mean_p_win = sum((Decimal(r.p_win) for r in agreeing), Decimal(0)) / Decimal(len(agreeing))
    return CheckConsensus(
        verdict=winner,
        agreeing_count=len(agreeing),
        total_count=total,
        mean_confidence=mean_confidence,
        mean_p_win=mean_p_win,
    )


# REQ: REQ-EXE-004 - sub-agent consensus → FULL / HALF / SKIP.
def aggregate_sub_agent_votes(votes: list[CheckResult]) -> SubAgentConsensus:
    """3 sub-agent votes: 2+ agree on a non-SKIP → FULL; exactly 1 non-SKIP
    → HALF; otherwise SKIP. Verdict is the dominant non-SKIP verdict (or
    SKIP if no non-SKIP majority).
    """
    non_skips = [v for v in votes if v.verdict != Verdict.SKIP]
    counts = Counter(v.verdict for v in non_skips)

    # Find dominant non-SKIP verdict
    if counts.get(Verdict.BUY, 0) >= 2:
        dominant: Verdict = Verdict.BUY
        size: Literal["FULL", "HALF", "SKIP"] = "FULL"
    elif counts.get(Verdict.SELL, 0) >= 2:
        dominant = Verdict.SELL
        size = "FULL"
    elif len(non_skips) == 1:
        dominant = non_skips[0].verdict
        size = "HALF"
    else:
        dominant = Verdict.SKIP
        size = "SKIP"

    return SubAgentConsensus(
        size_multiplier=size,
        verdict=dominant,
        agreeing_count=counts.get(dominant, 0) if dominant != Verdict.SKIP else 0,
        total_count=len(votes),
    )
