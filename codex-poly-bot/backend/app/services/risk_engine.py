"""Risk engine helpers for shared and venue-specific refusal checks.

REQ: REQ-EXE-004, REQ-EXE-005, REQ-EXE-006, REQ-EXE-009,
REQ-EXE-013, REQ-EXE-014, REQ-EXE-017, REQ-ALP-009,
REQ-ALP-010, REQ-ALP-011, REQ-ALP-012
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.config_service import default_config_payload


@dataclass(frozen=True)
class AlpacaRiskConfig:
    """Default Alpaca risk limits.

    REQ: REQ-ALP-009, REQ-ALP-010, REQ-ALP-011, REQ-ALP-012
    """

    max_position_usd: Decimal
    max_daily_loss_usd: Decimal
    max_open_positions: int
    max_portfolio_allocation_per_symbol: Decimal


@dataclass(frozen=True)
class AlpacaRiskInput:
    """Inputs needed to evaluate Alpaca risk defaults.

    REQ: REQ-ALP-009, REQ-ALP-010, REQ-ALP-011, REQ-ALP-012
    """

    proposed_notional: Decimal | str
    projected_symbol_exposure: Decimal | str
    daily_loss: Decimal | str
    open_positions: int
    creates_new_position: bool
    model_capital: Decimal | str


@dataclass(frozen=True)
class PolymarketRiskConfig:
    """Default Polymarket risk limits.

    REQ: REQ-EXE-004, REQ-EXE-005, REQ-EXE-006
    """

    max_position_usd: Decimal
    max_daily_loss_usd: Decimal
    max_open_positions: int


@dataclass(frozen=True)
class PolymarketRiskInput:
    """Inputs needed to evaluate Polymarket risk limits.

    REQ: REQ-EXE-004, REQ-EXE-005, REQ-EXE-006
    """

    proposed_notional: Decimal | str
    daily_loss: Decimal | str
    open_positions: int
    creates_new_position: bool


@dataclass(frozen=True)
class LiveOrderGateInput:
    """Boolean live-order blockers resolved before venue submission.

    REQ: REQ-EXE-013, REQ-EXE-014, REQ-EXE-017
    """

    live_enabled: bool
    venue_enabled: bool
    credentials_present: bool
    venue_config_supported: bool
    market_data_fresh: bool
    scoring_succeeded: bool
    risk_approved: bool
    account_mode_valid: bool
    kill_switch_active: bool = False
    risk_refusal_reason: str | None = None


@dataclass(frozen=True)
class RiskLimitResult:
    """Stable result from venue-specific risk checks."""

    approved: bool
    refusal_reasons: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def refusal_reason(self) -> str | None:
        return self.refusal_reasons[0] if self.refusal_reasons else None


def _decimal(value: Decimal | str, field_name: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return decimal


def default_alpaca_risk_config(payload: dict[str, Any] | None = None) -> AlpacaRiskConfig:
    """Load Alpaca risk limits from the default runtime payload.

    REQ: REQ-ALP-009, REQ-ALP-010, REQ-ALP-011, REQ-ALP-012
    """

    source = payload or default_config_payload()
    risk = source["risk"]["alpaca"]
    return AlpacaRiskConfig(
        max_position_usd=_decimal(risk["max_position_usd"], "max_position_usd"),
        max_daily_loss_usd=_decimal(risk["max_daily_loss_usd"], "max_daily_loss_usd"),
        max_open_positions=int(risk["max_open_positions"]),
        max_portfolio_allocation_per_symbol=_decimal(
            risk["max_portfolio_allocation_per_symbol"],
            "max_portfolio_allocation_per_symbol",
        ),
    )


def default_polymarket_risk_config(payload: dict[str, Any] | None = None) -> PolymarketRiskConfig:
    """Load Polymarket risk limits from the default runtime payload.

    REQ: REQ-EXE-004, REQ-EXE-005, REQ-EXE-006
    """

    source = payload or default_config_payload()
    risk = source["risk"]["polymarket"]
    return PolymarketRiskConfig(
        max_position_usd=_decimal(risk["max_position_usd"], "max_position_usd"),
        max_daily_loss_usd=_decimal(risk["max_daily_loss_usd"], "max_daily_loss_usd"),
        max_open_positions=int(risk["max_open_positions"]),
    )


def evaluate_polymarket_risk_limits(
    risk_input: PolymarketRiskInput,
    config: PolymarketRiskConfig | None = None,
) -> RiskLimitResult:
    """Evaluate default Polymarket position, loss, and open-position limits.

    REQ: REQ-EXE-004, REQ-EXE-005, REQ-EXE-006
    """

    limits = config or default_polymarket_risk_config()
    proposed_notional = _decimal(risk_input.proposed_notional, "proposed_notional")
    daily_loss = _decimal(risk_input.daily_loss, "daily_loss")
    projected_open_positions = risk_input.open_positions + (
        1 if risk_input.creates_new_position else 0
    )

    reasons: list[str] = []
    if proposed_notional <= 0:
        reasons.append("KELLY_NON_POSITIVE")
    if proposed_notional > limits.max_position_usd:
        reasons.append("MAX_POSITION_LIMIT")
    if daily_loss >= limits.max_daily_loss_usd:
        reasons.append("DAILY_LOSS_LIMIT")
    if projected_open_positions > limits.max_open_positions:
        reasons.append("OPEN_POSITION_LIMIT")

    return RiskLimitResult(
        approved=not reasons,
        refusal_reasons=tuple(dict.fromkeys(reasons)),
        payload={
            "max_position_usd": str(limits.max_position_usd),
            "max_daily_loss_usd": str(limits.max_daily_loss_usd),
            "max_open_positions": limits.max_open_positions,
            "projected_open_positions": projected_open_positions,
        },
    )


def check_positive_order_size(size: Decimal | str) -> RiskLimitResult:
    """Refuse trades when Kelly sizing returns a non-positive notional.

    REQ: REQ-EXE-009
    """

    notional = _decimal(size, "size")
    if notional <= 0:
        return RiskLimitResult(
            approved=False,
            refusal_reasons=("KELLY_NON_POSITIVE",),
            payload={"size": str(notional)},
        )
    return RiskLimitResult(approved=True, payload={"size": str(notional)})


def evaluate_live_order_gates(gates: LiveOrderGateInput) -> RiskLimitResult:
    """Return stable live-order refusal codes before any venue submit.

    REQ: REQ-EXE-013, REQ-EXE-014, REQ-EXE-017
    """

    reasons: list[str] = []
    if not gates.live_enabled:
        reasons.append("LIVE_DISABLED")
    if gates.kill_switch_active:
        reasons.append("KILL_SWITCH_ACTIVE")
    if not gates.venue_enabled:
        reasons.append("VENUE_DISABLED")
    if not gates.venue_config_supported or not gates.account_mode_valid:
        reasons.append("UNSUPPORTED_VENUE_CONFIG")
    if not gates.credentials_present:
        reasons.append("CREDENTIAL_MISSING")
    if not gates.market_data_fresh:
        reasons.append("STALE_MARKET_DATA")
    if not gates.scoring_succeeded:
        reasons.append("SCORING_MISSING_OR_FAILED")
    if not gates.risk_approved:
        reasons.append(gates.risk_refusal_reason or "RISK_CHECK_FAILED")

    return RiskLimitResult(
        approved=not reasons,
        refusal_reasons=tuple(dict.fromkeys(reasons)),
        payload={
            "live_enabled": gates.live_enabled,
            "venue_enabled": gates.venue_enabled,
            "kill_switch_active": gates.kill_switch_active,
        },
    )


def evaluate_alpaca_risk_limits(
    risk_input: AlpacaRiskInput,
    config: AlpacaRiskConfig | None = None,
) -> RiskLimitResult:
    """Evaluate default Alpaca position, loss, open-position, and allocation limits.

    REQ: REQ-ALP-009, REQ-ALP-010, REQ-ALP-011, REQ-ALP-012
    """

    limits = config or default_alpaca_risk_config()
    proposed_notional = _decimal(risk_input.proposed_notional, "proposed_notional")
    projected_symbol_exposure = _decimal(
        risk_input.projected_symbol_exposure,
        "projected_symbol_exposure",
    )
    daily_loss = _decimal(risk_input.daily_loss, "daily_loss")
    model_capital = _decimal(risk_input.model_capital, "model_capital")
    projected_open_positions = risk_input.open_positions + (1 if risk_input.creates_new_position else 0)
    max_symbol_allocation_usd = model_capital * limits.max_portfolio_allocation_per_symbol

    reasons: list[str] = []
    if proposed_notional < 0:
        reasons.append("INVALID_NOTIONAL")
    if projected_symbol_exposure > limits.max_position_usd:
        reasons.append("MAX_POSITION_LIMIT")
    if daily_loss >= limits.max_daily_loss_usd:
        reasons.append("DAILY_LOSS_LIMIT")
    if projected_open_positions > limits.max_open_positions:
        reasons.append("OPEN_POSITION_LIMIT")
    if model_capital <= 0 or projected_symbol_exposure > max_symbol_allocation_usd:
        reasons.append("ALPACA_ALLOCATION_LIMIT")

    return RiskLimitResult(
        approved=not reasons,
        refusal_reasons=tuple(dict.fromkeys(reasons)),
        payload={
            "max_position_usd": str(limits.max_position_usd),
            "max_daily_loss_usd": str(limits.max_daily_loss_usd),
            "max_open_positions": limits.max_open_positions,
            "max_portfolio_allocation_per_symbol": str(
                limits.max_portfolio_allocation_per_symbol
            ),
            "max_symbol_allocation_usd": str(max_symbol_allocation_usd),
            "projected_open_positions": projected_open_positions,
        },
    )
