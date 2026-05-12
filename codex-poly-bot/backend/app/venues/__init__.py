"""Venue adapter contracts and helpers.

REQ: REQ-VEN-003, REQ-VEN-004, REQ-VEN-005, REQ-EXE-010,
REQ-EXE-011, REQ-EXE-015, REQ-ALP-003, REQ-ALP-004,
REQ-ALP-008, REQ-ALP-015
"""

from app.venues.alpaca import (
    AlpacaAccountCredential,
    AlpacaClientBoundary,
    AlpacaContractClient,
    AlpacaMarketDataStatus,
    AlpacaOrderIntent,
    AlpacaVenueConfig,
    validate_alpaca_account_identifiers,
    validate_alpaca_client_boundary,
    validate_alpaca_long_only_order,
    validate_alpaca_market_data,
)
from app.venues.polymarket import (
    PolymarketClientBoundary,
    PolymarketContractClient,
    PolymarketVenueConfig,
    VenueCallResult,
    VenueOperation,
    allowed_when_venue_disabled,
    check_market_order_slippage,
    dry_run_read_contract,
    live_submit_contract,
    polymarket_live_eligibility_gate,
    polymarket_market_data_live_gate,
    validate_order_type,
    validate_polymarket_config,
)

__all__ = [
    "AlpacaAccountCredential",
    "AlpacaClientBoundary",
    "AlpacaContractClient",
    "AlpacaMarketDataStatus",
    "AlpacaOrderIntent",
    "AlpacaVenueConfig",
    "PolymarketClientBoundary",
    "PolymarketContractClient",
    "PolymarketVenueConfig",
    "VenueCallResult",
    "VenueOperation",
    "allowed_when_venue_disabled",
    "check_market_order_slippage",
    "dry_run_read_contract",
    "live_submit_contract",
    "polymarket_live_eligibility_gate",
    "polymarket_market_data_live_gate",
    "validate_alpaca_account_identifiers",
    "validate_alpaca_client_boundary",
    "validate_alpaca_long_only_order",
    "validate_alpaca_market_data",
    "validate_order_type",
    "validate_polymarket_config",
]
