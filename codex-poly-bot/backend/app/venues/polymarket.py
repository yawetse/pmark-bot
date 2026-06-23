"""Polymarket venue contract helpers.

REQ: REQ-VEN-001, REQ-VEN-003, REQ-VEN-004, REQ-VEN-005,
REQ-DAT-001, REQ-DAT-002, REQ-DAT-005, REQ-EXE-010,
REQ-EXE-011, REQ-EXE-015, REQ-EXE-016, REQ-EXE-017
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
import os
from typing import Any, Callable, Protocol

from app.bootstrap import configured_slippage_threshold
from app.db import RepositoryRegistry
from app.domain import Environment, OrderType, Venue, supported_polymarket_venues


POLYMARKET_US_API_BASE_URL = "https://api.polymarket.us"
POLYMARKET_US_GATEWAY_BASE_URL = "https://gateway.polymarket.us"

POLYMARKET_ORDER_INTENTS = frozenset(
    {
        "ORDER_INTENT_BUY_LONG",
        "ORDER_INTENT_SELL_LONG",
        "ORDER_INTENT_BUY_SHORT",
        "ORDER_INTENT_SELL_SHORT",
    }
)
POLYMARKET_ORDER_TYPES = {
    OrderType.LIMIT.value: "ORDER_TYPE_LIMIT",
    OrderType.MARKET.value: "ORDER_TYPE_MARKET",
    "ORDER_TYPE_LIMIT": "ORDER_TYPE_LIMIT",
    "ORDER_TYPE_MARKET": "ORDER_TYPE_MARKET",
}
POLYMARKET_TIME_IN_FORCE = frozenset(
    {
        "TIME_IN_FORCE_GOOD_TILL_CANCEL",
        "TIME_IN_FORCE_GOOD_TILL_DATE",
        "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "TIME_IN_FORCE_FILL_OR_KILL",
    }
)
POLYMARKET_MANUAL_ORDER_INDICATORS = frozenset(
    {
        "MANUAL_ORDER_INDICATOR_MANUAL",
        "MANUAL_ORDER_INDICATOR_AUTOMATIC",
    }
)


class VenueOperation(str, Enum):
    """Venue operations relevant to enabled/disabled gating.

    REQ: REQ-VEN-003, REQ-EXE-015
    """

    SCAN = "scan"
    SCORE = "score"
    SUBMIT_ORDER = "submit_order"
    CANCEL_ORDER = "cancel_order"
    GET_ORDER = "get_order"
    RECONCILE = "reconcile"


class PolymarketClientBoundary(str, Enum):
    """Allowed Polymarket client integration boundaries.

    REQ: REQ-VEN-004
    """

    OFFICIAL_SDK = "official_sdk"
    DOCUMENTED_HTTP_API = "documented_http_api"
    UNAPPROVED = "unapproved"


@dataclass(frozen=True)
class VenueCallResult:
    """Expected venue call success/failure envelope.

    REQ: REQ-VEN-004, REQ-VEN-005, REQ-EXE-010, REQ-EXE-011
    """

    ok: bool
    refusal_reasons: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def refusal_reason(self) -> str | None:
        return "; ".join(self.refusal_reasons) if self.refusal_reasons else None


@dataclass(frozen=True)
class PolymarketVenueConfig:
    """Polymarket adapter configuration contract.

    REQ: REQ-VEN-001, REQ-VEN-003, REQ-VEN-004, REQ-VEN-005
    """

    venue: Venue
    enabled: bool
    live_enabled: bool
    client_boundary: PolymarketClientBoundary
    base_url: str
    credential_ref: str | None = None
    gateway_base_url: str = POLYMARKET_US_GATEWAY_BASE_URL
    jurisdiction_supported: bool = True
    stale_threshold_seconds: int = 60
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class PolymarketApiCredentials:
    """Polymarket US API credentials for SDK authentication.

    REQ: REQ-WAL-005, REQ-WAL-006, REQ-VEN-004
    """

    key_id: str
    secret_key: str

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> PolymarketApiCredentials:
        """Load API credentials without exposing private material.

        REQ: REQ-WAL-005, REQ-WAL-006
        """

        source = environ if environ is not None else os.environ
        return cls(
            key_id=source.get("POLYMARKET_KEY_ID", "").strip(),
            secret_key=(
                source.get("POLYMARKET_SECRET_KEY", "").strip()
                or source.get("POLYMARKET_PRIVATE_KEY", "").strip()
            ),
        )


@dataclass(frozen=True)
class PolymarketLiveOrderRequest:
    """Venue-native Polymarket US live order request.

    REQ: REQ-VEN-004, REQ-EXE-010, REQ-EXE-011
    """

    market_slug: str
    intent: str
    order_type: OrderType | str
    tif: str = "TIME_IN_FORCE_GOOD_TILL_CANCEL"
    price: Decimal | str | None = None
    quantity: Decimal | str | int | float | None = None
    cash_order_qty: Decimal | str | None = None
    participate_dont_initiate: bool = False
    good_till_time: str | None = None
    manual_order_indicator: str = "MANUAL_ORDER_INDICATOR_AUTOMATIC"
    synchronous_execution: bool = True
    max_block_time: str | None = None
    current_price: Decimal | str | None = None
    slippage_tolerance_bips: int | None = None
    slippage_tolerance_ticks: int | None = None


class PolymarketUsOrdersClient(Protocol):
    """Subset of the official SDK orders resource used by the adapter."""

    def create(self, params: dict[str, Any]) -> Any:
        ...

    def preview(self, params: dict[str, Any]) -> Any:
        ...


class PolymarketUsMarketsClient(Protocol):
    """Subset of the official SDK markets resource used by the adapter."""

    def list(self, params: dict[str, Any] | None = None) -> Any:
        ...


class PolymarketUsAccountClient(Protocol):
    """Subset of the official SDK account resource used by the adapter."""

    def balances(self) -> Any:
        ...


class PolymarketUsSdkClient(Protocol):
    """Subset of the official SDK client used by this service boundary."""

    orders: PolymarketUsOrdersClient
    markets: PolymarketUsMarketsClient
    account: PolymarketUsAccountClient

    def close(self) -> None:
        ...


def validate_polymarket_config(config: PolymarketVenueConfig) -> VenueCallResult:
    """Return unsupported Polymarket config reasons without making venue calls.

    REQ: REQ-VEN-005
    """

    reasons: list[str] = []
    if config.venue not in supported_polymarket_venues():
        reasons.append("unsupported Polymarket venue")
    if not config.base_url.strip():
        reasons.append("missing Polymarket base URL")
    if config.live_enabled and not config.credential_ref:
        reasons.append("missing Polymarket credential reference")
    if not config.jurisdiction_supported:
        reasons.append("unsupported jurisdiction")
    if config.stale_threshold_seconds <= 0:
        reasons.append("invalid stale data threshold")
    if config.client_boundary not in {
        PolymarketClientBoundary.OFFICIAL_SDK,
        PolymarketClientBoundary.DOCUMENTED_HTTP_API,
    }:
        reasons.append("unapproved Polymarket client boundary")
    return VenueCallResult(
        ok=not reasons,
        refusal_reasons=tuple(reasons),
        payload={"venue": config.venue.value},
    )


def live_submit_contract(config: PolymarketVenueConfig) -> VenueCallResult:
    """Validate live Polymarket submit uses approved client boundary.

    REQ: REQ-VEN-004, REQ-VEN-005
    """

    config_result = validate_polymarket_config(config)
    if not config_result.ok:
        return config_result
    return VenueCallResult(
        ok=True,
        payload={
            "client_boundary": config.client_boundary.value,
            "venue": config.venue.value,
        },
    )


def dry_run_read_contract(
    config: PolymarketVenueConfig,
    *,
    snapshot_type: str,
) -> VenueCallResult:
    """Validate a Polymarket read path without enabling order submission.

    REQ: REQ-VEN-004, REQ-DAT-001, REQ-DAT-002, REQ-EXE-017
    """

    config_result = validate_polymarket_config(config)
    if not config_result.ok:
        return config_result
    if config.live_enabled:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("Polymarket read contract requires dry-run mode",),
            payload={
                "venue": config.venue.value,
                "live_submit_attempted": False,
            },
        )
    if not config.enabled:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("Polymarket venue disabled",),
            payload={
                "venue": config.venue.value,
                "live_submit_attempted": False,
            },
        )
    return VenueCallResult(
        ok=True,
        payload={
            "client_boundary": config.client_boundary.value,
            "live_submit_attempted": False,
            "operation": "read_markets",
            "snapshot_type": snapshot_type,
            "venue": config.venue.value,
        },
    )


def _record_polymarket_live_refusal(
    *,
    registry: RepositoryRegistry,
    environment: Environment,
    config: PolymarketVenueConfig,
    refusal_reasons: tuple[str, ...],
    entity_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Persist Polymarket live-order refusal events for auditability.

    REQ: REQ-VEN-005, REQ-DAT-005, REQ-EXE-016
    """

    event_metadata: dict[str, Any] = {
        "venue": config.venue.value,
        "live_order_allowed": False,
        "refusal_reasons": list(refusal_reasons),
    }
    if metadata:
        event_metadata.update(metadata)
    return registry.shared().record_audit_event(
        event_type="polymarket_live_refusal",
        actor="system",
        action="polymarket.live_order_refused",
        environment=environment,
        entity_id=entity_id or config.venue.value,
        metadata=event_metadata,
        success=False,
    )


