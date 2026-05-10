"""Exit monitoring trigger and execution helpers.

REQ: REQ-EXT-002, REQ-EXT-003, REQ-EXT-004, REQ-EXT-005,
REQ-EXT-006
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain import ExitTrigger, ExitTriggerType, PositionSnapshot, Venue


@dataclass(frozen=True)
class ExitExecutionRequest:
    """Exit execution request after trigger and risk approval.

    REQ: REQ-EXT-005, REQ-EXT-006
    """

    position_id: str
    venue: Venue
    global_execution_mode: str
    risk_approved: bool
    risk_refusal_reason: str | None = None


@dataclass(frozen=True)
class ExitExecutionResult:
    """Dry-run, live, or refused exit execution result.

    REQ: REQ-EXT-005, REQ-EXT-006
    """

    status: str
    exit_recorded: bool
    venue_submitted: bool
    refusal_reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def evaluate_profit_target_exit(
    position: PositionSnapshot,
    *,
    profit_target: Decimal,
) -> ExitTrigger | None:
    """Create a profit-target exit when unrealized P&L reaches threshold.

    REQ: REQ-EXT-002
    """

    threshold = _as_decimal(profit_target)
    if position.unrealized_pnl < threshold:
        return None
    return ExitTrigger(
        trigger_type=ExitTriggerType.PROFIT_TARGET,
        position_id=position.position_id,
        threshold=threshold,
        observed_value=position.unrealized_pnl,
        reason="profit target reached",
    )


def evaluate_volume_spike_exit(
    *,
    position_id: str,
    observed_volume: Decimal,
    baseline_volume: Decimal,
    multiplier_threshold: Decimal,
    stale_data: bool,
) -> ExitTrigger | None:
    """Create a volume-spike exit when fresh volume crosses threshold.

    REQ: REQ-EXT-003
    """

    if stale_data:
        return None
    baseline = _as_decimal(baseline_volume)
    if baseline <= 0:
        return None
    observed = _as_decimal(observed_volume)
    threshold = _as_decimal(multiplier_threshold)
    multiplier = observed / baseline
    if multiplier < threshold:
        return None
    return ExitTrigger(
        trigger_type=ExitTriggerType.VOLUME_SPIKE,
        position_id=position_id,
        threshold=threshold,
        observed_value=multiplier,
        reason="volume spike threshold reached",
    )


def evaluate_stale_thesis_exit(
    *,
    position_id: str,
    thesis_age_hours: Decimal,
    max_age_hours: Decimal,
    price_move_pct: Decimal,
    min_price_move_pct: Decimal,
) -> ExitTrigger | None:
    """Create a stale-thesis exit when age and price movement both cross.

    REQ: REQ-EXT-004
    """

    age = _as_decimal(thesis_age_hours)
    max_age = _as_decimal(max_age_hours)
    movement = abs(_as_decimal(price_move_pct))
    min_movement = _as_decimal(min_price_move_pct)
    if age < max_age or movement < min_movement:
        return None
    return ExitTrigger(
        trigger_type=ExitTriggerType.STALE_THESIS,
        position_id=position_id,
        threshold=max_age,
        observed_value=age,
        reason="stale thesis threshold reached",
    )


def execute_exit_order(
    request: ExitExecutionRequest,
    *,
    submitter: Any,
) -> ExitExecutionResult:
    """Record simulated exits or submit approved live exits.

    REQ: REQ-EXT-005, REQ-EXT-006
    """

    if not request.risk_approved:
        return ExitExecutionResult(
            status="refused",
            exit_recorded=False,
            venue_submitted=False,
            refusal_reason=request.risk_refusal_reason or "RISK_CHECK_FAILED",
        )
    if request.global_execution_mode == "dry_run":
        return ExitExecutionResult(
            status="simulated",
            exit_recorded=True,
            venue_submitted=False,
            payload={
                "position_id": request.position_id,
                "venue": request.venue.value,
            },
        )
    if request.global_execution_mode != "live":
        return ExitExecutionResult(
            status="refused",
            exit_recorded=False,
            venue_submitted=False,
            refusal_reason="LIVE_DISABLED",
        )

    venue_order_id = submitter.submit_order()
    return ExitExecutionResult(
        status="submitted",
        exit_recorded=True,
        venue_submitted=True,
        payload={
            "position_id": request.position_id,
            "venue": request.venue.value,
            "venue_order_id": venue_order_id,
        },
    )


def _as_decimal(value: Any) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("value must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError("value must be finite")
    return decimal
