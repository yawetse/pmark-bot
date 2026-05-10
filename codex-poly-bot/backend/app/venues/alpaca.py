"""Alpaca venue contract helpers.

REQ: REQ-ALP-003, REQ-ALP-004, REQ-ALP-015, REQ-ALP-016,
REQ-ALP-017, REQ-ALP-018
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from app.domain import Environment, ModelProvider, Venue
from app.venues.polymarket import VenueCallResult


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


class AlpacaContractClient:
    """Small testable adapter boundary for Alpaca operation checks.

    REQ: REQ-ALP-003
    """

    def __init__(self, config: AlpacaVenueConfig):
        self.config = config
        self.operation_calls = 0

    def execute_contract_operations(self) -> VenueCallResult:
        """Validate the client boundary and count approved operation calls.

        REQ: REQ-ALP-003
        """

        result = validate_alpaca_client_boundary(self.config)
        if result.ok:
            self.operation_calls = len(result.payload["operations"])
        return result