def polymarket_live_eligibility_gate(
    *,
    config: PolymarketVenueConfig,
    environment: Environment,
    registry: RepositoryRegistry,
) -> VenueCallResult:
    """Block live Polymarket eligibility for unsupported configuration.

    REQ: REQ-VEN-005, REQ-EXE-016, REQ-EXE-017
    """

    result = validate_polymarket_config(config)
    if result.ok:
        return VenueCallResult(
            ok=True,
            payload={
                "live_order_allowed": True,
                "venue": config.venue.value,
            },
        )
    audit_event = _record_polymarket_live_refusal(
        registry=registry,
        environment=environment,
        config=config,
        refusal_reasons=result.refusal_reasons,
    )
    return VenueCallResult(
        ok=False,
        refusal_reasons=result.refusal_reasons,
        payload={
            "audit_event_id": audit_event["id"],
            "live_order_allowed": False,
            "venue": config.venue.value,
        },
    )


def polymarket_market_data_live_gate(
    *,
    config: PolymarketVenueConfig,
    environment: Environment,
    registry: RepositoryRegistry,
    market_id: str,
    observed_at: datetime | None,
    now: datetime,
) -> VenueCallResult:
    """Block live Polymarket orders that depend on stale market data.

    REQ: REQ-DAT-005, REQ-EXE-016, REQ-EXE-017
    """

    from app.services.ingestion_service import check_market_data_freshness

    config_result = validate_polymarket_config(config)
    if not config_result.ok:
        return polymarket_live_eligibility_gate(
            config=config,
            environment=environment,
            registry=registry,
        )

    freshness = check_market_data_freshness(
        observed_at=observed_at,
        now=now,
        threshold=timedelta(seconds=config.stale_threshold_seconds),
    )
    if freshness.ok:
        return VenueCallResult(
            ok=True,
            payload={
                "age_seconds": freshness.age_seconds,
                "live_order_allowed": True,
                "market_id": market_id,
                "threshold_seconds": freshness.threshold_seconds,
                "venue": config.venue.value,
            },
        )

    refusal_reasons = (freshness.refusal_reason or "STALE_MARKET_DATA",)
    audit_event = _record_polymarket_live_refusal(
        registry=registry,
        environment=environment,
        config=config,
        refusal_reasons=refusal_reasons,
        entity_id=market_id,
        metadata={
            "age_seconds": freshness.age_seconds,
            "market_id": market_id,
            "threshold_seconds": freshness.threshold_seconds,
        },
    )
    return VenueCallResult(
        ok=False,
        refusal_reasons=refusal_reasons,
        payload={
            "age_seconds": freshness.age_seconds,
            "audit_event_id": audit_event["id"],
            "live_order_allowed": False,
            "market_id": market_id,
            "threshold_seconds": freshness.threshold_seconds,
            "venue": config.venue.value,
        },
    )


