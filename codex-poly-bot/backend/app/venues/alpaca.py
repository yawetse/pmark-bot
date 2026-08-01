"""Alpaca venue contract helpers.

REQ: REQ-ALP-003, REQ-ALP-004, REQ-ALP-005, REQ-ALP-006,
REQ-ALP-015, REQ-ALP-016, REQ-ALP-017, REQ-ALP-018,
REQ-DAT-001, REQ-DAT-002, REQ-EXE-016, REQ-EXE-017
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from hashlib import sha256
import os
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

import httpx

from app.db import RepositoryRegistry
from app.domain import Environment, ModelProvider, OrderSide, Venue
from app.venues.polymarket import VenueCallResult


ALPACA_LIVE_TRADING_BASE_URL = "https://api.alpaca.markets"
ALPACA_PAPER_TRADING_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets/v2"


class AlpacaClientBoundary(str, Enum):
    """Allowed Alpaca client integration boundaries.

    REQ: REQ-ALP-003
    """

    OFFICIAL_PYTHON_SDK = "official_python_sdk"
    DOCUMENTED_HTTP_API = "documented_http_api"
    UNAPPROVED = "unapproved"


@dataclass(frozen=True)
class AlpacaVenueConfig:
    """Alpaca adapter configuration contract.

    REQ: REQ-ALP-003
    """

    account_mode: str
    client_boundary: AlpacaClientBoundary
    venue: Venue = Venue.ALPACA
    account_operations_enabled: bool = True
    market_data_operations_enabled: bool = True
    position_operations_enabled: bool = True
    order_operations_enabled: bool = True


@dataclass(frozen=True)
class AlpacaAccountCredential:
    """Non-secret Alpaca account credential metadata.

    REQ: REQ-ALP-004, REQ-ALP-016
    """

    environment: Environment
    account_mode: str
    model_provider: ModelProvider
    account_id: str | None
    credential_ref: str | None


@dataclass(frozen=True)
class AlpacaMarketDataStatus:
    """Market data health gate input for an Alpaca symbol.

    REQ: REQ-ALP-015
    """

    symbol: str
    available: bool = True
    rate_limited: bool = False
    stale: bool = False
    outside_trading_hours: bool = False


@dataclass(frozen=True)
class AlpacaOrderIntent:
    """Alpaca order safety input before adapter submit.

    REQ: REQ-ALP-008
    """

    symbol: str
    side: OrderSide
    quantity: Decimal | str
    current_position: Decimal | str
    estimated_notional: Decimal | str
    buying_power: Decimal | str
    margin_required: bool = False


@dataclass(frozen=True)
class AlpacaLiveAccountState:
    """Account and portfolio state required before Alpaca live eligibility.

    REQ: REQ-ALP-017
    """

    account_mode: str
    configured_account_id: str | None
    broker_account_id: str | None
    account_status: str | None
    positions: Mapping[str, Decimal | str] | None
    open_orders: Sequence[str] | None
    buying_power: Decimal | str | None


class AlpacaOrderSubmitError(RuntimeError):
    """Sanitized Alpaca submit error safe for persistence and UI display."""

    def __init__(
        self,
        refusal_reason: str,
        *,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(refusal_reason)
        self.refusal_reason = refusal_reason
        self.status_code = status_code
        self.payload = payload or {}


def _decimal(value: Decimal | str, field_name: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return decimal


def validate_alpaca_client_boundary(config: AlpacaVenueConfig) -> VenueCallResult:
    """Validate that Alpaca operations use approved SDK or HTTP boundaries.

    REQ: REQ-ALP-003
    """

    reasons: list[str] = []
    if config.venue != Venue.ALPACA:
        reasons.append("unsupported Alpaca venue")
    if config.account_mode not in {"paper", "live"}:
        reasons.append("alpaca account mode must be paper or live")
    if config.client_boundary not in {
        AlpacaClientBoundary.OFFICIAL_PYTHON_SDK,
        AlpacaClientBoundary.DOCUMENTED_HTTP_API,
    }:
        reasons.append("unapproved Alpaca client boundary")

    operations = {
        "account": config.account_operations_enabled,
        "market_data": config.market_data_operations_enabled,
        "position": config.position_operations_enabled,
        "order": config.order_operations_enabled,
    }
    for operation, enabled in operations.items():
        if not enabled:
            reasons.append(f"missing Alpaca {operation} operation binding")

    return VenueCallResult(
        ok=not reasons,
        refusal_reasons=tuple(reasons),
        payload={
            "account_mode": config.account_mode,
            "client_boundary": config.client_boundary.value,
            "operations": tuple(operations),
            "venue": config.venue.value,
        },
    )


def validate_alpaca_read_boundary(config: AlpacaVenueConfig) -> VenueCallResult:
    """Validate dry-run account and market-data reads without order binding.

    REQ: REQ-ALP-003, REQ-DAT-001, REQ-DAT-002, REQ-EXE-017
    """

    reasons: list[str] = []
    if config.venue != Venue.ALPACA:
        reasons.append("unsupported Alpaca venue")
    if config.account_mode not in {"paper", "live"}:
        reasons.append("alpaca account mode must be paper or live")
    if config.client_boundary not in {
        AlpacaClientBoundary.OFFICIAL_PYTHON_SDK,
        AlpacaClientBoundary.DOCUMENTED_HTTP_API,
    }:
        reasons.append("unapproved Alpaca client boundary")
    if not config.account_operations_enabled:
        reasons.append("missing Alpaca account operation binding")
    if not config.market_data_operations_enabled:
        reasons.append("missing Alpaca market_data operation binding")

    return VenueCallResult(
        ok=not reasons,
        refusal_reasons=tuple(reasons),
        payload={
            "account_mode": config.account_mode,
            "broker_submit_attempted": False,
            "client_boundary": config.client_boundary.value,
            "operations": ("account", "market_data"),
            "venue": config.venue.value,
        },
    )


def validate_alpaca_long_only_order(intent: AlpacaOrderIntent) -> VenueCallResult:
    """Refuse Alpaca orders that would short or require margin.

    REQ: REQ-ALP-008
    """

    quantity = _decimal(intent.quantity, "quantity")
    current_position = _decimal(intent.current_position, "current_position")
    estimated_notional = _decimal(intent.estimated_notional, "estimated_notional")
    buying_power = _decimal(intent.buying_power, "buying_power")
    symbol = intent.symbol.strip().upper()
    reasons: list[str] = []

    if not symbol:
        reasons.append("missing Alpaca symbol")
    if quantity <= 0:
        reasons.append("Alpaca order quantity must be positive")
    if current_position < 0:
        reasons.append("Alpaca current position cannot be negative")
    if estimated_notional < 0:
        reasons.append("Alpaca order notional cannot be negative")
    if buying_power < 0:
        reasons.append("Alpaca buying power cannot be negative")

    projected_position = current_position
    if intent.side == OrderSide.BUY:
        projected_position += quantity
        if intent.margin_required or estimated_notional > buying_power:
            reasons.append("Alpaca order would require margin")
    elif intent.side == OrderSide.SELL:
        projected_position -= quantity
        if projected_position < 0:
            reasons.append("Alpaca order would create short position")
    else:
        reasons.append("unsupported Alpaca order side")

    return VenueCallResult(
        ok=not reasons,
        refusal_reasons=tuple(dict.fromkeys(reasons)),
        payload={
            "symbol": symbol,
            "projected_position": str(projected_position),
            "margin_required": "Alpaca order would require margin" in reasons,
        },
    )


def validate_alpaca_account_identifiers(
    credentials: Iterable[AlpacaAccountCredential],
) -> VenueCallResult:
    """Validate Alpaca account IDs without returning secret references.

    REQ: REQ-ALP-004, REQ-ALP-016
    """

    reasons: list[str] = []
    resolved_accounts: dict[str, str] = {}
    seen_accounts: dict[tuple[str, str, str], ModelProvider] = {}

    for credential in credentials:
        key = (
            f"{credential.environment.value}:"
            f"{credential.account_mode}:"
            f"{credential.model_provider.value}"
        )
        account_id = credential.account_id.strip() if credential.account_id else ""
        credential_ref = credential.credential_ref.strip() if credential.credential_ref else ""

        if not account_id:
            reasons.append(f"missing Alpaca account identifier for {key}")
            continue
        if not credential_ref:
            reasons.append(f"missing Alpaca credential reference for {key}")

        account_key = (credential.environment.value, credential.account_mode, account_id)
        existing_provider = seen_accounts.get(account_key)
        if existing_provider is not None and existing_provider != credential.model_provider:
            reasons.append("duplicate Alpaca account identifier")
        else:
            seen_accounts[account_key] = credential.model_provider
        resolved_accounts[key] = account_id

    return VenueCallResult(
        ok=not reasons,
        refusal_reasons=tuple(dict.fromkeys(reasons)),
        payload={
            "resolved_account_count": len(resolved_accounts),
            "resolved_accounts": resolved_accounts,
        },
    )


def validate_alpaca_market_data(status: AlpacaMarketDataStatus) -> VenueCallResult:
    """Block Alpaca live orders when market data health is unsafe.

    REQ: REQ-ALP-015
    """

    reasons: list[str] = []
    symbol = status.symbol.strip().upper()
    if not symbol:
        reasons.append("missing Alpaca symbol")
    if not status.available:
        reasons.append("Alpaca market data unavailable")
    if status.rate_limited:
        reasons.append("Alpaca market data rate limited")
    if status.stale:
        reasons.append("Alpaca market data stale")
    if status.outside_trading_hours:
        reasons.append("Alpaca market outside trading hours")

    return VenueCallResult(
        ok=not reasons,
        refusal_reasons=tuple(reasons),
        payload={"symbol": symbol},
    )


def _record_alpaca_live_refusal(
    *,
    registry: RepositoryRegistry,
    environment: Environment,
    refusal_reasons: tuple[str, ...],
    entity_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Persist Alpaca live-order refusal events.

    REQ: REQ-ALP-015, REQ-EXE-016
    """

    event_metadata: dict[str, Any] = {
        "venue": Venue.ALPACA.value,
        "live_order_allowed": False,
        "refusal_reasons": list(refusal_reasons),
    }
    if metadata:
        event_metadata.update(metadata)
    return registry.shared().record_audit_event(
        event_type="alpaca_live_refusal",
        actor="system",
        action="alpaca.live_order_refused",
        environment=environment,
        entity_id=entity_id,
        metadata=event_metadata,
        success=False,
    )


