"""Kalshi REST venue boundary.

REQ: REQ-KAL-003, REQ-KAL-004, REQ-KAL-005, REQ-KAL-006,
REQ-KAL-007, REQ-KAL-008
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import logging
import os
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit
from enum import Enum

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import httpx

from app.domain import Environment
from app.venues.polymarket import VenueCallResult


LOGGER = logging.getLogger(__name__)


KALSHI_PRODUCTION_API_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
KALSHI_DEMO_API_BASE_URL = "https://external-api.demo.kalshi.co/trade-api/v2"
KALSHI_V2_ORDER_PATH = "/portfolio/events/orders"
KALSHI_SUPPORTED_TIME_IN_FORCE = frozenset(
    {"fill_or_kill", "good_till_canceled", "immediate_or_cancel"}
)
KALSHI_SUPPORTED_SIDES = frozenset({"bid", "ask"})
KALSHI_SUPPORTED_STP = frozenset({"taker_at_cross", "maker"})


@dataclass(frozen=True)
class KalshiCredentials:
    """Private Kalshi credential material held only at the adapter boundary.

    REQ: REQ-KAL-004
    """

    key_id: str = field(repr=False)
    private_key_pem: str = field(repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "KalshiCredentials":
        """Load a key ID and RSA PEM without logging either value.

        REQ: REQ-KAL-004
        """

        source = environ if environ is not None else os.environ
        return cls(
            key_id=str(source.get("KALSHI_KEY_ID", "")).strip(),
            private_key_pem=str(source.get("KALSHI_PRIVATE_KEY", "")).strip().replace("\\n", "\n"),
        )


class KalshiAuthSigner:
    """Build Kalshi RSA-PSS request authentication headers.

    REQ: REQ-KAL-004
    """

    def __init__(self, credentials: KalshiCredentials) -> None:
        if not credentials.key_id or not credentials.private_key_pem:
            raise ValueError("missing Kalshi credentials")
        try:
            private_key = serialization.load_pem_private_key(
                credentials.private_key_pem.encode(),
                password=None,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid Kalshi private key") from exc
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise ValueError("Kalshi private key must be RSA")
        self._key_id = credentials.key_id
        self._private_key = private_key

    def headers(
        self,
        method: str,
        path: str,
        *,
        timestamp_ms: int | None = None,
    ) -> dict[str, str]:
        """Sign timestamp, uppercase method, and path without its query string.

        REQ: REQ-KAL-004
        """

        timestamp = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        clean_path = urlsplit(path).path
        message = f"{timestamp}{method.upper()}{clean_path}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp),
        }


@dataclass(frozen=True)
class KalshiLiveOrderRequest:
    """Validated fixed-point input for a Kalshi V2 event order.

    REQ: REQ-KAL-005, REQ-KAL-006
    """

    ticker: str
    side: str
    count: Decimal | str
    price: Decimal | str
    client_order_id: str
    time_in_force: str = "immediate_or_cancel"
    self_trade_prevention_type: str = "taker_at_cross"
    cancel_order_on_pause: bool = True
    reduce_only: bool = False
    post_only: bool = False
    subaccount: int = 0
    exchange_index: int = 0
    price_ranges: tuple[dict[str, Decimal | str], ...] = ()
    market_style: bool = True


class KalshiHttpError(RuntimeError):
    """Sanitized Kalshi failure that never retains response or credential data.

    REQ: REQ-KAL-003, REQ-KAL-004, REQ-KAL-006
    """

    def __init__(self, *, code: str, status_code: int | None, operation: str) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.operation = operation


class KalshiOrderOutcome(str, Enum):
    """Durable outcomes for one Kalshi submit attempt.

    REQ: REQ-KAL-006
    """

    REFUSED = "refused"
    UNKNOWN_SUBMIT = "unknown_submit"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED_OPEN = "partially_filled_open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    UNFILLED_CANCELED = "unfilled_canceled"


@dataclass(frozen=True)
class KalshiOrderResult:
    """Typed Kalshi order result that preserves ambiguous send state.

    REQ: REQ-KAL-005, REQ-KAL-006
    """

    outcome: KalshiOrderOutcome
    client_order_id: str
    venue_order_id: str | None = None
    http_status: int | None = None
    send_started: bool = False
    safe_error_code: str | None = None
    fill_count: Decimal = Decimal("0")
    remaining_count: Decimal = Decimal("0")
    retry_eligible: bool = False

    @property
    def terminal(self) -> bool:
        return self.outcome in {
            KalshiOrderOutcome.REFUSED,
            KalshiOrderOutcome.PARTIALLY_FILLED,
            KalshiOrderOutcome.FILLED,
            KalshiOrderOutcome.UNFILLED_CANCELED,
        }

    @property
    def ok(self) -> bool:
        return self.outcome in {
            KalshiOrderOutcome.SUBMITTED,
            KalshiOrderOutcome.PARTIALLY_FILLED_OPEN,
            KalshiOrderOutcome.PARTIALLY_FILLED,
            KalshiOrderOutcome.FILLED,
            KalshiOrderOutcome.UNFILLED_CANCELED,
        }

    @property
    def refusal_reasons(self) -> tuple[str, ...]:
        return (self.safe_error_code,) if self.safe_error_code else ()

    @property
    def refusal_reason(self) -> str | None:
        return self.safe_error_code

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "fill_count": format(self.fill_count, "f"),
            "http_status": self.http_status,
            "order_id": self.venue_order_id,
            "outcome": self.outcome.value,
            "remaining_count": format(self.remaining_count, "f"),
            "retry_eligible": self.retry_eligible,
            "send_started": self.send_started,
        }


class KalshiLiveOrderAdapter:
    """Authenticated Kalshi REST adapter with read-only retry semantics.

    REQ: REQ-KAL-003, REQ-KAL-004, REQ-KAL-005, REQ-KAL-006,
    REQ-KAL-007, REQ-KAL-008
    """

    def __init__(
        self,
        *,
        base_url: str,
        credentials: KalshiCredentials,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
        read_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._signer = KalshiAuthSigner(credentials)
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._read_retries = max(0, min(read_retries, 2))
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._sleep = sleep

    def exchange_status(self) -> VenueCallResult:
        """Read whether the exchange and trading engine are active.

        REQ: REQ-KAL-007
        """

        try:
            payload = self._request("GET", "/exchange/status", operation="exchange_status")
        except KalshiHttpError as exc:
            return self._failed_result(exc)
        active = bool(payload.get("exchange_active")) and bool(payload.get("trading_active"))
        return VenueCallResult(
            ok=active,
            refusal_reasons=() if active else ("Kalshi trading is inactive",),
            payload={
                "exchange_active": bool(payload.get("exchange_active")),
                "trading_active": bool(payload.get("trading_active")),
                "operation": "exchange_status",
            },
        )

    def submit_order(self, request: KalshiLiveOrderRequest) -> KalshiOrderResult:
        """Submit one V2 order without retrying the mutation.

        REQ: REQ-KAL-005, REQ-KAL-006, REQ-KAL-007
        """

        refusal_reasons, body = _validated_order_body(request)
        if refusal_reasons:
            return KalshiOrderResult(
                outcome=KalshiOrderOutcome.REFUSED,
                client_order_id=request.client_order_id,
                safe_error_code=refusal_reasons[0],
            )
        status = self.exchange_status()
        if not status.ok:
            return KalshiOrderResult(
                outcome=KalshiOrderOutcome.REFUSED,
                client_order_id=request.client_order_id,
                safe_error_code=status.refusal_reason or "kalshi_exchange_inactive",
            )
        try:
            payload = self._request(
                "POST",
                KALSHI_V2_ORDER_PATH,
                operation="submit_order",
                json_body=body,
                retry_safe_reads=False,
            )
        except KalshiHttpError as exc:
            ambiguous = (
                exc.status_code is None
                or exc.status_code in {409, 429}
                or (
                    exc.status_code is not None
                    and (200 <= exc.status_code < 300 or exc.status_code >= 500)
                )
            )
            return KalshiOrderResult(
                outcome=(
                    KalshiOrderOutcome.UNKNOWN_SUBMIT
                    if ambiguous
                    else KalshiOrderOutcome.REFUSED
                ),
                client_order_id=request.client_order_id,
                http_status=exc.status_code,
                send_started=True,
                safe_error_code=exc.code,
            )
        order = payload
        order_id = str(order.get("order_id") or "").strip()
        response_client_order_id = str(order.get("client_order_id") or "").strip()
        fill_count = _strict_nonnegative_decimal(order.get("fill_count"))
        remaining_count = _strict_nonnegative_decimal(order.get("remaining_count"))
        try:
            response_timestamp_ms = int(order.get("ts_ms"))
        except (TypeError, ValueError):
            response_timestamp_ms = 0
        if (
            not order_id
            or response_client_order_id not in {"", request.client_order_id}
            or fill_count is None
            or remaining_count is None
            or response_timestamp_ms <= 0
            or fill_count + remaining_count > Decimal(str(request.count))
        ):
            return KalshiOrderResult(
                outcome=KalshiOrderOutcome.UNKNOWN_SUBMIT,
                client_order_id=request.client_order_id,
                send_started=True,
                safe_error_code="kalshi_submit_response_malformed",
            )
        if fill_count > 0 and remaining_count == 0:
            outcome = KalshiOrderOutcome.FILLED
        elif request.time_in_force == "immediate_or_cancel":
            outcome = (
                KalshiOrderOutcome.PARTIALLY_FILLED
                if fill_count > 0
                else KalshiOrderOutcome.UNFILLED_CANCELED
            )
        else:
            outcome = (
                KalshiOrderOutcome.PARTIALLY_FILLED_OPEN
                if fill_count > 0
                else KalshiOrderOutcome.SUBMITTED
            )
        return KalshiOrderResult(
            outcome=outcome,
            client_order_id=response_client_order_id or request.client_order_id,
            venue_order_id=order_id,
            http_status=201,
            send_started=True,
            fill_count=fill_count,
            remaining_count=remaining_count,
        )

    def get_order(self, order_id: str) -> VenueCallResult:
        """Read one order for reconciliation using safe retry behavior.

        REQ: REQ-KAL-006, REQ-KAL-008
        """

        if not order_id.strip():
            return VenueCallResult(ok=False, refusal_reasons=("missing Kalshi order ID",))
        try:
            payload = self._request(
                "GET",
                f"/portfolio/orders/{order_id.strip()}",
                operation="get_order",
            )
        except KalshiHttpError as exc:
            return self._failed_result(exc)
        return VenueCallResult(ok=True, payload=payload)

    def find_order_by_client_order_id(
        self,
        client_order_id: str,
        *,
        ticker: str | None = None,
    ) -> VenueCallResult:
        """Find exactly one current or historical order by reserved client ID.

        REQ: REQ-KAL-006, REQ-KAL-014
        """

        expected = client_order_id.strip()
        if not expected:
            return VenueCallResult(ok=False, refusal_reasons=("missing Kalshi client order ID",))
        matches: list[dict[str, Any]] = []
        for path in ("/portfolio/orders", "/historical/orders"):
            result = self.read_paginated(
                path,
                collection_key="orders",
                params={"subaccount": 0, "limit": 1000},
            )
            if not result.ok:
                return result
            matches.extend(
                order
                for order in result.payload.get("orders", [])
                if str(order.get("client_order_id") or "") == expected
                and (not ticker or str(order.get("ticker") or "") == ticker)
            )
            if matches:
                break
        unique = {str(order.get("order_id")): order for order in matches if order.get("order_id")}
        if len(unique) != 1:
            code = "kalshi_order_not_found" if not unique else "kalshi_order_match_ambiguous"
            return VenueCallResult(
                ok=False,
                refusal_reasons=(code,),
                payload={"client_order_id": expected, "match_count": len(unique)},
            )
        return VenueCallResult(ok=True, payload={"order": next(iter(unique.values()))})

    def cancel_order(self, order_id: str) -> VenueCallResult:
        """Reconcile then cancel one V2 order without retrying DELETE.

        REQ: REQ-KAL-006
        """

        if not order_id.strip():
            return VenueCallResult(ok=False, refusal_reasons=("missing Kalshi order ID",))
        observed = self.get_order(order_id)
        if not observed.ok:
            return observed
        observed_order = (
            observed.payload.get("order")
            if isinstance(observed.payload.get("order"), dict)
            else None
        )
        if not isinstance(observed_order, dict):
            return VenueCallResult(
                ok=False,
                refusal_reasons=("kalshi_order_state_malformed",),
                payload={"operation": "cancel_order", "order_id": order_id},
            )
        observed_order_id = str(observed_order.get("order_id") or "").strip()
        observed_status = str(observed_order.get("status") or "").lower()
        if observed_order_id != order_id or not observed_status:
            return VenueCallResult(
                ok=False,
                refusal_reasons=("kalshi_order_state_malformed",),
                payload={"operation": "cancel_order", "order_id": order_id},
            )
        if observed_status in {"canceled", "executed", "filled", "rejected"}:
            return VenueCallResult(
                ok=True,
                payload={"operation": "cancel_order", "order_id": order_id, "status": observed_status},
            )
        if observed_status != "resting":
            return VenueCallResult(
                ok=False,
                refusal_reasons=("kalshi_order_not_cancelable",),
                payload={
                    "operation": "cancel_order",
                    "order_id": order_id,
                    "status": observed_status,
                },
            )
        try:
            payload = self._request(
                "DELETE",
                f"{KALSHI_V2_ORDER_PATH}/{order_id.strip()}",
                operation="cancel_order",
                retry_safe_reads=False,
            )
        except KalshiHttpError as exc:
            unknown = exc.status_code is None or exc.status_code == 429 or (
                exc.status_code is not None and exc.status_code >= 500
            )
            return VenueCallResult(
                ok=False,
                refusal_reasons=("kalshi_cancel_unknown" if unknown else exc.code,),
                payload={
                    "operation": "cancel_order",
                    "order_id": order_id,
                    "unknown": unknown,
                },
            )
        response_order_id = str(payload.get("order_id") or "").strip()
        reduced_by = _strict_nonnegative_decimal(payload.get("reduced_by"))
        try:
            response_timestamp_ms = int(payload.get("ts_ms"))
        except (TypeError, ValueError):
            response_timestamp_ms = 0
        if (
            response_order_id != order_id
            or reduced_by is None
            or reduced_by <= 0
            or response_timestamp_ms <= 0
        ):
            return VenueCallResult(
                ok=False,
                refusal_reasons=("kalshi_cancel_unknown",),
                payload={
                    "operation": "cancel_order",
                    "order_id": order_id,
                    "unknown": True,
                },
            )
        return VenueCallResult(ok=True, payload=payload)

    def read_paginated(
        self,
        path: str,
        *,
        collection_key: str,
        params: Mapping[str, str | int] | None = None,
        max_pages: int = 100,
    ) -> VenueCallResult:
        """Read one cursor-paginated primary-account collection.

        REQ: REQ-KAL-008
        """

        items: list[dict[str, Any]] = []
        cursor = ""
        page_limit = max(1, min(max_pages, 100))
        for page_index in range(page_limit):
            page_params = dict(params or {})
            if cursor:
                page_params["cursor"] = cursor
            try:
                payload = self._request(
                    "GET",
                    path,
                    operation=f"read_{collection_key}",
                    params=page_params,
                )
            except KalshiHttpError as exc:
                return self._failed_result(exc)
            page_items = payload.get(collection_key)
            if not isinstance(page_items, list):
                return VenueCallResult(
                    ok=False,
                    refusal_reasons=("kalshi_malformed_response",),
                    payload={"operation": f"read_{collection_key}"},
                )
            items.extend(item for item in page_items if isinstance(item, dict))
            next_cursor = str(payload.get("cursor") or "").strip()
            if not next_cursor:
                break
            if next_cursor == cursor:
                return VenueCallResult(
                    ok=False,
                    refusal_reasons=("kalshi_repeated_cursor",),
                    payload={collection_key: items},
                )
            cursor = next_cursor
            if page_index + 1 == page_limit:
                return VenueCallResult(
                    ok=False,
                    refusal_reasons=("kalshi_pagination_limit",),
                    payload={collection_key: items},
                )
        return VenueCallResult(ok=True, payload={collection_key: items})

    def balance(self) -> VenueCallResult:
        """Read primary subaccount balance.

        REQ: REQ-KAL-008
        """

        try:
            payload = self._request(
                "GET",
                "/portfolio/balance",
                operation="balance",
                params={"subaccount": 0},
            )
        except KalshiHttpError as exc:
            return self._failed_result(exc)
        return VenueCallResult(ok=True, payload=payload)

    def positions(self) -> VenueCallResult:
        """Read all market positions for the primary subaccount.

        REQ: REQ-KAL-008
        """

        return self.read_paginated(
            "/portfolio/positions",
            collection_key="market_positions",
            params={"subaccount": 0, "limit": 1000},
        )

    def fills(self) -> VenueCallResult:
        """Read all fills for the primary subaccount.

        REQ: REQ-KAL-008
        """

        return self.read_paginated(
            "/portfolio/fills",
            collection_key="fills",
            params={"subaccount": 0, "limit": 1000},
        )

    def settlements(self) -> VenueCallResult:
        """Read all settlements for the primary subaccount.

        REQ: REQ-KAL-008
        """

        return self.read_paginated(
            "/portfolio/settlements",
            collection_key="settlements",
            params={"subaccount": 0, "limit": 1000},
        )

    def orders(self) -> VenueCallResult:
        """Read all orders for the primary subaccount.

        REQ: REQ-KAL-006, REQ-KAL-008
        """

        return self.read_paginated(
            "/portfolio/orders",
            collection_key="orders",
            params={"subaccount": 0, "limit": 1000},
        )

    def api_keys(self) -> VenueCallResult:
        """Read authenticated account membership and credential scopes.

        REQ: REQ-KAL-012
        """

        try:
            payload = self._request("GET", "/api_keys", operation="api_keys")
        except KalshiHttpError as exc:
            return self._failed_result(exc)
        keys = payload.get("api_keys")
        if not isinstance(keys, list):
            return VenueCallResult(
                ok=False,
                refusal_reasons=("kalshi_malformed_response",),
                payload={"operation": "api_keys"},
            )
        return VenueCallResult(
            ok=True,
            payload={"api_keys": [row for row in keys if isinstance(row, dict)]},
        )

    def historical_cutoff(self) -> VenueCallResult:
        """Read live-to-historical cutoff timestamps.

        REQ: REQ-KAL-014
        """

        try:
            payload = self._request("GET", "/historical/cutoff", operation="historical_cutoff")
        except KalshiHttpError as exc:
            return self._failed_result(exc)
        required = ("market_settled_ts", "trades_created_ts", "orders_updated_ts")
        if any(not str(payload.get(field) or "").strip() for field in required):
            return VenueCallResult(
                ok=False,
                refusal_reasons=("kalshi_malformed_response",),
                payload={"operation": "historical_cutoff"},
            )
        return VenueCallResult(ok=True, payload=payload)

    def historical_fills(self) -> VenueCallResult:
        """Read all historical primary-account fills.

        REQ: REQ-KAL-014
        """

        result = self.read_paginated(
            "/historical/fills",
            collection_key="fills",
            params={"limit": 1000},
        )
        if result.ok:
            filtered: list[dict[str, Any]] = []
            for row in result.payload.get("fills", []):
                try:
                    subaccount = int(row.get("subaccount_number") or 0)
                except (TypeError, ValueError):
                    return VenueCallResult(
                        ok=False,
                        refusal_reasons=("kalshi_malformed_response",),
                        payload={"operation": "historical_fills"},
                    )
                if subaccount == 0:
                    filtered.append(row)
            result.payload["fills"] = filtered
        return result

    def historical_orders(self) -> VenueCallResult:
        """Read all historical primary-account terminal orders.

        REQ: REQ-KAL-006, REQ-KAL-014
        """

        result = self.read_paginated(
            "/historical/orders",
            collection_key="orders",
            params={"limit": 1000},
        )
        if result.ok:
            filtered: list[dict[str, Any]] = []
            for row in result.payload.get("orders", []):
                try:
                    subaccount = int(row.get("subaccount_number") or 0)
                except (TypeError, ValueError):
                    return VenueCallResult(
                        ok=False,
                        refusal_reasons=("kalshi_malformed_response",),
                        payload={"operation": "historical_orders"},
                    )
                if subaccount == 0:
                    filtered.append(row)
            result.payload["orders"] = filtered
        return result

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: Mapping[str, str | int] | None = None,
        json_body: dict[str, Any] | None = None,
        retry_safe_reads: bool = True,
    ) -> dict[str, Any]:
        attempts = self._read_retries + 1 if method.upper() == "GET" and retry_safe_reads else 1
        for attempt in range(attempts):
            signature_path = urlsplit(self.base_url).path.rstrip("/") + "/" + path.lstrip("/")
            headers = self._signer.headers(method, signature_path)
            LOGGER.info(
                "kalshi_venue_request method=%s operation=%s attempt=%s",
                method.upper(),
                operation,
                attempt + 1,
            )
            try:
                with httpx.Client(
                    base_url=self.base_url,
                    transport=self._transport,
                    timeout=self._timeout_seconds,
                ) as client:
                    response = client.request(
                        method,
                        path,
                        params=params,
                        json=json_body,
                        headers=headers,
                    )
            except httpx.HTTPError as exc:
                if attempt + 1 < attempts:
                    self._sleep(self._retry_backoff_seconds * (2**attempt))
                    continue
                raise KalshiHttpError(
                    code="kalshi_transport_error",
                    status_code=None,
                    operation=operation,
                ) from exc
            if 200 <= response.status_code < 300:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise KalshiHttpError(
                        code="kalshi_malformed_response",
                        status_code=response.status_code,
                        operation=operation,
                    ) from exc
                if not isinstance(payload, dict):
                    raise KalshiHttpError(
                        code="kalshi_malformed_response",
                        status_code=response.status_code,
                        operation=operation,
                    )
                return payload
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt + 1 < attempts:
                self._sleep(self._retry_backoff_seconds * (2**attempt))
                continue
            code = (
                "kalshi_rate_limited"
                if response.status_code == 429
                else "kalshi_duplicate_client_order_id"
                if response.status_code == 409
                else "kalshi_credentials_rejected"
                if response.status_code in {401, 403}
                else "kalshi_http_error"
            )
            raise KalshiHttpError(
                code=code,
                status_code=response.status_code,
                operation=operation,
            )
        raise KalshiHttpError(code="kalshi_transport_error", status_code=None, operation=operation)

    @staticmethod
    def _failed_result(exc: KalshiHttpError) -> VenueCallResult:
        return VenueCallResult(
            ok=False,
            refusal_reasons=(exc.code,),
            payload={
                "operation": exc.operation,
                "status_code": exc.status_code,
            },
        )


def _validated_order_body(request: KalshiLiveOrderRequest) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    ticker = request.ticker.strip()
    client_order_id = request.client_order_id.strip()
    if not ticker:
        reasons.append("missing Kalshi ticker")
    if not client_order_id:
        reasons.append("missing Kalshi client order ID")
    if request.side not in KALSHI_SUPPORTED_SIDES:
        reasons.append("unsupported Kalshi side")
    if request.time_in_force not in KALSHI_SUPPORTED_TIME_IN_FORCE:
        reasons.append("unsupported Kalshi time in force")
    if request.self_trade_prevention_type not in KALSHI_SUPPORTED_STP:
        reasons.append("unsupported Kalshi self trade prevention")
    if not request.cancel_order_on_pause:
        reasons.append("Kalshi pause cancellation is required")
    if request.market_style and request.time_in_force != "immediate_or_cancel":
        reasons.append("Kalshi market-style orders require immediate or cancel")
    if request.market_style and request.post_only:
        reasons.append("Kalshi market-style orders cannot be post only")
    if request.subaccount != 0:
        reasons.append("Kalshi primary subaccount is required")
    if request.exchange_index != 0:
        reasons.append("Kalshi exchange index zero is required")
    try:
        count = Decimal(str(request.count))
        price = Decimal(str(request.price))
    except (InvalidOperation, ValueError):
        reasons.append("invalid Kalshi fixed-point value")
        count = Decimal("0")
        price = Decimal("0")
    if not count.is_finite() or count <= 0:
        reasons.append("Kalshi count must be positive")
    if not price.is_finite() or price <= 0 or price >= 1:
        reasons.append("Kalshi price must be between zero and one")
    if price.is_finite() and price > 0 and price < 1:
        if not request.price_ranges:
            reasons.append("missing Kalshi price ranges")
        elif not _price_matches_range(price, request.price_ranges):
            reasons.append("Kalshi price is not aligned to a market price range")
    if count.is_finite() and count.as_tuple().exponent < -2:
        reasons.append("Kalshi count has unsupported precision")
    body = {
        "cancel_order_on_pause": request.cancel_order_on_pause,
        "client_order_id": client_order_id,
        "count": str(request.count),
        "side": request.side,
        "ticker": ticker,
        "time_in_force": request.time_in_force,
        "price": str(request.price),
        "self_trade_prevention_type": request.self_trade_prevention_type,
        "post_only": request.post_only,
        "reduce_only": request.reduce_only,
        "subaccount": request.subaccount,
        "exchange_index": request.exchange_index,
    }
    return reasons, body


def kalshi_live_order_adapter_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> KalshiLiveOrderAdapter:
    """Build a demo or production adapter while refusing environment crossover.

    REQ: REQ-KAL-004, REQ-KAL-007, REQ-KAL-010
    """

    source = environ if environ is not None else os.environ
    app_environment = str(source.get("APP_ENV") or source.get("ENVIRONMENT") or "local").strip().lower()
    kalshi_environment = str(source.get("KALSHI_ENVIRONMENT") or "demo").strip().lower()
    if kalshi_environment not in {"demo", "production"}:
        raise ValueError("unsupported Kalshi environment")
    if app_environment == Environment.PRODUCTION.value and kalshi_environment != "production":
        raise ValueError("production requires the Kalshi production environment")
    if app_environment != Environment.PRODUCTION.value and kalshi_environment == "production":
        raise ValueError("non-production cannot use the Kalshi production environment")
    base_url = (
        KALSHI_PRODUCTION_API_BASE_URL
        if kalshi_environment == "production"
        else KALSHI_DEMO_API_BASE_URL
    )
    credentials = KalshiCredentials.from_env(source)
    return KalshiLiveOrderAdapter(
        base_url=base_url,
        credentials=credentials,
        transport=transport,
        timeout_seconds=_float_setting(source.get("KALSHI_HTTP_TIMEOUT_SECONDS"), 10.0),
        read_retries=_int_setting(source.get("KALSHI_READ_RETRIES"), 2),
        retry_backoff_seconds=_float_setting(source.get("KALSHI_RETRY_BACKOFF_SECONDS"), 0.25),
    )


def _float_setting(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _price_matches_range(
    price: Decimal,
    price_ranges: tuple[dict[str, Decimal | str], ...],
) -> bool:
    """Return whether a price falls on a market-provided price step.

    REQ: REQ-KAL-002, REQ-KAL-005
    """

    for price_range in price_ranges:
        try:
            start = Decimal(str(price_range.get("start") or price_range.get("min") or "0"))
            end = Decimal(str(price_range.get("end") or price_range.get("max") or "1"))
            step = Decimal(str(price_range.get("step") or "0"))
        except (InvalidOperation, ValueError):
            continue
        if step > 0 and start <= price <= end and (price - start) % step == 0:
            return True
    return False


def _int_setting(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decimal_value(value: Any, default: Decimal) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default
    return result if result.is_finite() else default


def _strict_nonnegative_decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result < 0:
        return None
    return result
