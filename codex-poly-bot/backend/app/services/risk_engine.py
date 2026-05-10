"""Risk engine helpers for shared and venue-specific refusal checks.

REQ: REQ-ALP-009, REQ-ALP-010, REQ-ALP-011, REQ-ALP-012
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