def alpaca_market_data_live_gate(
    *,
    status: AlpacaMarketDataStatus,
    environment: Environment,
    registry: RepositoryRegistry,
    model_provider: ModelProvider,
) -> VenueCallResult:
    """Block affected Alpaca live orders and persist market-data refusals.

    REQ: REQ-ALP-015, REQ-EXE-016, REQ-EXE-017
    """

    result = validate_alpaca_market_data(status)
    symbol = result.payload["symbol"]
    if result.ok:
        return VenueCallResult(
            ok=True,
            payload={
                "live_order_allowed": True,
                "model_provider": model_provider.value,
                "symbol": symbol,
                "venue": Venue.ALPACA.value,
            },
        )
    audit_event = _record_alpaca_live_refusal(
        registry=registry,
        environment=environment,
        refusal_reasons=result.refusal_reasons,
        entity_id=symbol,
        metadata={
            "available": status.available,
            "model_provider": model_provider.value,
            "outside_trading_hours": status.outside_trading_hours,
            "rate_limited": status.rate_limited,
            "stale": status.stale,
            "symbol": symbol,
        },
    )
    return VenueCallResult(
        ok=False,
        refusal_reasons=result.refusal_reasons,
        payload={
            "audit_event_id": audit_event["id"],
            "live_order_allowed": False,
            "model_provider": model_provider.value,
            "symbol": symbol,
            "venue": Venue.ALPACA.value,
        },
    )


