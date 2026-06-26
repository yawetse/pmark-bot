"""Red-phase tests for Venue Integration."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tests.spec.helpers import pending
from app.bootstrap import load_runtime_defaults, safe_defaults, venue_operation_gate, with_venue_enabled
from app.db import RepositoryRegistry
from app.domain import Environment, Instrument, InstrumentType, OrderType, Venue, supported_polymarket_venues
from app.services import (
    ActorContext,
    AuthService,
    ConfigPatchOperation,
    ConfigService,
    PolymarketExecutionRequest,
    execute_polymarket_order,
)
from app.venues import (
    POLYMARKET_US_API_BASE_URL,
    PolymarketApiCredentials,
    PolymarketClientBoundary,
    PolymarketContractClient,
    PolymarketLiveOrderAdapter,
    PolymarketLiveOrderRequest,
    PolymarketVenueConfig,
    VenueOperation,
    allowed_when_venue_disabled,
    build_polymarket_order_payload,
    polymarket_live_eligibility_gate,
    polymarket_market_data_live_gate,
    validate_polymarket_config,
)


class FakePolymarketOrders:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.preview_calls: list[dict] = []
        self.close_position_calls: list[dict] = []

    def create(self, params: dict) -> dict:
        self.create_calls.append(params)
        return {"id": "pm-order-1", "executions": []}

    def preview(self, params: dict) -> dict:
        self.preview_calls.append(params)
        return {"order": {"id": "pm-preview-1"}}

    def close_position(self, params: dict) -> dict:
        self.close_position_calls.append(params)
        return {"id": "pm-close-1", "executions": []}


class FakePolymarketMarkets:
    def __init__(self) -> None:
        self.list_calls: list[dict | None] = []

    def list(self, params: dict | None = None) -> dict:
        self.list_calls.append(params)
        return {"markets": [{"slug": "will-fed-cut"}]}


class FakePolymarketAccount:
    def __init__(self) -> None:
        self.balance_calls = 0

    def balances(self) -> dict:
        self.balance_calls += 1
        return {"balances": []}


class FakePolymarketSdkClient:
    def __init__(self) -> None:
        self.orders = FakePolymarketOrders()
        self.markets = FakePolymarketMarkets()
        self.account = FakePolymarketAccount()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_req_ven_001_01_supported_venue_configs_polymarket_us_international_venue_adapters() -> None:
    """TST-REQ-VEN-001-01: Validates REQ-VEN-001

    Given: supported venue configs for Polymarket US and International
    When: venue adapters are registered
    Then: both venues are available as configurable trading venues
    """
    assert supported_polymarket_venues() == {
        Venue.POLYMARKET_US,
        Venue.POLYMARKET_INTERNATIONAL,
    }

def test_req_ven_001_02_unknown_polymarket_venue_key_venue_adapters_resolved_system() -> None:
    """TST-REQ-VEN-001-02: Validates REQ-VEN-001

    Given: an unknown Polymarket venue key
    When: venue adapters are resolved
    Then: the system rejects the venue and records a configuration error
    """
    with pytest.raises(ValueError):
        Venue("unknown_polymarket")
    with pytest.raises(ValidationError):
        Instrument(
            venue=Venue.POLYMARKET_US,
            instrument_type=InstrumentType.PREDICTION_MARKET,
            market_id="   ",
            outcome_id="yes",
            display_name="Whitespace Market",
        )

def test_req_ven_002_01_no_explicit_venue_setting_app_loads_runtime_config() -> None:
    """TST-REQ-VEN-002-01: Validates REQ-VEN-002

    Given: no explicit venue setting
    When: the app loads runtime config
    Then: `polymarket_us` is selected as the default venue
    """
    defaults = load_runtime_defaults()

    assert defaults.default_selected_venue == "polymarket_us"

def test_req_ven_002_02_explicit_supported_venue_setting_app_loads_runtime_config() -> None:
    """TST-REQ-VEN-002-02: Validates REQ-VEN-002

    Given: an explicit supported venue setting
    When: the app loads runtime config
    Then: the explicit setting is used instead of the default
    """
    defaults = load_runtime_defaults(explicit_venue="alpaca")

    assert defaults.default_selected_venue == "alpaca"

def test_req_ven_003_01_venue_enabled_false_scan_score_trade_requested_system() -> None:
    """TST-REQ-VEN-003-01: Validates REQ-VEN-003

    Given: a venue with `enabled=false`
    When: scan, score, or trade is requested
    Then: the system refuses the operation before external calls
    """
    for operation in ("scan", "score", "trade"):
        gate = venue_operation_gate("polymarket_us", operation)
        assert not gate.allowed
        assert gate.refusal_reason == f"venue disabled for {operation}"

def test_req_ven_003_02_venue_toggled_enabled_disabled_next_loop_starts_no() -> None:
    """TST-REQ-VEN-003-02: Validates REQ-VEN-003

    Given: a venue is toggled from enabled to disabled
    When: the next loop starts
    Then: no stale enabled state allows scan, score, or trade
    """
    enabled = with_venue_enabled(safe_defaults(), "polymarket_us", True)
    disabled = with_venue_enabled(enabled, "polymarket_us", False)

    assert venue_operation_gate("polymarket_us", "scan", enabled).allowed
    assert not venue_operation_gate("polymarket_us", "scan", disabled).allowed

def test_req_ven_004_01_live_mode_approved_polymarket_order_execution_submits_order() -> None:
    """TST-REQ-VEN-004-01: Validates REQ-VEN-004

    Given: live mode and an approved Polymarket order
    When: execution submits the order
    Then: the official SDK or documented API client is used
    """
    client = PolymarketContractClient(
        PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=True,
            client_boundary=PolymarketClientBoundary.OFFICIAL_SDK,
            base_url="https://clob.polymarket.com",
            credential_ref="/codex-poly-bot/development/polymarket/openai/wallet",
        )
    )

    result = client.submit_order()

    assert result.ok
    assert result.payload["client_boundary"] == PolymarketClientBoundary.OFFICIAL_SDK.value
    assert client.submit_attempts == 1

def test_req_ven_004_02_non_official_polymarket_client_implementation_configured_live_order() -> None:
    """TST-REQ-VEN-004-02: Validates REQ-VEN-004

    Given: a non-official Polymarket client implementation is configured
    When: live order submission is attempted
    Then: the system blocks the submission
    """
    client = PolymarketContractClient(
        PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=True,
            client_boundary=PolymarketClientBoundary.UNAPPROVED,
            base_url="https://clob.polymarket.com",
            credential_ref="/codex-poly-bot/development/polymarket/openai/wallet",
        )
    )

    result = client.submit_order()

    assert not result.ok
    assert "unapproved Polymarket client boundary" in result.refusal_reasons
    assert client.submit_attempts == 0

def test_req_ven_004_03_dry_run_polymarket_read_uses_approved_read_boundary_without_submit() -> None:
    """TST-REQ-VEN-004-03: Validates REQ-VEN-004

    Given: dry-run mode is enabled and Polymarket is configured
    When: market reads execute through the adapter boundary
    Then: approved read APIs are used and no live order submit is attempted
    """
    client = PolymarketContractClient(
        PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=False,
            client_boundary=PolymarketClientBoundary.DOCUMENTED_HTTP_API,
            base_url="https://clob.polymarket.com",
        )
    )

    result = client.read_markets(snapshot_type="incremental")

    assert result.ok
    assert result.payload["operation"] == "read_markets"
    assert result.payload["snapshot_type"] == "incremental"
    assert result.payload["client_boundary"] == PolymarketClientBoundary.DOCUMENTED_HTTP_API.value
    assert result.payload["live_submit_attempted"] is False
    assert client.read_attempts == 1
    assert client.submit_attempts == 0


def test_req_ven_004_04_polymarket_us_order_payload_maps_to_official_sdk_shape() -> None:
    """TST-REQ-VEN-004-04: Validates REQ-VEN-004

    Given: a validated Polymarket US limit order request
    When: the adapter builds an SDK payload
    Then: the payload uses the official SDK field names and amount objects
    """
    result = build_polymarket_order_payload(
        PolymarketLiveOrderRequest(
            market_slug="will-fed-cut",
            intent="ORDER_INTENT_BUY_LONG",
            order_type=OrderType.LIMIT,
            price="0.55",
            quantity="2",
            tif="TIME_IN_FORCE_GOOD_TILL_CANCEL",
        )
    )

    assert result.ok
    payload = result.payload["order_payload"]
    assert payload["marketSlug"] == "will-fed-cut"
    assert payload["intent"] == "ORDER_INTENT_BUY_LONG"
    assert payload["type"] == "ORDER_TYPE_LIMIT"
    assert payload["price"] == {"value": "0.55", "currency": "USD"}
    assert payload["quantity"] == 2
    assert payload["manualOrderIndicator"] == "MANUAL_ORDER_INDICATOR_AUTOMATIC"


def test_req_ven_004_05_polymarket_us_sdk_live_adapter_submits_order_through_official_sdk() -> None:
    """TST-REQ-VEN-004-05: Validates REQ-VEN-004

    Given: live mode, credentials, and a fake official SDK client
    When: execution submits a Polymarket US order
    Then: the adapter calls `orders.create` and returns only safe metadata
    """
    sdk = FakePolymarketSdkClient()
    adapter = PolymarketLiveOrderAdapter(
        config=PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=True,
            client_boundary=PolymarketClientBoundary.OFFICIAL_SDK,
            base_url=POLYMARKET_US_API_BASE_URL,
            credential_ref="/codex-poly-bot/production/polymarket/secret-key",
        ),
        credentials=PolymarketApiCredentials(key_id="pm-key", secret_key="pm-secret"),
        client_factory=lambda: sdk,
    )

    result = adapter.submit_order(
        PolymarketLiveOrderRequest(
            market_slug="will-fed-cut",
            intent="ORDER_INTENT_BUY_LONG",
            order_type=OrderType.LIMIT,
            price="0.55",
            quantity="2",
        )
    )

    assert result.ok
    assert sdk.orders.create_calls[0]["marketSlug"] == "will-fed-cut"
    assert sdk.orders.create_calls[0]["price"] == {"value": "0.55", "currency": "USD"}
    assert sdk.orders.preview_calls == []
    assert sdk.closed is True
    assert result.payload["operation"] == "submit_order"
    assert result.payload["venue_order_id"] == "pm-order-1"
    assert "pm-secret" not in str(result.payload)


def test_req_ven_004_06_polymarket_us_sdk_preview_does_not_create_live_order() -> None:
    """TST-REQ-VEN-004-06: Validates REQ-VEN-004

    Given: a Polymarket US adapter and live order request
    When: preview is requested
    Then: the adapter calls `orders.preview` and does not create an order
    """
    sdk = FakePolymarketSdkClient()
    adapter = PolymarketLiveOrderAdapter(
        config=PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=True,
            client_boundary=PolymarketClientBoundary.OFFICIAL_SDK,
            base_url=POLYMARKET_US_API_BASE_URL,
            credential_ref="/codex-poly-bot/production/polymarket/secret-key",
        ),
        credentials=PolymarketApiCredentials(key_id="pm-key", secret_key="pm-secret"),
        client_factory=lambda: sdk,
    )

    result = adapter.preview_order(
        PolymarketLiveOrderRequest(
            market_slug="will-fed-cut",
            intent="ORDER_INTENT_BUY_LONG",
            order_type=OrderType.LIMIT,
            price="0.55",
            quantity="2",
        )
    )

    assert result.ok
    assert sdk.orders.create_calls == []
    assert sdk.orders.preview_calls[0]["request"]["marketSlug"] == "will-fed-cut"
    assert result.payload["operation"] == "preview_order"


def test_req_ven_004_09_polymarket_us_sdk_close_position_uses_official_sdk() -> None:
    """TST-REQ-VEN-004-09: Validates REQ-VEN-004 and REQ-EXT-006

    Given: a Polymarket US adapter with credentials
    When: a live exit closes a position
    Then: the official SDK close-position operation is used
    """
    sdk = FakePolymarketSdkClient()
    adapter = PolymarketLiveOrderAdapter(
        config=PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=True,
            client_boundary=PolymarketClientBoundary.OFFICIAL_SDK,
            base_url=POLYMARKET_US_API_BASE_URL,
            credential_ref="/codex-poly-bot/production/polymarket/secret-key",
        ),
        credentials=PolymarketApiCredentials(key_id="pm-key", secret_key="pm-secret"),
        client_factory=lambda: sdk,
    )

    result = adapter.close_position(
        market_slug="will-fed-cut",
        current_price="0.50",
        slippage_tolerance_bips=200,
    )

    assert result.ok
    assert sdk.orders.close_position_calls[0]["marketSlug"] == "will-fed-cut"
    assert sdk.orders.close_position_calls[0]["slippageTolerance"]["currentPrice"] == {
        "value": "0.50",
        "currency": "USD",
    }
    assert sdk.orders.close_position_calls[0]["slippageTolerance"]["bips"] == 200
    assert result.payload["operation"] == "close_position"
    assert result.payload["venue_order_id"] == "pm-close-1"


def test_req_ven_004_07_missing_polymarket_secret_blocks_before_sdk_call() -> None:
    """TST-REQ-VEN-004-07: Validates REQ-VEN-004

    Given: a live adapter with missing API secret
    When: submission is attempted
    Then: the adapter refuses before creating an SDK client
    """
    factory_called = False

    def client_factory() -> FakePolymarketSdkClient:
        nonlocal factory_called
        factory_called = True
        return FakePolymarketSdkClient()

    adapter = PolymarketLiveOrderAdapter(
        config=PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=True,
            client_boundary=PolymarketClientBoundary.OFFICIAL_SDK,
            base_url=POLYMARKET_US_API_BASE_URL,
            credential_ref="/codex-poly-bot/production/polymarket/secret-key",
        ),
        credentials=PolymarketApiCredentials(key_id="pm-key", secret_key=""),
        client_factory=client_factory,
    )

    result = adapter.submit_order(
        PolymarketLiveOrderRequest(
            market_slug="will-fed-cut",
            intent="ORDER_INTENT_BUY_LONG",
            order_type=OrderType.LIMIT,
            price="0.55",
            quantity="2",
        )
    )

    assert not result.ok
    assert "missing Polymarket secret key" in result.refusal_reasons
    assert factory_called is False


def test_req_ven_004_08_execution_service_routes_polymarket_live_orders_to_adapter() -> None:
    """TST-REQ-VEN-004-08: Validates REQ-VEN-004

    Given: a risk-approved Polymarket live execution request
    When: execution runs in live mode
    Then: the service submits through the configured adapter boundary
    """

    class Submitter:
        def __init__(self) -> None:
            self.calls: list[PolymarketLiveOrderRequest] = []

        def submit_order(self, request: PolymarketLiveOrderRequest):
            self.calls.append(request)
            return type(
                "Result",
                (),
                {
                    "ok": True,
                    "payload": {"venue_order_id": "pm-order-1"},
                    "refusal_reason": None,
                },
            )()

    order = PolymarketLiveOrderRequest(
        market_slug="will-fed-cut",
        intent="ORDER_INTENT_BUY_LONG",
        order_type=OrderType.LIMIT,
        price="0.55",
        quantity="2",
    )
    submitter = Submitter()

    result = execute_polymarket_order(
        PolymarketExecutionRequest(
            global_execution_mode="live",
            risk_approved=True,
            order=order,
        ),
        submitter=submitter,
    )

    assert result.status == "submitted"
    assert result.broker_submitted is True
    assert submitter.calls == [order]

def test_req_ven_005_01_unsupported_venue_configuration_environment_live_order_checks_run() -> None:
    """TST-REQ-VEN-005-01: Validates REQ-VEN-005

    Given: an unsupported venue configuration for the environment
    When: live order checks run
    Then: live orders are blocked and the refusal reason is persisted
    """
    result = validate_polymarket_config(
        PolymarketVenueConfig(
            venue=Venue.ALPACA,
            enabled=True,
            live_enabled=True,
            client_boundary=PolymarketClientBoundary.DOCUMENTED_HTTP_API,
            base_url="https://clob.polymarket.com",
            credential_ref="/codex-poly-bot/development/polymarket/openai/wallet",
        )
    )

    assert not result.ok
    assert result.payload["venue"] == Venue.ALPACA.value
    assert "unsupported Polymarket venue" in result.refusal_reasons

def test_req_ven_005_03_unsupported_polymarket_config_blocks_live_eligibility_and_persists_refusal() -> None:
    """TST-REQ-VEN-005-03: Validates REQ-VEN-005

    Given: unsupported Polymarket venue configuration for the current environment
    When: live eligibility checks run
    Then: live orders are blocked and the refusal reason is persisted
    """
    registry = RepositoryRegistry()
    config = PolymarketVenueConfig(
        venue=Venue.POLYMARKET_US,
        enabled=True,
        live_enabled=True,
        client_boundary=PolymarketClientBoundary.UNAPPROVED,
        base_url="https://clob.polymarket.com",
        credential_ref="/codex-poly-bot/development/polymarket/openai/wallet",
        jurisdiction_supported=False,
    )

    result = polymarket_live_eligibility_gate(
        config=config,
        environment=Environment.DEVELOPMENT,
        registry=registry,
    )

    assert not result.ok
    assert result.payload["live_order_allowed"] is False
    assert "unsupported jurisdiction" in result.refusal_reasons
    assert "unapproved Polymarket client boundary" in result.refusal_reasons
    audit_row = registry.state.rows("shared.audit_events")[0]
    assert audit_row["event_type"] == "polymarket_live_refusal"
    assert audit_row["success"] is False
    assert audit_row["metadata"]["venue"] == Venue.POLYMARKET_US.value
    assert audit_row["metadata"]["refusal_reasons"] == [
        "unsupported jurisdiction",
        "unapproved Polymarket client boundary",
    ]

def test_req_ven_005_02_multiple_unsupported_venue_fields_validation_runs_refusal_event() -> None:
    """TST-REQ-VEN-005-02: Validates REQ-VEN-005

    Given: multiple unsupported venue fields
    When: validation runs
    Then: the refusal event includes each relevant unsupported setting
    """
    result = validate_polymarket_config(
        PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=True,
            client_boundary=PolymarketClientBoundary.UNAPPROVED,
            base_url="",
            credential_ref=None,
            jurisdiction_supported=False,
            stale_threshold_seconds=0,
        )
    )

    assert not result.ok
    assert set(result.refusal_reasons) == {
        "missing Polymarket base URL",
        "missing Polymarket credential reference",
        "unsupported jurisdiction",
        "invalid stale data threshold",
        "unapproved Polymarket client boundary",
    }
    assert allowed_when_venue_disabled(VenueOperation.CANCEL_ORDER, known_open_order=True)
    assert not allowed_when_venue_disabled(VenueOperation.SUBMIT_ORDER, known_open_order=True)

def test_req_dat_005_03_stale_polymarket_market_data_blocks_live_order_and_persists_refusal() -> None:
    """TST-REQ-DAT-005-03: Validates REQ-DAT-005

    Given: Polymarket market data is stale beyond the configured threshold
    When: live order checks run
    Then: dependent live orders are blocked and the refusal event is persisted
    """
    registry = RepositoryRegistry()
    config = PolymarketVenueConfig(
        venue=Venue.POLYMARKET_US,
        enabled=True,
        live_enabled=True,
        client_boundary=PolymarketClientBoundary.DOCUMENTED_HTTP_API,
        base_url="https://clob.polymarket.com",
        credential_ref="/codex-poly-bot/development/polymarket/openai/wallet",
        stale_threshold_seconds=60,
    )

    result = polymarket_market_data_live_gate(
        config=config,
        environment=Environment.DEVELOPMENT,
        registry=registry,
        market_id="market-2026-fed",
        observed_at=datetime(2026, 5, 10, 5, 58, 59, tzinfo=UTC),
        now=datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
    )

    assert not result.ok
    assert result.refusal_reasons == ("STALE_MARKET_DATA",)
    assert result.payload["live_order_allowed"] is False
    assert result.payload["age_seconds"] == 61
    audit_row = registry.state.rows("shared.audit_events")[0]
    assert audit_row["event_type"] == "polymarket_live_refusal"
    assert audit_row["entity_id"] == "market-2026-fed"
    assert audit_row["metadata"]["refusal_reasons"] == ["STALE_MARKET_DATA"]
    assert audit_row["metadata"]["age_seconds"] == 61

def test_req_ven_006_01_authorized_dashboard_update_venue_config_next_trading_loop() -> None:
    """TST-REQ-VEN-006-01: Validates REQ-VEN-006

    Given: an authorized dashboard update to venue config
    When: the next trading loop starts
    Then: the updated venue config is applied without restart
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)

    service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=auth.authorize_request(auth.create_session_token(username="yaw")),
        environment=Environment.DEVELOPMENT,
        expected_version=None,
        version="v1",
        patches=[ConfigPatchOperation("replace", "venues.polymarket_us.enabled", True)],
    )
    snapshot = service.config_for_next_loop(Environment.DEVELOPMENT)

    assert snapshot.snapshot.payload["venues"]["polymarket_us"]["enabled"] is True