def allowed_when_venue_disabled(
    operation: VenueOperation,
    *,
    known_open_order: bool = False,
) -> bool:
    """Allow only safe lifecycle operations after a venue is disabled.

    REQ: REQ-VEN-003, REQ-EXE-015
    """

    lifecycle_operations = {
        VenueOperation.CANCEL_ORDER,
        VenueOperation.GET_ORDER,
        VenueOperation.RECONCILE,
    }
    return known_open_order and operation in lifecycle_operations


def validate_order_type(order_type: OrderType | str) -> VenueCallResult:
    """Validate order type support before execution routes an order.

    REQ: REQ-EXE-010
    """

    value = order_type.value if isinstance(order_type, OrderType) else str(order_type)
    supported = {OrderType.LIMIT.value, OrderType.MARKET.value}
    if value not in supported:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("unsupported order type",),
            payload={"order_type": value},
        )
    return VenueCallResult(ok=True, payload={"order_type": value})


def check_market_order_slippage(
    *,
    venue: Venue,
    order_type: OrderType | str,
    estimated_slippage: Decimal | str | None,
) -> VenueCallResult:
    """Refuse market orders when estimated slippage exceeds threshold.

    REQ: REQ-EXE-011
    """

    order_type_result = validate_order_type(order_type)
    if not order_type_result.ok:
        return order_type_result
    if order_type_result.payload["order_type"] != OrderType.MARKET.value:
        return VenueCallResult(ok=True, payload={"slippage_checked": False})
    if estimated_slippage is None:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("slippage data unavailable",),
        )
    try:
        observed = Decimal(str(estimated_slippage))
    except (InvalidOperation, ValueError):
        return VenueCallResult(
            ok=False,
            refusal_reasons=("slippage data unavailable",),
        )
    threshold = configured_slippage_threshold(venue.value)
    if observed > threshold:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("slippage threshold exceeded",),
            payload={
                "estimated_slippage": str(observed),
                "threshold": str(threshold),
            },
        )
    return VenueCallResult(
        ok=True,
        payload={
            "slippage_checked": True,
            "estimated_slippage": str(observed),
            "threshold": str(threshold),
        },
    )