def validate_alpaca_live_account_state(
    *,
    config: AlpacaVenueConfig,
    state: AlpacaLiveAccountState,
) -> VenueCallResult:
    """Validate account state before Alpaca live order eligibility.

    REQ: REQ-ALP-017, REQ-ALP-018
    """

    boundary = validate_alpaca_read_boundary(config)
    reasons = list(boundary.refusal_reasons)
    configured_account_id = (state.configured_account_id or "").strip()
    broker_account_id = (state.broker_account_id or "").strip()
    account_mode = state.account_mode.strip().lower()
    account_status = (state.account_status or "").strip().lower()
    positions = state.positions
    open_orders = state.open_orders
    buying_power: Decimal | None = None

    if account_mode != config.account_mode:
        reasons.append("Alpaca account mode mismatch")
    if not configured_account_id:
        reasons.append("missing configured Alpaca account identifier")
    if not broker_account_id:
        reasons.append("missing broker Alpaca account identifier")
    elif configured_account_id and configured_account_id != broker_account_id:
        reasons.append("Alpaca account identifier mismatch")
    if not account_status:
        reasons.append("missing Alpaca account status")
    elif account_status != "active":
        reasons.append("Alpaca account not active")
    if positions is None:
        reasons.append("Alpaca positions unavailable")
    if open_orders is None:
        reasons.append("Alpaca open orders unavailable")
    if state.buying_power is None:
        reasons.append("Alpaca buying power unavailable")
    else:
        try:
            buying_power = _decimal(state.buying_power, "buying_power")
            if buying_power < 0:
                reasons.append("Alpaca buying power cannot be negative")
        except ValueError:
            reasons.append("Alpaca buying power unavailable")

    return VenueCallResult(
        ok=not reasons,
        refusal_reasons=tuple(dict.fromkeys(reasons)),
        payload={
            "account_mode": account_mode,
            "account_status": account_status,
            "broker_account_id": broker_account_id,
            "buying_power": str(buying_power) if buying_power is not None else None,
            "configured_account_id": configured_account_id,
            "live_order_allowed": not reasons,
            "open_orders_count": len(open_orders or ()),
            "positions_count": len(positions or {}),
            "venue": config.venue.value,
        },
    )


