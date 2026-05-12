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
from typing import Any

from app.bootstrap import configured_slippage_threshold
from app.db import RepositoryRegistry
from app.domain import Environment, OrderType, Venue, supported_polymarket_venues
from app.services.ingestion_service import check_market_data_freshness


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