def validate_polymarket_credentials(credentials: PolymarketApiCredentials) -> VenueCallResult:
    """Validate that SDK authentication can be attempted.

    REQ: REQ-WAL-005, REQ-WAL-006, REQ-VEN-004
    """

    reasons: list[str] = []
    if not credentials.key_id.strip():
        reasons.append("missing Polymarket key id")
    if not credentials.secret_key.strip():
        reasons.append("missing Polymarket secret key")
    return VenueCallResult(ok=not reasons, refusal_reasons=tuple(reasons))


def build_polymarket_order_payload(request: PolymarketLiveOrderRequest) -> VenueCallResult:
    """Build the official SDK order payload after local validation.

    REQ: REQ-VEN-004, REQ-EXE-010, REQ-EXE-011
    """

    reasons: list[str] = []
    market_slug = request.market_slug.strip()
    intent = request.intent.strip().upper()
    order_type_raw = request.order_type.value if isinstance(request.order_type, OrderType) else str(request.order_type)
    order_type = POLYMARKET_ORDER_TYPES.get(order_type_raw.strip().lower()) or POLYMARKET_ORDER_TYPES.get(
        order_type_raw.strip().upper()
    )
    tif = request.tif.strip().upper()
    manual_order_indicator = request.manual_order_indicator.strip().upper()

    if not market_slug:
        reasons.append("missing Polymarket market slug")
    if intent not in POLYMARKET_ORDER_INTENTS:
        reasons.append("unsupported Polymarket order intent")
    if order_type not in set(POLYMARKET_ORDER_TYPES.values()):
        reasons.append("unsupported order type")
    if tif not in POLYMARKET_TIME_IN_FORCE:
        reasons.append("unsupported Polymarket time in force")
    if manual_order_indicator not in POLYMARKET_MANUAL_ORDER_INDICATORS:
        reasons.append("unsupported Polymarket manual order indicator")

    price_amount = _amount_payload(request.price, "price", reasons) if request.price is not None else None
    quantity = _numeric_payload(request.quantity, "quantity", reasons) if request.quantity is not None else None
    cash_order_qty = (
        _amount_payload(request.cash_order_qty, "cash_order_qty", reasons)
        if request.cash_order_qty is not None
        else None
    )
    current_price = (
        _amount_payload(request.current_price, "current_price", reasons)
        if request.current_price is not None
        else None
    )
    if order_type == "ORDER_TYPE_LIMIT":
        if price_amount is None:
            reasons.append("limit orders require price")
        if quantity is None:
            reasons.append("limit orders require quantity")
    if order_type == "ORDER_TYPE_MARKET" and quantity is None and cash_order_qty is None:
        reasons.append("market orders require quantity or cash order quantity")
    if request.slippage_tolerance_bips is not None and request.slippage_tolerance_bips < 0:
        reasons.append("slippage tolerance bips cannot be negative")
    if request.slippage_tolerance_ticks is not None and request.slippage_tolerance_ticks < 0:
        reasons.append("slippage tolerance ticks cannot be negative")
    if reasons:
        return VenueCallResult(ok=False, refusal_reasons=tuple(reasons))

    payload: dict[str, Any] = {
        "marketSlug": market_slug,
        "intent": intent,
        "type": order_type,
        "tif": tif,
        "manualOrderIndicator": manual_order_indicator,
        "synchronousExecution": request.synchronous_execution,
    }
    if price_amount is not None:
        payload["price"] = price_amount
    if quantity is not None:
        payload["quantity"] = quantity
    if cash_order_qty is not None:
        payload["cashOrderQty"] = cash_order_qty
    if request.participate_dont_initiate:
        payload["participateDontInitiate"] = True
    if request.good_till_time:
        payload["goodTillTime"] = request.good_till_time
    if request.max_block_time:
        payload["maxBlockTime"] = request.max_block_time
    slippage_tolerance: dict[str, Any] = {}
    if current_price is not None:
        slippage_tolerance["currentPrice"] = current_price
    if request.slippage_tolerance_bips is not None:
        slippage_tolerance["bips"] = request.slippage_tolerance_bips
    if request.slippage_tolerance_ticks is not None:
        slippage_tolerance["ticks"] = request.slippage_tolerance_ticks
    if slippage_tolerance:
        payload["slippageTolerance"] = slippage_tolerance

    return VenueCallResult(
        ok=True,
        payload={
            "order_payload": payload,
            "market_slug": market_slug,
            "order_type": order_type,
            "intent": intent,
        },
    )