class AlpacaContractClient:
    """Small testable adapter boundary for Alpaca operation checks.

    REQ: REQ-ALP-003
    """

    def __init__(self, config: AlpacaVenueConfig):
        self.config = config
        self.operation_calls = 0
        self.read_calls = 0
        self.submit_attempts = 0

    def read_account_and_market_data(self, *, symbols: Sequence[str]) -> VenueCallResult:
        """Validate dry-run Alpaca reads without order endpoint calls.

        REQ: REQ-ALP-003, REQ-ALP-005, REQ-DAT-001, REQ-DAT-002,
        REQ-EXE-017
        """

        result = validate_alpaca_read_boundary(self.config)
        normalized_symbols = tuple(symbol.strip().upper() for symbol in symbols if symbol.strip())
        if not result.ok:
            return result
        if not normalized_symbols:
            return VenueCallResult(
                ok=False,
                refusal_reasons=("missing Alpaca symbols",),
                payload={
                    "broker_submit_attempted": False,
                    "symbols": normalized_symbols,
                },
            )
        self.read_calls += len(result.payload["operations"])
        return VenueCallResult(
            ok=True,
            payload={
                **result.payload,
                "operation": "read_account_and_market_data",
                "symbols": normalized_symbols,
            },
        )

    def execute_contract_operations(self) -> VenueCallResult:
        """Validate the client boundary and count approved operation calls.

        REQ: REQ-ALP-003
        """

        result = validate_alpaca_client_boundary(self.config)
        if result.ok:
            self.operation_calls = len(result.payload["operations"])
        return result


