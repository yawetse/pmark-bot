"""Polymarket venue contract helpers.

REQ: REQ-VEN-003, REQ-VEN-004, REQ-VEN-005, REQ-EXE-010,
REQ-EXE-011, REQ-EXE-015
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from app.bootstrap import configured_slippage_threshold
from app.domain import OrderType, Venue, supported_polymarket_venues


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
    jurisdiction_supported: bool = True
    stale_threshold_seconds: int = 60


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


class PolymarketContractClient:
    """Small testable adapter boundary for Polymarket live submit checks."""

    def __init__(self, config: PolymarketVenueConfig):
        self.config = config
        self.submit_attempts = 0

    def submit_order(self) -> VenueCallResult:
        """Validate contract and count approved submit attempts.

        REQ: REQ-VEN-004
        """

        result = live_submit_contract(self.config)
        if result.ok:
            self.submit_attempts += 1
        return result
