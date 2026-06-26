"""Execution service helpers for dry-run and live order paths.

REQ: REQ-EXE-002, REQ-EXE-015, REQ-ALP-005, REQ-ALP-006,
REQ-ALP-007
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.domain import ModelProvider, Venue
from app.venues.polymarket import PolymarketLiveOrderRequest, VenueCallResult


class AlpacaVenueSubmitter(Protocol):
    """Minimal submitter boundary used by execution tests.

    REQ: REQ-ALP-006
    """

    def submit_order(
        self,
        *,
        account_mode: str,
        symbol: str,
        notional: Decimal | None = None,
        quantity: Decimal | None = None,
        side: str = "buy",
        client_order_id: str | None = None,
    ) -> str:
        ...


class PolymarketVenueSubmitter(Protocol):
    """Minimal Polymarket submitter boundary used by execution tests.

    REQ: REQ-VEN-004, REQ-EXE-010
    """

    def submit_order(self, request: PolymarketLiveOrderRequest) -> VenueCallResult:
        ...


class PolymarketPositionCloser(Protocol):
    """Minimal Polymarket close-position boundary used by live exits."""

    def close_position(
        self,
        *,
        market_slug: str,
        current_price: Decimal | str | None = None,
        slippage_tolerance_bips: int | None = None,
        slippage_tolerance_ticks: int | None = None,
    ) -> VenueCallResult:
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
    client_order_id: str | None = None


@dataclass(frozen=True)
class PolymarketExecutionRequest:
    """Polymarket execution request after risk evaluation.

    REQ: REQ-VEN-004, REQ-EXE-010, REQ-EXE-011
    """

    global_execution_mode: str
    risk_approved: bool
    order: PolymarketLiveOrderRequest
    risk_refusal_reason: str | None = None


@dataclass(frozen=True)
class AlpacaExecutionResult:
    """Result from dry-run, live, or refused Alpaca execution."""

    status: str
    order_recorded: bool
    broker_submitted: bool
    refusal_reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DryRunOrderRequest:
    """Dry-run order request for any supported venue.

    REQ: REQ-EXE-002
    """

    venue: Venue
    model_provider: ModelProvider
    order_id: str
    notional: Decimal | str


@dataclass(frozen=True)
class ExecutionResult:
    """Generic dry-run or venue execution result.

    REQ: REQ-EXE-002, REQ-EXE-015
    """

    status: str
    order_recorded: bool
    broker_submitted: bool
    refusal_reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenOrder:
    """Known live order eligible for kill-switch cancellation.

    REQ: REQ-EXE-015
    """

    order_id: str
    venue: Venue
    venue_order_id: str


@dataclass(frozen=True)
class KillSwitchCancelResult:
    """Aggregate result for kill-switch cancel attempts.

    REQ: REQ-EXE-015
    """

    status: str
    cancel_attempts: tuple[str, ...] = ()
    canceled_order_ids: tuple[str, ...] = ()
    failed_order_ids: tuple[str, ...] = ()


class FakeAlpacaVenueSubmitter:
    """Fake Alpaca submitter that records calls without external I/O."""

    def __init__(self) -> None:
        self.submit_calls = 0
        self.submitted_modes: tuple[str, ...] = ()
        self.submitted_orders: tuple[dict[str, str], ...] = ()

    def submit_order(
        self,
        *,
        account_mode: str,
        symbol: str,
        notional: Decimal | None = None,
        quantity: Decimal | None = None,
        side: str = "buy",
        client_order_id: str | None = None,
    ) -> str:
        """Record an approved submit call.

        REQ: REQ-ALP-006
        """

        self.submit_calls += 1
        self.submitted_modes = (*self.submitted_modes, account_mode)
        self.submitted_orders = (
            *self.submitted_orders,
            {
                "account_mode": account_mode,
                "symbol": symbol,
                "notional": str(notional) if notional is not None else "",
                "quantity": str(quantity) if quantity is not None else "",
                "side": side,
                "client_order_id": client_order_id or "",
            },
        )
        return f"alpaca-{account_mode}-{symbol}-{self.submit_calls}"


class FakeVenueSubmitter:
    """Generic fake submitter used to prove dry-run avoids venue calls.

    REQ: REQ-EXE-002
    """

    def __init__(self) -> None:
        self.submit_calls = 0

    def submit_order(self) -> str:
        self.submit_calls += 1
        return f"venue-order-{self.submit_calls}"


class FakeCancelVenue:
    """Fake cancel adapter for kill-switch tests.

    REQ: REQ-EXE-015
    """

    def __init__(self, *, fail_order_ids: frozenset[str] = frozenset()) -> None:
        self.fail_order_ids = fail_order_ids
        self.cancel_calls = 0
        self.canceled_venue_order_ids: tuple[str, ...] = ()

    def cancel_order(self, *, venue: Venue, venue_order_id: str) -> bool:
        """Record cancel attempt and return success/failure.

        REQ: REQ-EXE-015
        """

        self.cancel_calls += 1
        self.canceled_venue_order_ids = (*self.canceled_venue_order_ids, venue_order_id)
        return venue_order_id not in self.fail_order_ids


def _decimal(value: Decimal | str, field_name: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return decimal


def execute_dry_run_order(
    request: DryRunOrderRequest,
    *,
    submitter: FakeVenueSubmitter,
) -> ExecutionResult:
    """Record a simulated order without calling the venue submitter.

    REQ: REQ-EXE-002
    """

    notional = _decimal(request.notional, "notional")
    return ExecutionResult(
        status="simulated",
        order_recorded=True,
        broker_submitted=False,
        payload={
            "order_id": request.order_id,
            "venue": request.venue.value,
            "model_provider": request.model_provider.value,
            "notional": str(notional),
            "submit_calls": submitter.submit_calls,
        },
    )


def execute_polymarket_order(
    request: PolymarketExecutionRequest,
    *,
    submitter: PolymarketVenueSubmitter,
) -> ExecutionResult:
    """Record simulated Polymarket orders or submit approved live orders.

    REQ: REQ-VEN-004, REQ-EXE-010, REQ-EXE-011
    """

    if not request.risk_approved:
        return ExecutionResult(
            status="refused",
            order_recorded=False,
            broker_submitted=False,
            refusal_reason=request.risk_refusal_reason or "RISK_CHECK_FAILED",
        )
    if request.global_execution_mode == "dry_run":
        return ExecutionResult(
            status="simulated",
            order_recorded=True,
            broker_submitted=False,
            payload={
                "market_slug": request.order.market_slug,
                "order_type": request.order.order_type.value
                if hasattr(request.order.order_type, "value")
                else str(request.order.order_type),
                "venue": Venue.POLYMARKET_US.value,
            },
        )
    if request.global_execution_mode != "live":
        return ExecutionResult(
            status="refused",
            order_recorded=False,
            broker_submitted=False,
            refusal_reason="LIVE_DISABLED",
        )

    venue_result = submitter.submit_order(request.order)
    if not venue_result.ok:
        return ExecutionResult(
            status="refused",
            order_recorded=False,
            broker_submitted=False,
            refusal_reason=venue_result.refusal_reason,
            payload=venue_result.payload,
        )
    return ExecutionResult(
        status="submitted",
        order_recorded=True,
        broker_submitted=True,
        payload=venue_result.payload,
    )


def cancel_open_orders_for_kill_switch(
    open_orders: tuple[OpenOrder, ...],
    *,
    canceler: FakeCancelVenue,
) -> KillSwitchCancelResult:
    """Attempt cancellation for every known open order after kill switch.

    REQ: REQ-EXE-015
    """

    attempted: list[str] = []
    canceled: list[str] = []
    failed: list[str] = []
    for order in open_orders:
        attempted.append(order.order_id)
        ok = canceler.cancel_order(
            venue=order.venue,
            venue_order_id=order.venue_order_id,
        )
        if ok:
            canceled.append(order.order_id)
            continue
        failed.append(order.order_id)

    return KillSwitchCancelResult(
        status="cancel_failed" if failed else "cancel_requested",
        cancel_attempts=tuple(attempted),
        canceled_order_ids=tuple(canceled),
        failed_order_ids=tuple(failed),
    )


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

    try:
        venue_order_id = submitter.submit_order(
            account_mode=mode_result.payload["account_mode"],
            symbol=symbol,
            notional=notional,
            side="buy",
            client_order_id=request.client_order_id,
        )
    except Exception as exc:
        return AlpacaExecutionResult(
            status="refused",
            order_recorded=False,
            broker_submitted=False,
            refusal_reason=_submit_exception_reason(exc),
            payload=_submit_exception_payload(exc),
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


def _submit_exception_reason(exc: Exception) -> str:
    reason = getattr(exc, "refusal_reason", None)
    if reason:
        return str(reason)
    return f"{type(exc).__name__}: broker submit failed"


def _submit_exception_payload(exc: Exception) -> dict[str, Any]:
    payload = getattr(exc, "payload", None)
    if isinstance(payload, dict):
        return dict(payload)
    status_code = getattr(exc, "status_code", None)
    result: dict[str, Any] = {"error_type": type(exc).__name__}
    if status_code is not None:
        result["status_code"] = status_code
    return result