class AlpacaLiveOrderAdapter:
    """Submit approved Alpaca live or paper orders through the Trading API."""

    def __init__(
        self,
        *,
        account_mode: str,
        environ: dict[str, str] | None = None,
        trading_base_url: str | None = None,
        data_base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.account_mode = _account_mode(account_mode)
        self.environ = environ if environ is not None else os.environ
        self.trading_base_url = _base_url(
            trading_base_url
            or self.environ.get("ALPACA_TRADING_BASE_URL")
            or (
                self.environ.get("ALPACA_PAPER_TRADING_BASE_URL")
                if self.account_mode == "paper"
                else self.environ.get("ALPACA_LIVE_TRADING_BASE_URL")
            ),
            ALPACA_PAPER_TRADING_BASE_URL
            if self.account_mode == "paper"
            else ALPACA_LIVE_TRADING_BASE_URL,
        )
        self.data_base_url = _base_url(
            data_base_url or self.environ.get("ALPACA_DATA_BASE_URL"),
            ALPACA_DATA_BASE_URL,
        )
        self.transport = transport
        self.timeout_seconds = max(0.5, float(timeout_seconds))

    def submit_order(
        self,
        *,
        account_mode: str,
        symbol: str,
        notional: Decimal | None = None,
        quantity: Decimal | None = None,
        side: str = "buy",
        client_order_id: str | None = None,
        position_intent: str | None = None,
        estimated_unit_price: Decimal | None = None,
        expected_account_id: str | None = None,
        entry_cutoff_minutes: int | None = None,
        max_quote_age_seconds: int | None = None,
    ) -> str:
        """Submit a market order and return the broker order id.

        REQ: REQ-ALP-006, REQ-ALP-018
        """

        requested_mode = _account_mode(account_mode)
        if requested_mode != self.account_mode:
            raise AlpacaOrderSubmitError(
                "Alpaca account mode mismatch",
                payload={
                    "configured_account_mode": self.account_mode,
                    "requested_account_mode": requested_mode,
                },
            )
        headers = self._headers()
        if headers is None:
            raise AlpacaOrderSubmitError(
                "Alpaca credentials missing",
                payload={"error_code": "alpaca_credentials_missing"},
            )
        payload = _alpaca_market_order_payload(
            symbol=symbol,
            side=side,
            notional=notional,
            quantity=quantity,
            client_order_id=client_order_id,
            extended_hours=_bool_env(self.environ.get("ALPACA_EXTENDED_HOURS")),
            position_intent=position_intent,
        )
        try:
            with self._client() as client:
                if payload["position_intent"] == "sell_to_open":
                    self._validate_short_entry(
                        client=client,
                        headers=headers,
                        symbol=str(payload["symbol"]),
                        quantity=_decimal(payload["qty"], "quantity"),
                        estimated_unit_price=estimated_unit_price,
                        expected_account_id=expected_account_id,
                        entry_cutoff_minutes=entry_cutoff_minutes,
                        max_quote_age_seconds=max_quote_age_seconds,
                    )
                elif payload["position_intent"] in {"buy_to_close", "sell_to_close"} and expected_account_id:
                    self._validate_exit_state(
                        client=client,
                        headers=headers,
                        expected_account_id=expected_account_id,
                        symbol=str(payload["symbol"]),
                        quantity=_decimal(payload["qty"], "quantity"),
                        position_intent=str(payload["position_intent"]),
                    )
                response = client.post(
                    f"{self.trading_base_url}/v2/orders",
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise AlpacaOrderSubmitError(
                f"Alpaca order submit failed: {type(exc).__name__}",
                payload={"error_code": "alpaca_http_error"},
            ) from exc
        if response.status_code == 429:
            raise AlpacaOrderSubmitError(
                "Alpaca order submit rate limited",
                status_code=response.status_code,
                payload={"error_code": "alpaca_rate_limited"},
            )
        if response.status_code >= 400:
            raise AlpacaOrderSubmitError(
                f"Alpaca order submit returned HTTP {response.status_code}",
                status_code=response.status_code,
                payload=_safe_alpaca_error_payload(response),
            )
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise AlpacaOrderSubmitError(
                "Alpaca order submit returned invalid JSON",
                payload={"error_code": "alpaca_invalid_json"},
            ) from exc
        order_id = _first_text(
            response_payload.get("id") if isinstance(response_payload, dict) else None,
            response_payload.get("client_order_id") if isinstance(response_payload, dict) else None,
        )
        if order_id is None:
            raise AlpacaOrderSubmitError(
                "Alpaca order submit did not return an order id",
                payload={"error_code": "alpaca_missing_order_id"},
            )
        return order_id

    def _validate_short_entry(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str],
        symbol: str,
        quantity: Decimal,
        estimated_unit_price: Decimal | None,
        expected_account_id: str | None,
        entry_cutoff_minutes: int | None,
        max_quote_age_seconds: int | None,
    ) -> None:
        """Fail closed on current account and easy-to-borrow asset state."""

        if estimated_unit_price is None:
            raise AlpacaOrderSubmitError("Alpaca short entry requires estimated unit price")
        unit_price = _decimal(estimated_unit_price, "estimated_unit_price")
        if unit_price <= 0:
            raise AlpacaOrderSubmitError("Alpaca short entry requires estimated unit price")
        if not expected_account_id:
            raise AlpacaOrderSubmitError(
                "Alpaca short entry account route unresolved",
                payload={"error_code": "alpaca_short_account_unresolved"},
            )
        account = _alpaca_get_json(
            client,
            f"{self.trading_base_url}/v2/account",
            headers=headers,
            label="account",
        )
        if _alpaca_account_id(account) != expected_account_id:
            raise AlpacaOrderSubmitError(
                "Alpaca short entry account mismatch",
                payload={"error_code": "alpaca_short_account_mismatch"},
            )
        clock = _alpaca_get_json(
            client,
            f"{self.trading_base_url}/v2/clock",
            headers=headers,
            label="clock",
        )
        clock_time = _validate_alpaca_market_clock(
            clock,
            cutoff_minutes=max(
                0,
                int(15 if entry_cutoff_minutes is None else entry_cutoff_minutes),
            ),
            error_prefix="Alpaca short entry",
            max_age_seconds=max(1, int(max_quote_age_seconds or 300)),
        )
        quote_payload = _alpaca_get_json(
            client,
            f"{self.data_base_url}/stocks/{quote(symbol, safe='')}/quotes/latest",
            headers=headers,
            label="latest quote",
        )
        quote_payload = quote_payload.get("quote")
        if not isinstance(quote_payload, Mapping):
            raise AlpacaOrderSubmitError(
                "Alpaca short latest ask unavailable",
                payload={"error_code": "alpaca_short_latest_ask_unavailable"},
            )
        try:
            current_ask = _decimal(str(quote_payload.get("ap")), "latest ask")
        except ValueError as exc:
            raise AlpacaOrderSubmitError(
                "Alpaca short latest ask unavailable",
                payload={"error_code": "alpaca_short_latest_ask_unavailable"},
            ) from exc
        if current_ask <= 0:
            raise AlpacaOrderSubmitError(
                "Alpaca short latest ask unavailable",
                payload={"error_code": "alpaca_short_latest_ask_unavailable"},
            )
        quote_time = _parse_alpaca_timestamp(quote_payload.get("t"))
        if quote_time is None:
            raise AlpacaOrderSubmitError(
                "Alpaca short latest quote timestamp unavailable",
                payload={"error_code": "alpaca_short_quote_timestamp_unavailable"},
            )
        quote_age_seconds = abs(int((clock_time - quote_time).total_seconds()))
        if quote_age_seconds > max(1, int(max_quote_age_seconds or 300)):
            raise AlpacaOrderSubmitError(
                "Alpaca short latest quote is stale",
                payload={"error_code": "alpaca_short_quote_stale"},
            )
        account_reason = _alpaca_short_account_refusal(
            account,
            required_buying_power=quantity * current_ask * Decimal("1.03"),
        )
        if account_reason:
            raise AlpacaOrderSubmitError(
                f"Alpaca short entry refused: {account_reason}",
                payload={"error_code": "alpaca_short_account_ineligible"},
            )
        asset = _alpaca_get_json(
            client,
            f"{self.trading_base_url}/v2/assets/{quote(symbol, safe='')}",
            headers=headers,
            label="asset",
        )
        if not _alpaca_short_asset_eligible(asset, expected_symbol=symbol):
            raise AlpacaOrderSubmitError(
                "Alpaca short entry refused: asset not eligible for short sale",
                payload={"error_code": "alpaca_short_asset_ineligible"},
            )
        if _alpaca_current_position(
            client,
            trading_base_url=self.trading_base_url,
            headers=headers,
            symbol=symbol,
        ) is not None:
            raise AlpacaOrderSubmitError(
                "Alpaca short entry refused: position already exists",
                payload={"error_code": "alpaca_short_position_exists"},
            )
        if _alpaca_open_orders(
            client,
            trading_base_url=self.trading_base_url,
            headers=headers,
            symbol=symbol,
        ):
            raise AlpacaOrderSubmitError(
                "Alpaca short entry refused: open order already exists",
                payload={"error_code": "alpaca_short_open_order_exists"},
            )

    def _validate_exit_state(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str],
        expected_account_id: str,
        symbol: str,
        quantity: Decimal,
        position_intent: str,
    ) -> None:
        account = _alpaca_get_json(
            client,
            f"{self.trading_base_url}/v2/account",
            headers=headers,
            label="exit account",
        )
        if _alpaca_account_id(account) != expected_account_id:
            raise AlpacaOrderSubmitError(
                "Alpaca exit account mismatch",
                payload={"error_code": "alpaca_exit_account_mismatch"},
            )
        clock = _alpaca_get_json(
            client,
            f"{self.trading_base_url}/v2/clock",
            headers=headers,
            label="exit clock",
        )
        _validate_alpaca_market_clock(
            clock,
            cutoff_minutes=0,
            error_prefix="Alpaca exit",
        )
        position = _alpaca_current_position(
            client,
            trading_base_url=self.trading_base_url,
            headers=headers,
            symbol=symbol,
        )
        if position is None:
            raise AlpacaOrderSubmitError(
                "Alpaca exit position unavailable",
                payload={"error_code": "alpaca_exit_position_unavailable"},
            )
        expected_side = "short" if position_intent == "buy_to_close" else "long"
        actual_side = str(position.get("side") or "").strip().lower()
        try:
            current_quantity = abs(_decimal(str(position.get("qty")), "position quantity"))
        except ValueError as exc:
            raise AlpacaOrderSubmitError(
                "Alpaca exit position quantity unavailable",
                payload={"error_code": "alpaca_exit_quantity_unavailable"},
            ) from exc
        if actual_side != expected_side:
            raise AlpacaOrderSubmitError(
                "Alpaca exit position direction mismatch",
                payload={"error_code": "alpaca_exit_direction_mismatch"},
            )
        if current_quantity != quantity:
            raise AlpacaOrderSubmitError(
                "Alpaca exit position quantity mismatch",
                payload={"error_code": "alpaca_exit_quantity_mismatch"},
            )
        if _alpaca_open_orders(
            client,
            trading_base_url=self.trading_base_url,
            headers=headers,
            symbol=symbol,
        ):
            raise AlpacaOrderSubmitError(
                "Alpaca exit open order already exists",
                payload={"error_code": "alpaca_exit_open_order_exists"},
            )

    def _headers(self) -> dict[str, str] | None:
        key_id = self.environ.get("ALPACA_KEY_ID", "").strip()
        secret_key = self.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not key_id or not secret_key:
            return None
        return {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout_seconds, transport=self.transport)


