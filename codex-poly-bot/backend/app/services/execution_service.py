"""Execution service helpers for dry-run and live order paths.

REQ: REQ-ALP-005, REQ-ALP-006, REQ-ALP-007
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.venues.polymarket import VenueCallResult


class AlpacaVenueSubmitter(Protocol):
    """Minimal submitter boundary used by execution tests.

    REQ: REQ-ALP-006
    """

    def submit_order(self, *, account_mode: str, symbol: str, notional: Decimal) -> str:
        ...


@dataclass(frozen=True)
class AlpacaExecutionRequest:
    """Alpaca execution request after risk evaluation.

    REQ: REQ-ALP-005, REQ-ALP-006, REQ-ALP-007
    """

    global_execution_mode: str
    account_mode: str
    risk_approved: bool
    symbol: str
    notional: Decimal | str
    risk_refusal_reason: str | None = None


@dataclass(frozen=True)
class AlpacaExecutionResult:
    """Result from dry-run, live, or refused Alpaca execution."""

    status: str
    order_recorded: bool
    broker_submitted: bool
    refusal_reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class FakeAlpacaVenueSubmitter:
    """Fake Alpaca submitter that records calls without external I/O."""

    def __init__(self) -> None:
        self.submit_calls = 0
        self.submitted_modes: tuple[str, ...] = ()

    def submit_order(self, *, account_mode: str, symbol: str, notional: Decimal) -> str:
        """Record an approved submit call.

        REQ: REQ-ALP-006
        """

        self.submit_calls += 1
        self.submitted_modes = (*self.submitted_modes, account_mode)
        return f"alpaca-{account_mode}-{symbol}-{self.submit_calls}"


def _decimal(value: Decimal | str, field_name: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return decimal


def resolve_alpaca_account_mode(raw_mode: str) -> VenueCallResult:
    """Validate Alpaca account mode configuration values.

    REQ: REQ-ALP-007
    """

    account_mode = raw_mode.strip().lower()
    if account_mode not in {"paper", "live"}:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("alpaca account mode must be paper or live",),
            payload={"account_mode": account_mode},
        )
    return VenueCallResult(ok=True, payload={"account_mode": account_mode})


def execute_alpaca_order(
    request: AlpacaExecutionRequest,
    *,
    submitter: AlpacaVenueSubmitter,
) -> AlpacaExecutionResult:
    """Record simulated Alpaca orders or submit approved live orders.

    REQ: REQ-ALP-005, REQ-ALP-006, REQ-ALP-007
    """

    notional = _decimal(request.notional, "notional")
    symbol = request.symbol.strip().upper()
    mode_result = resolve_alpaca_account_mode(request.account_mode)
    if not mode_result.ok:
        return AlpacaExecutionResult(
            status="refused",
            order_recorded=False,
            broker_submitted=False,
            refusal_reason=mode_result.refusal_reason,
        )
    if not request.risk_approved:
        return AlpacaExecutionResult(
            status="refused",
            order_recorded=False,
            broker_submitted=False,
            refusal_reason=request.risk_refusal_reason or "RISK_CHECK_FAILED",
        )
    if request.global_execution_mode == "dry_run":
        return AlpacaExecutionResult(
            status="simulated",
            order_recorded=True,
            broker_submitted=False,
            payload={
                "account_mode": mode_result.payload["account_mode"],
                "notional": str(notional),
                "symbol": symbol,
            },
        )
    if request.global_execution_mode != "live":
        return AlpacaExecutionResult(
            status="refused",
            order_recorded=False,
            broker_submitted=False,
            refusal_reason="LIVE_DISABLED",
        )

    venue_order_id = submitter.submit_order(
        account_mode=mode_result.payload["account_mode"],
        symbol=symbol,
        notional=notional,
    )
    return AlpacaExecutionResult(
        status="submitted",
        order_recorded=True,
        broker_submitted=True,
        payload={
            "account_mode": mode_result.payload["account_mode"],
            "notional": str(notional),
            "symbol": symbol,
            "venue_order_id": venue_order_id,
        },
    )