def _decimal_payload(value: Decimal | str | int | float, field_name: str, reasons: list[str]) -> Decimal | None:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        reasons.append(f"{field_name} must be a decimal")
        return None
    if not decimal.is_finite():
        reasons.append(f"{field_name} must be finite")
        return None
    if decimal <= 0:
        reasons.append(f"{field_name} must be positive")
        return None
    return decimal


def _amount_payload(
    value: Decimal | str | int | float | None,
    field_name: str,
    reasons: list[str],
) -> dict[str, str] | None:
    if value is None:
        return None
    decimal = _decimal_payload(value, field_name, reasons)
    if decimal is None:
        return None
    return {"value": format(decimal, "f"), "currency": "USD"}


def _numeric_payload(
    value: Decimal | str | int | float | None,
    field_name: str,
    reasons: list[str],
) -> int | float | None:
    if value is None:
        return None
    decimal = _decimal_payload(value, field_name, reasons)
    if decimal is None:
        return None
    if decimal == decimal.to_integral_value():
        return int(decimal)
    return float(decimal)


def _response_value(response: Any, key: str) -> Any:
    if isinstance(response, dict):
        return response.get(key)
    return getattr(response, key, None)


class PolymarketLiveOrderAdapter:
    """Real Polymarket US adapter backed by the official SDK.

    REQ: REQ-VEN-004, REQ-EXE-010, REQ-EXE-011, REQ-EXE-017
    """

    def __init__(
        self,
        *,
        config: PolymarketVenueConfig,
        credentials: PolymarketApiCredentials,
        client_factory: Callable[[], PolymarketUsSdkClient] | None = None,
    ) -> None:
        self.config = config
        self.credentials = credentials
        self._client_factory = client_factory

    def verify_credentials(self) -> VenueCallResult:
        """Check read-only authenticated access without returning account data.

        REQ: REQ-WAL-005, REQ-WAL-006, REQ-EXE-017
        """

        preflight = self._preflight(require_official_sdk=False)
        if not preflight.ok:
            return preflight
        client = self._new_client()
        try:
            client.account.balances()
            return VenueCallResult(
                ok=True,
                payload={
                    "operation": "verify_credentials",
                    "venue": self.config.venue.value,
                },
            )
        except Exception as exc:  # pragma: no cover - exact SDK exceptions vary by installed version.
            return self._sdk_failure(exc, operation="verify_credentials")
        finally:
            self._close_client(client)

    def read_markets(self, *, limit: int = 50, slugs: tuple[str, ...] = ()) -> VenueCallResult:
        """Read markets through the official SDK without order submission.

        REQ: REQ-VEN-004, REQ-DAT-001, REQ-DAT-002, REQ-EXE-017
        """

        preflight = self._preflight(require_official_sdk=False)
        if not preflight.ok:
            return preflight
        if limit <= 0:
            return VenueCallResult(ok=False, refusal_reasons=("market read limit must be positive",))
        params: dict[str, Any] = {"limit": limit}
        if slugs:
            params["slug"] = list(slugs)
        client = self._new_client()
        try:
            response = client.markets.list(params)
            markets = _response_value(response, "markets") or ()
            return VenueCallResult(
                ok=True,
                payload={
                    "client_boundary": self.config.client_boundary.value,
                    "market_count": len(markets),
                    "operation": "read_markets",
                    "venue": self.config.venue.value,
                },
            )
        except Exception as exc:  # pragma: no cover - exact SDK exceptions vary by installed version.
            return self._sdk_failure(exc, operation="read_markets")
        finally:
            self._close_client(client)

    def preview_order(self, request: PolymarketLiveOrderRequest) -> VenueCallResult:
        """Preview an order through the official SDK without creating it.

        REQ: REQ-VEN-004, REQ-EXE-017
        """

        return self._send_order(request, create=False)

    def submit_order(self, request: PolymarketLiveOrderRequest) -> VenueCallResult:
        """Submit a live order through the official SDK.

        REQ: REQ-VEN-004, REQ-EXE-010, REQ-EXE-011
        """

        return self._send_order(request, create=True)

    def _send_order(self, request: PolymarketLiveOrderRequest, *, create: bool) -> VenueCallResult:
        preflight = self._preflight(require_official_sdk=True)
        if not preflight.ok:
            return preflight
        payload_result = build_polymarket_order_payload(request)
        if not payload_result.ok:
            return payload_result
        order_payload = payload_result.payload["order_payload"]
        client = self._new_client()
        try:
            if create:
                response = client.orders.create(order_payload)
                operation = "submit_order"
            else:
                response = client.orders.preview({"request": order_payload})
                operation = "preview_order"
            venue_order_id = _response_value(response, "id")
            return VenueCallResult(
                ok=True,
                payload={
                    "client_boundary": self.config.client_boundary.value,
                    "intent": payload_result.payload["intent"],
                    "market_slug": payload_result.payload["market_slug"],
                    "operation": operation,
                    "order_type": payload_result.payload["order_type"],
                    "venue": self.config.venue.value,
                    "venue_order_id": str(venue_order_id) if venue_order_id else None,
                },
            )
        except Exception as exc:  # pragma: no cover - exact SDK exceptions vary by installed version.
            return self._sdk_failure(exc, operation="submit_order" if create else "preview_order")
        finally:
            self._close_client(client)

    def _preflight(self, *, require_official_sdk: bool) -> VenueCallResult:
        config_result = validate_polymarket_config(self.config)
        if not config_result.ok:
            return config_result
        if not self.config.enabled:
            return VenueCallResult(ok=False, refusal_reasons=("Polymarket venue disabled",))
        if require_official_sdk and self.config.client_boundary != PolymarketClientBoundary.OFFICIAL_SDK:
            return VenueCallResult(
                ok=False,
                refusal_reasons=("Polymarket live adapter requires official SDK",),
            )
        credentials_result = validate_polymarket_credentials(self.credentials)
        if not credentials_result.ok:
            return credentials_result
        return VenueCallResult(ok=True)

    def _new_client(self) -> PolymarketUsSdkClient:
        if self._client_factory is not None:
            return self._client_factory()
        from polymarket_us import PolymarketUS

        return PolymarketUS(
            key_id=self.credentials.key_id,
            secret_key=self.credentials.secret_key,
            gateway_base_url=self.config.gateway_base_url,
            api_base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )

    def _sdk_failure(self, exc: Exception, *, operation: str) -> VenueCallResult:
        status_code = getattr(exc, "status_code", None)
        request_id = getattr(exc, "request_id", None)
        payload: dict[str, Any] = {
            "error_type": type(exc).__name__,
            "operation": operation,
            "venue": self.config.venue.value,
        }
        if status_code is not None:
            payload["status_code"] = status_code
        if request_id:
            payload["request_id"] = request_id
        return VenueCallResult(
            ok=False,
            refusal_reasons=("Polymarket SDK call failed",),
            payload=payload,
        )

    @staticmethod
    def _close_client(client: PolymarketUsSdkClient) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def polymarket_us_live_adapter_from_env(
    environ: dict[str, str] | None = None,
) -> PolymarketLiveOrderAdapter:
    """Build a production Polymarket US adapter from environment variables.

    REQ: REQ-WAL-005, REQ-WAL-006, REQ-VEN-004
    """

    source = environ if environ is not None else os.environ
    live_enabled = source.get("LIVE_ENABLED", "false").strip().lower() == "true"
    enabled = source.get("POLYMARKET_US_ENABLED", "false").strip().lower() == "true"
    config = PolymarketVenueConfig(
        venue=Venue.POLYMARKET_US,
        enabled=enabled,
        live_enabled=live_enabled,
        client_boundary=PolymarketClientBoundary.OFFICIAL_SDK,
        base_url=(
            source.get("POLYMARKET_API_BASE_URL", "").strip()
            or source.get("POLYMARKET_BASE_URL", "").strip()
            or POLYMARKET_US_API_BASE_URL
        ),
        gateway_base_url=source.get("POLYMARKET_GATEWAY_BASE_URL", POLYMARKET_US_GATEWAY_BASE_URL).strip()
        or POLYMARKET_US_GATEWAY_BASE_URL,
        credential_ref=source.get(
            "POLYMARKET_CREDENTIAL_REF",
            f"/codex-poly-bot/{source.get('ENVIRONMENT', 'local')}/polymarket/secret-key",
        ),
    )
    return PolymarketLiveOrderAdapter(
        config=config,
        credentials=PolymarketApiCredentials.from_env(source),
    )


class PolymarketContractClient:
    """Small testable adapter boundary for Polymarket live submit checks."""

    def __init__(self, config: PolymarketVenueConfig):
        self.config = config
        self.read_attempts = 0
        self.submit_attempts = 0

    def read_markets(self, *, snapshot_type: str = "full") -> VenueCallResult:
        """Validate dry-run market reads and count approved read attempts.

        REQ: REQ-VEN-004, REQ-DAT-001, REQ-DAT-002, REQ-EXE-017
        """

        result = dry_run_read_contract(self.config, snapshot_type=snapshot_type)
        if result.ok:
            self.read_attempts += 1
        return result

    def submit_order(self) -> VenueCallResult:
        """Validate contract and count approved submit attempts.

        REQ: REQ-VEN-004
        """

        result = live_submit_contract(self.config)
        if result.ok:
            self.submit_attempts += 1
        return result