def alpaca_live_order_adapter_from_env(
    environ: dict[str, str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> AlpacaLiveOrderAdapter:
    """Build an Alpaca order adapter from deployed runtime variables."""

    source = environ if environ is not None else os.environ
    return AlpacaLiveOrderAdapter(
        account_mode=source.get("TRADING_ACCOUNT_MODE", "paper"),
        environ=source,
        transport=transport,
    )


def _alpaca_market_order_payload(
    *,
    symbol: str,
    side: str,
    notional: Decimal | None,
    quantity: Decimal | None,
    client_order_id: str | None,
    extended_hours: bool,
    position_intent: str | None = None,
) -> dict[str, Any]:
    normalized_symbol = symbol.strip().upper()
    normalized_side = side.strip().lower()
    if not normalized_symbol:
        raise AlpacaOrderSubmitError("missing Alpaca symbol")
    if normalized_side not in {"buy", "sell"}:
        raise AlpacaOrderSubmitError("unsupported Alpaca order side")
    normalized_intent = _alpaca_position_intent(position_intent, normalized_side)
    payload: dict[str, Any] = {
        "symbol": normalized_symbol,
        "side": normalized_side,
        "position_intent": normalized_intent,
        "type": "market",
        "time_in_force": "day",
    }
    if extended_hours:
        payload["extended_hours"] = True
    if client_order_id:
        payload["client_order_id"] = _alpaca_client_order_id(client_order_id)
    if normalized_intent in {"sell_to_open", "buy_to_close"} and notional is not None:
        raise AlpacaOrderSubmitError("Alpaca short orders require quantity, not notional")
    if quantity is not None:
        parsed_quantity = _decimal(quantity, "quantity")
        if normalized_intent == "sell_to_open" and (
            parsed_quantity <= 0 or parsed_quantity != parsed_quantity.to_integral_value()
        ):
            raise AlpacaOrderSubmitError(
                "Alpaca short entry requires positive whole-share quantity"
            )
        if parsed_quantity <= 0:
            raise AlpacaOrderSubmitError("Alpaca order quantity must be positive")
        payload["qty"] = _decimal_text(parsed_quantity)
        return payload
    if notional is None:
        raise AlpacaOrderSubmitError("Alpaca order requires notional or quantity")
    if normalized_intent in {"sell_to_open", "buy_to_close"}:
        raise AlpacaOrderSubmitError("Alpaca short orders require quantity, not notional")
    parsed_notional = _decimal(notional, "notional")
    if parsed_notional <= 0:
        raise AlpacaOrderSubmitError("Alpaca order notional must be positive")
    payload["notional"] = _decimal_text(parsed_notional)
    return payload


def _alpaca_position_intent(position_intent: str | None, side: str) -> str:
    normalized = (position_intent or "").strip().lower()
    if not normalized:
        return "buy_to_open" if side == "buy" else "sell_to_close"
    allowed = {
        "buy": {"buy_to_open", "buy_to_close"},
        "sell": {"sell_to_open", "sell_to_close"},
    }
    if normalized not in allowed[side]:
        raise AlpacaOrderSubmitError("Alpaca position intent does not match order side")
    return normalized


def _alpaca_get_json(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    label: str,
) -> dict[str, Any]:
    label_code = label.strip().lower().replace(" ", "_")
    try:
        response = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise AlpacaOrderSubmitError(
            f"Alpaca short {label} eligibility unavailable",
            payload={"error_code": f"alpaca_short_{label_code}_http_error"},
        ) from exc
    if response.status_code >= 400:
        raise AlpacaOrderSubmitError(
            f"Alpaca short {label} eligibility returned HTTP {response.status_code}",
            status_code=response.status_code,
            payload={"error_code": f"alpaca_short_{label_code}_http_{response.status_code}"},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AlpacaOrderSubmitError(
            f"Alpaca short {label} eligibility returned invalid JSON",
            payload={"error_code": f"alpaca_short_{label_code}_invalid_json"},
        ) from exc
    if not isinstance(payload, dict):
        raise AlpacaOrderSubmitError(
            f"Alpaca short {label} eligibility returned invalid payload",
            payload={"error_code": f"alpaca_short_{label_code}_invalid_payload"},
        )
    return payload


def _alpaca_account_id(account: Mapping[str, Any]) -> str | None:
    return _first_text(
        account.get("id"),
        account.get("account_id"),
        account.get("account_number"),
    )


def _parse_alpaca_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _validate_alpaca_market_clock(
    clock: Mapping[str, Any],
    *,
    cutoff_minutes: int,
    error_prefix: str,
    max_age_seconds: int = 300,
) -> datetime:
    if clock.get("is_open") is not True:
        raise AlpacaOrderSubmitError(
            f"{error_prefix} refused: market is closed",
            payload={"error_code": "alpaca_market_closed"},
        )
    clock_time = _parse_alpaca_timestamp(clock.get("timestamp"))
    if clock_time is None:
        raise AlpacaOrderSubmitError(
            f"{error_prefix} market clock timestamp unavailable",
            payload={"error_code": "alpaca_clock_timestamp_unavailable"},
        )
    if abs((datetime.now(UTC) - clock_time).total_seconds()) > max(1, max_age_seconds):
        raise AlpacaOrderSubmitError(
            f"{error_prefix} market clock is stale",
            payload={"error_code": "alpaca_clock_stale"},
        )
    if cutoff_minutes > 0:
        next_close = _parse_alpaca_timestamp(clock.get("next_close"))
        if next_close is None:
            raise AlpacaOrderSubmitError(
                f"{error_prefix} next market close unavailable",
                payload={"error_code": "alpaca_next_close_unavailable"},
            )
        if clock_time >= next_close - timedelta(minutes=cutoff_minutes):
            raise AlpacaOrderSubmitError(
                f"{error_prefix} refused: close-before-market cutoff reached",
                payload={"error_code": "alpaca_entry_market_close_cutoff"},
            )
    return clock_time


def _alpaca_current_position(
    client: httpx.Client,
    *,
    trading_base_url: str,
    headers: dict[str, str],
    symbol: str,
) -> dict[str, Any] | None:
    try:
        response = client.get(
            f"{trading_base_url}/v2/positions/{quote(symbol, safe='')}",
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise AlpacaOrderSubmitError(
            "Alpaca current position unavailable",
            payload={"error_code": "alpaca_position_http_error"},
        ) from exc
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise AlpacaOrderSubmitError(
            f"Alpaca current position returned HTTP {response.status_code}",
            status_code=response.status_code,
            payload={"error_code": f"alpaca_position_http_{response.status_code}"},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AlpacaOrderSubmitError(
            "Alpaca current position returned invalid JSON",
            payload={"error_code": "alpaca_position_invalid_json"},
        ) from exc
    if not isinstance(payload, dict):
        raise AlpacaOrderSubmitError(
            "Alpaca current position returned invalid payload",
            payload={"error_code": "alpaca_position_invalid_payload"},
        )
    return payload


def _alpaca_open_orders(
    client: httpx.Client,
    *,
    trading_base_url: str,
    headers: dict[str, str],
    symbol: str,
) -> list[dict[str, Any]]:
    try:
        response = client.get(
            f"{trading_base_url}/v2/orders",
            headers=headers,
            params={"status": "open", "symbols": symbol, "limit": "500"},
        )
    except httpx.HTTPError as exc:
        raise AlpacaOrderSubmitError(
            "Alpaca open orders unavailable",
            payload={"error_code": "alpaca_open_orders_http_error"},
        ) from exc
    if response.status_code >= 400:
        raise AlpacaOrderSubmitError(
            f"Alpaca open orders returned HTTP {response.status_code}",
            status_code=response.status_code,
            payload={"error_code": f"alpaca_open_orders_http_{response.status_code}"},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AlpacaOrderSubmitError(
            "Alpaca open orders returned invalid JSON",
            payload={"error_code": "alpaca_open_orders_invalid_json"},
        ) from exc
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise AlpacaOrderSubmitError(
            "Alpaca open orders returned invalid payload",
            payload={"error_code": "alpaca_open_orders_invalid_payload"},
        )
    return [
        item
        for item in payload
        if str(item.get("symbol") or symbol).strip().upper() == symbol.upper()
    ]


def _alpaca_short_account_refusal(
    account: Mapping[str, Any],
    *,
    required_buying_power: Decimal,
) -> str | None:
    if str(account.get("status") or "").strip().lower() != "active":
        return "account not active"
    if account.get("account_blocked") is not False:
        return "account blocked"
    if account.get("trading_blocked") is not False:
        return "trading blocked"
    if account.get("trade_suspended_by_user") is not False:
        return "trading suspended by user"
    if account.get("shorting_enabled") is not True:
        return "shorting not enabled"
    try:
        equity = _decimal(str(account.get("equity")), "equity")
    except ValueError:
        return "account equity unavailable"
    if equity < Decimal("2000"):
        return "equity below 2000"
    try:
        buying_power = _decimal(str(account.get("buying_power")), "buying_power")
    except ValueError:
        return "buying power unavailable"
    if buying_power < required_buying_power:
        return "insufficient short buying power"
    return None


def _alpaca_short_asset_eligible(
    asset: Mapping[str, Any],
    *,
    expected_symbol: str,
) -> bool:
    return (
        str(asset.get("symbol") or "").strip().upper() == expected_symbol
        and str(asset.get("class") or "").strip().lower() == "us_equity"
        and str(asset.get("status") or "").strip().lower() == "active"
        and asset.get("tradable") is True
        and asset.get("shortable") is True
        and str(asset.get("borrow_status") or "").strip().lower() == "easy_to_borrow"
    )


def _safe_alpaca_error_payload(response: httpx.Response) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error_code": f"alpaca_http_{response.status_code}",
        "status_code": response.status_code,
    }
    try:
        body = response.json()
    except ValueError:
        return payload
    if isinstance(body, dict):
        for key in ("code", "message", "error"):
            value = body.get(key)
            if value is not None:
                payload[key] = str(value)
    return payload


def _alpaca_client_order_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    return f"codex-{sha256(normalized.encode('utf-8')).hexdigest()[:24]}"


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _bool_env(value: str | None) -> bool:
    return str(value or "").strip().lower() == "true"


def _base_url(value: str | None, default: str) -> str:
    text = (value or default).strip().rstrip("/")
    return text or default


def _account_mode(value: str) -> str:
    text = value.strip().lower()
    if text not in {"paper", "live"}:
        raise ValueError("account_mode must be paper or live")
    return text
