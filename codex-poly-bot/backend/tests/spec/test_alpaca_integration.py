"""Red-phase tests for Alpaca Stock and ETF Integration."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.spec.helpers import pending
from app.bootstrap import configured_slippage_threshold, market_order_slippage_allowed
from app.db import AlpacaReconciliationSnapshot, RepositoryRegistry
from app.domain import (
    Environment,
    Instrument,
    InstrumentType,
    ModelProvider,
    OrderSide,
    Venue,
    eligible_alpaca_instruments,
    supported_venues,
)
from app.services import (
    ActorContext,
    AuthService,
    ConfigAuthorizationError,
    ConfigPatchOperation,
    ConfigService,
    ConfigValidationError,
    AlpacaRiskInput,
    evaluate_alpaca_risk_limits,
)
from app.venues import (
    AlpacaAccountCredential,
    AlpacaClientBoundary,
    AlpacaContractClient,
    AlpacaMarketDataStatus,
    AlpacaOrderIntent,
    AlpacaVenueConfig,
    validate_alpaca_account_identifiers,
    validate_alpaca_long_only_order,
    validate_alpaca_market_data,
)


def test_req_alp_001_01_alpaca_configured_enabled_venue_adapters_registered_alpaca_available() -> None:
    """TST-REQ-ALP-001-01: Validates REQ-ALP-001

    Given: Alpaca is configured and enabled
    When: venue adapters are registered
    Then: Alpaca is available for stocks and ETFs
    """
    assert Venue.ALPACA in supported_venues()

    instrument = Instrument(
        venue=Venue.ALPACA,
        instrument_type=InstrumentType.STOCK,
        symbol="SPY",
        display_name="SPDR S&P 500 ETF",
    )
    assert instrument.identifier == "SPY"

def test_req_alp_001_02_alpaca_not_enabled_trading_loop_evaluates_stock_etf() -> None:
    """TST-REQ-ALP-001-02: Validates REQ-ALP-001

    Given: Alpaca is not enabled
    When: the trading loop evaluates stock or ETF candidates
    Then: Alpaca scan and execution are skipped
    """
    polymarket = Instrument(
        venue=Venue.POLYMARKET_US,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        market_id="market-1",
        outcome_id="yes",
        display_name="Will it rain?",
    )

    assert eligible_alpaca_instruments([polymarket]) == []

def test_req_alp_002_01_stock_etf_candidates_alpaca_filtering_runs_only_stocks() -> None:
    """TST-REQ-ALP-002-01: Validates REQ-ALP-002

    Given: stock and ETF candidates
    When: Alpaca filtering runs
    Then: only stocks and ETFs remain eligible
    """
    stock = Instrument(
        venue=Venue.ALPACA,
        instrument_type=InstrumentType.STOCK,
        symbol="AAPL",
        display_name="Apple",
    )
    etf = Instrument(
        venue=Venue.ALPACA,
        instrument_type=InstrumentType.ETF,
        symbol="VTI",
        display_name="Vanguard Total Stock Market ETF",
    )

    assert eligible_alpaca_instruments([stock, etf]) == [stock, etf]

def test_req_alp_002_02_options_crypto_short_margin_candidates_alpaca_filtering_runs() -> None:
    """TST-REQ-ALP-002-02: Validates REQ-ALP-002

    Given: options, crypto, short, or margin candidates
    When: Alpaca filtering runs
    Then: each unsupported product is rejected with a reason
    """
    with pytest.raises(ValidationError):
        Instrument(
            venue=Venue.ALPACA,
            instrument_type=InstrumentType.PREDICTION_MARKET,
            symbol="BTCUSD",
            display_name="Bitcoin",
        )
    with pytest.raises(ValueError):
        InstrumentType("option")
    with pytest.raises(ValidationError):
        Instrument(
            venue=Venue.ALPACA,
            instrument_type=InstrumentType.STOCK,
            symbol="   ",
            display_name="Whitespace Symbol",
        )

def test_req_alp_003_01_alpaca_account_market_data_position_order_operations_adapters() -> None:
    """TST-REQ-ALP-003-01: Validates REQ-ALP-003

    Given: Alpaca account, market data, position, and order operations
    When: adapters execute them
    Then: the official SDK or documented HTTP APIs are used
    """
    client = AlpacaContractClient(
        AlpacaVenueConfig(
            account_mode="paper",
            client_boundary=AlpacaClientBoundary.OFFICIAL_PYTHON_SDK,
        )
    )

    result = client.execute_contract_operations()

    assert result.ok
    assert result.payload["client_boundary"] == AlpacaClientBoundary.OFFICIAL_PYTHON_SDK.value
    assert set(result.payload["operations"]) == {
        "account",
        "market_data",
        "order",
        "position",
    }
    assert client.operation_calls == 4

def test_req_alp_003_02_adapter_without_approved_alpaca_client_binding_live_operations() -> None:
    """TST-REQ-ALP-003-02: Validates REQ-ALP-003

    Given: an adapter without an approved Alpaca client binding
    When: live operations are requested
    Then: the operation is blocked
    """
    client = AlpacaContractClient(
        AlpacaVenueConfig(
            account_mode="live",
            client_boundary=AlpacaClientBoundary.UNAPPROVED,
        )
    )

    result = client.execute_contract_operations()

    assert not result.ok
    assert result.refusal_reason == "unapproved Alpaca client boundary"
    assert client.operation_calls == 0

def test_req_alp_004_01_dev_prod_settings_claude_openai_alpaca_credentials_loaded() -> None:
    """TST-REQ-ALP-004-01: Validates REQ-ALP-004

    Given: dev and prod settings for Claude and OpenAI
    When: Alpaca credentials are loaded
    Then: each environment and model has a distinct account identifier
    """
    result = validate_alpaca_account_identifiers(
        [
            AlpacaAccountCredential(
                environment=Environment.DEVELOPMENT,
                account_mode="paper",
                model_provider=ModelProvider.OPENAI,
                account_id="alpaca-openai-dev-paper",
                credential_ref="/codex-poly-bot/development/alpaca/openai/api-key",
            ),
            AlpacaAccountCredential(
                environment=Environment.DEVELOPMENT,
                account_mode="paper",
                model_provider=ModelProvider.CLAUDE,
                account_id="alpaca-claude-dev-paper",
                credential_ref="/codex-poly-bot/development/alpaca/claude/api-key",
            ),
            AlpacaAccountCredential(
                environment=Environment.PRODUCTION,
                account_mode="live",
                model_provider=ModelProvider.OPENAI,
                account_id="alpaca-openai-prod-live",
                credential_ref="/codex-poly-bot/production/alpaca/openai/api-key",
            ),
            AlpacaAccountCredential(
                environment=Environment.PRODUCTION,
                account_mode="live",
                model_provider=ModelProvider.CLAUDE,
                account_id="alpaca-claude-prod-live",
                credential_ref="/codex-poly-bot/production/alpaca/claude/api-key",
            ),
        ]
    )

    assert result.ok
    assert result.payload["resolved_account_count"] == 4
    assert result.payload["resolved_accounts"]["development:paper:openai"] == "alpaca-openai-dev-paper"
    assert result.payload["resolved_accounts"]["production:live:claude"] == "alpaca-claude-prod-live"
    assert "credential_ref" not in result.payload

def test_req_alp_004_02_missing_alpaca_account_identifier_one_model_provider_live() -> None:
    """TST-REQ-ALP-004-02: Validates REQ-ALP-004

    Given: a missing Alpaca account identifier for one model provider
    When: live checks run
    Then: Alpaca live trading is blocked for that provider
    """
    result = validate_alpaca_account_identifiers(
        [
            AlpacaAccountCredential(
                environment=Environment.PRODUCTION,
                account_mode="live",
                model_provider=ModelProvider.OPENAI,
                account_id="alpaca-openai-prod-live",
                credential_ref="/codex-poly-bot/production/alpaca/openai/api-key",
            ),
            AlpacaAccountCredential(
                environment=Environment.PRODUCTION,
                account_mode="live",
                model_provider=ModelProvider.CLAUDE,
                account_id=None,
                credential_ref="/codex-poly-bot/production/alpaca/claude/api-key",
            ),
        ]
    )

    assert not result.ok
    assert result.refusal_reasons == (
        "missing Alpaca account identifier for production:live:claude",
    )

def test_req_alp_005_01_global_dry_run_mode_enabled_alpaca_stock_etf() -> None:
    """TST-REQ-ALP-005-01: Validates REQ-ALP-005

    Given: global dry-run mode is enabled
    When: an Alpaca stock or ETF order is approved
    Then: a simulated order is recorded without broker submission
    """
    pending("TST-REQ-ALP-005-01", "REQ-ALP-005")

def test_req_alp_005_02_dry_run_mode_mocked_broker_client_execution_runs() -> None:
    """TST-REQ-ALP-005-02: Validates REQ-ALP-005

    Given: dry-run mode and a mocked broker client
    When: execution runs
    Then: no Alpaca paper or live endpoint is called
    """
    pending("TST-REQ-ALP-005-02", "REQ-ALP-005")

def test_req_alp_006_01_dry_run_mode_disabled_alpaca_enabled_risk_checks() -> None:
    """TST-REQ-ALP-006-01: Validates REQ-ALP-006

    Given: dry-run mode is disabled, Alpaca is enabled, and risk checks pass
    When: an order is approved
    Then: it is submitted to the configured Alpaca account mode
    """
    pending("TST-REQ-ALP-006-01", "REQ-ALP-006")

def test_req_alp_006_02_dry_run_mode_disabled_but_risk_check_fails() -> None:
    """TST-REQ-ALP-006-02: Validates REQ-ALP-006

    Given: dry-run mode is disabled but a risk check fails
    When: Alpaca execution is requested
    Then: no order is submitted
    """
    pending("TST-REQ-ALP-006-02", "REQ-ALP-006")

def test_req_alp_007_01_environment_dashboard_config_values_alpaca_account_mode_resolved() -> None:
    """TST-REQ-ALP-007-01: Validates REQ-ALP-007

    Given: environment and dashboard config values
    When: Alpaca account mode is resolved
    Then: paper and live modes are supported values
    """
    pending("TST-REQ-ALP-007-01", "REQ-ALP-007")

def test_req_alp_007_02_invalid_alpaca_account_mode_config_validation_runs_mode() -> None:
    """TST-REQ-ALP-007-02: Validates REQ-ALP-007

    Given: an invalid Alpaca account mode
    When: config validation runs
    Then: the mode is rejected and live trading is blocked
    """
    pending("TST-REQ-ALP-007-02", "REQ-ALP-007")

def test_req_alp_008_01_buy_order_maintains_long_only_position_without_margin() -> None:
    """TST-REQ-ALP-008-01: Validates REQ-ALP-008

    Given: a buy order that maintains a long-only position without margin
    When: Alpaca risk checks run
    Then: the order remains eligible
    """
    result = validate_alpaca_long_only_order(
        AlpacaOrderIntent(
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=Decimal("2"),
            current_position=Decimal("1"),
            estimated_notional=Decimal("250.00"),
            buying_power=Decimal("500.00"),
        )
    )

    assert result.ok
    assert result.payload["projected_position"] == "3"
    assert result.payload["margin_required"] is False

def test_req_alp_008_02_order_would_short_symbol_require_margin_alpaca_risk() -> None:
    """TST-REQ-ALP-008-02: Validates REQ-ALP-008

    Given: an order that would short a symbol or require margin
    When: Alpaca risk checks run
    Then: the order is refused
    """
    short_result = validate_alpaca_long_only_order(
        AlpacaOrderIntent(
            symbol="SPY",
            side=OrderSide.SELL,
            quantity=Decimal("2"),
            current_position=Decimal("1"),
            estimated_notional=Decimal("250.00"),
            buying_power=Decimal("500.00"),
        )
    )
    margin_result = validate_alpaca_long_only_order(
        AlpacaOrderIntent(
            symbol="QQQ",
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            current_position=Decimal("0"),
            estimated_notional=Decimal("1000.00"),
            buying_power=Decimal("100.00"),
        )
    )

    assert not short_result.ok
    assert short_result.refusal_reason == "Alpaca order would create short position"
    assert not margin_result.ok
    assert margin_result.refusal_reason == "Alpaca order would require margin"

def test_req_alp_009_01_default_alpaca_risk_config_stock_etf_order_sized() -> None:
    """TST-REQ-ALP-009-01: Validates REQ-ALP-009

    Given: default Alpaca risk config
    When: a stock or ETF order is sized at 100 USD per symbol and provider
    Then: the order passes the max-position boundary check
    """
    result = evaluate_alpaca_risk_limits(
        AlpacaRiskInput(
            proposed_notional=Decimal("100.00"),
            projected_symbol_exposure=Decimal("100.00"),
            daily_loss=Decimal("0.00"),
            open_positions=0,
            creates_new_position=True,
            model_capital=Decimal("1000.00"),
        )
    )

    assert result.approved
    assert result.payload["max_position_usd"] == "100.00"

def test_req_alp_009_02_default_alpaca_risk_config_stock_etf_order_exceeds() -> None:
    """TST-REQ-ALP-009-02: Validates REQ-ALP-009

    Given: default Alpaca risk config
    When: a stock or ETF order exceeds 100 USD for a symbol and provider
    Then: the order is refused
    """
    result = evaluate_alpaca_risk_limits(
        AlpacaRiskInput(
            proposed_notional=Decimal("100.01"),
            projected_symbol_exposure=Decimal("100.01"),
            daily_loss=Decimal("0.00"),
            open_positions=0,
            creates_new_position=True,
            model_capital=Decimal("1000.00"),
        )
    )

    assert not result.approved
    assert result.refusal_reason == "MAX_POSITION_LIMIT"

def test_req_alp_010_01_default_alpaca_risk_config_daily_loss_equals_100() -> None:
    """TST-REQ-ALP-010-01: Validates REQ-ALP-010

    Given: default Alpaca risk config
    When: daily loss equals 100 USD for a model provider and a new order is evaluated
    Then: the order is refused because max daily loss is reached
    """
    result = evaluate_alpaca_risk_limits(
        AlpacaRiskInput(
            proposed_notional=Decimal("1.00"),
            projected_symbol_exposure=Decimal("1.00"),
            daily_loss=Decimal("100.00"),
            open_positions=0,
            creates_new_position=True,
            model_capital=Decimal("1000.00"),
        )
    )

    assert not result.approved
    assert result.refusal_reason == "DAILY_LOSS_LIMIT"

def test_req_alp_010_02_default_alpaca_risk_config_daily_loss_exceeds_100() -> None:
    """TST-REQ-ALP-010-02: Validates REQ-ALP-010

    Given: default Alpaca risk config
    When: daily loss exceeds 100 USD for a model provider
    Then: additional Alpaca orders are refused
    """
    result = evaluate_alpaca_risk_limits(
        AlpacaRiskInput(
            proposed_notional=Decimal("1.00"),
            projected_symbol_exposure=Decimal("1.00"),
            daily_loss=Decimal("100.01"),
            open_positions=0,
            creates_new_position=True,
            model_capital=Decimal("1000.00"),
        )
    )

    assert not result.approved
    assert result.refusal_reason == "DAILY_LOSS_LIMIT"

def test_req_alp_011_01_default_alpaca_risk_config_4_open_stock_etf() -> None:
    """TST-REQ-ALP-011-01: Validates REQ-ALP-011

    Given: default Alpaca risk config and 4 open stock or ETF positions
    When: an approved order would create the fifth open position
    Then: the order passes the max-open boundary check
    """
    result = evaluate_alpaca_risk_limits(
        AlpacaRiskInput(
            proposed_notional=Decimal("1.00"),
            projected_symbol_exposure=Decimal("1.00"),
            daily_loss=Decimal("0.00"),
            open_positions=4,
            creates_new_position=True,
            model_capital=Decimal("1000.00"),
        )
    )

    assert result.approved
    assert result.payload["projected_open_positions"] == 5

def test_req_alp_011_02_default_alpaca_risk_config_sixth_open_stock_etf() -> None:
    """TST-REQ-ALP-011-02: Validates REQ-ALP-011

    Given: default Alpaca risk config
    When: a sixth open stock or ETF position would be created
    Then: the order is refused
    """
    result = evaluate_alpaca_risk_limits(
        AlpacaRiskInput(
            proposed_notional=Decimal("1.00"),
            projected_symbol_exposure=Decimal("1.00"),
            daily_loss=Decimal("0.00"),
            open_positions=5,
            creates_new_position=True,
            model_capital=Decimal("1000.00"),
        )
    )

    assert not result.approved
    assert result.refusal_reason == "OPEN_POSITION_LIMIT"

def test_req_alp_012_01_default_alpaca_risk_config_symbol_allocation_would_equal() -> None:
    """TST-REQ-ALP-012-01: Validates REQ-ALP-012

    Given: default Alpaca risk config
    When: symbol allocation would equal 10 percent for a model provider
    Then: the order passes the allocation boundary check
    """
    result = evaluate_alpaca_risk_limits(
        AlpacaRiskInput(
            proposed_notional=Decimal("100.00"),
            projected_symbol_exposure=Decimal("100.00"),
            daily_loss=Decimal("0.00"),
            open_positions=0,
            creates_new_position=True,
            model_capital=Decimal("1000.00"),
        )
    )

    assert result.approved
    assert result.payload["max_symbol_allocation_usd"] == "100.0000"

def test_req_alp_012_02_default_alpaca_risk_config_symbol_allocation_would_exceed() -> None:
    """TST-REQ-ALP-012-02: Validates REQ-ALP-012

    Given: default Alpaca risk config
    When: symbol allocation would exceed 10 percent
    Then: the order is refused
    """
    result = evaluate_alpaca_risk_limits(
        AlpacaRiskInput(
            proposed_notional=Decimal("100.01"),
            projected_symbol_exposure=Decimal("100.01"),
            daily_loss=Decimal("0.00"),
            open_positions=0,
            creates_new_position=True,
            model_capital=Decimal("1000.00"),
        )
    )

    assert not result.approved
    assert "ALPACA_ALLOCATION_LIMIT" in result.refusal_reasons

def test_req_alp_013_01_default_alpaca_slippage_config_estimated_market_order_slippage() -> None:
    """TST-REQ-ALP-013-01: Validates REQ-ALP-013

    Given: default Alpaca slippage config
    When: estimated market order slippage is exactly 0.5 percent
    Then: the market order passes the slippage boundary check
    """
    assert configured_slippage_threshold("alpaca") == Decimal("0.005")
    assert market_order_slippage_allowed("alpaca", Decimal("0.005"))

def test_req_alp_013_02_default_alpaca_slippage_config_estimated_market_order_slippage() -> None:
    """TST-REQ-ALP-013-02: Validates REQ-ALP-013

    Given: default Alpaca slippage config
    When: estimated market order slippage exceeds 0.5 percent
    Then: the market order is blocked
    """
    assert not market_order_slippage_allowed("alpaca", Decimal("0.0051"))

def test_req_alp_014_01_authorized_dashboard_user_alpaca_mode_enabled_flag_risk() -> None:
    """TST-REQ-ALP-014-01: Validates REQ-ALP-014

    Given: an authorized dashboard user
    When: Alpaca mode, enabled flag, risk limits, universe, or slippage is saved
    Then: the config is persisted
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)
    result = service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=auth.authorize_request(auth.create_session_token(username="yaw")),
        environment=Environment.DEVELOPMENT,
        expected_version=None,
        version="v1",
        patches=[
            ConfigPatchOperation("replace", "alpaca.account_mode", "paper"),
            ConfigPatchOperation("replace", "venues.alpaca.enabled", True),
            ConfigPatchOperation("replace", "risk.alpaca.max_position_usd", "150.00"),
            ConfigPatchOperation("replace", "risk.alpaca.max_daily_loss_usd", "125.00"),
            ConfigPatchOperation("replace", "risk.alpaca.max_open_positions", 4),
            ConfigPatchOperation("replace", "risk.alpaca.max_portfolio_allocation_per_symbol", "0.08"),
            ConfigPatchOperation("replace", "risk.alpaca.market_order_slippage_threshold", "0.004"),
            ConfigPatchOperation("replace", "alpaca.symbol_universe", ["spy", "qqq"]),
        ],
    )
    payload = result.mutation.config_version["payload"]

    assert payload["alpaca"]["account_mode"] == "paper"
    assert payload["venues"]["alpaca"]["enabled"] is True
    assert payload["risk"]["alpaca"]["max_position_usd"] == "150.00"
    assert payload["risk"]["alpaca"]["max_daily_loss_usd"] == "125.00"
    assert payload["risk"]["alpaca"]["max_open_positions"] == 4
    assert payload["risk"]["alpaca"]["max_portfolio_allocation_per_symbol"] == "0.08"
    assert payload["risk"]["alpaca"]["market_order_slippage_threshold"] == "0.004"
    assert payload["alpaca"]["symbol_universe"] == ["SPY", "QQQ"]

def test_req_alp_014_02_unauthorized_user_invalid_alpaca_config_value_update_submitted() -> None:
    """TST-REQ-ALP-014-02: Validates REQ-ALP-014

    Given: an unauthorized user or invalid Alpaca config value
    When: the update is submitted
    Then: the dashboard rejects the change
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)

    with pytest.raises(ConfigAuthorizationError):
        service.save_config_patches(
            actor=ActorContext(username="not-allowed", ip_address="198.51.100.42"),
            access=auth.authorize_request(auth.create_session_token(username="not-allowed")),
            environment=Environment.DEVELOPMENT,
            expected_version=None,
            version="v1",
            patches=[ConfigPatchOperation("replace", "alpaca.account_mode", "live")],
        )
    with pytest.raises(ConfigValidationError):
        service.save_config_patches(
            actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
            access=auth.authorize_request(auth.create_session_token(username="yaw")),
            environment=Environment.DEVELOPMENT,
            expected_version=None,
            version="v1",
            patches=[ConfigPatchOperation("replace", "alpaca.account_mode", "margin")],
        )

    assert auth.registry.state.rows("shared.config_versions") == []

def test_req_alp_015_01_alpaca_market_data_unavailable_rate_limited_stale_outside() -> None:
    """TST-REQ-ALP-015-01: Validates REQ-ALP-015

    Given: Alpaca market data is unavailable, rate-limited, stale, or outside configured trading hours
    When: live order checks run
    Then: the order is blocked and the reason is recorded
    """
    result = validate_alpaca_market_data(
        AlpacaMarketDataStatus(
            symbol="SPY",
            available=False,
            rate_limited=True,
            stale=True,
            outside_trading_hours=True,
        )
    )

    assert not result.ok
    assert set(result.refusal_reasons) == {
        "Alpaca market data unavailable",
        "Alpaca market data rate limited",
        "Alpaca market data stale",
        "Alpaca market outside trading hours",
    }
    assert result.payload["symbol"] == "SPY"

def test_req_alp_016_01_distinct_alpaca_account_identifiers_each_model_in_same() -> None:
    """TST-REQ-ALP-016-01: Validates REQ-ALP-016

    Given: distinct Alpaca account identifiers for each model in the same environment and mode
    When: duplicate checks run
    Then: Alpaca live trading remains eligible
    """
    registry = RepositoryRegistry()
    shared = registry.shared()

    openai = shared.register_alpaca_account(
        environment=Environment.PRODUCTION,
        account_mode="live",
        model_provider=ModelProvider.OPENAI,
        account_id="alpaca-openai-prod-live",
    )
    claude = shared.register_alpaca_account(
        environment=Environment.PRODUCTION,
        account_mode="live",
        model_provider=ModelProvider.CLAUDE,
        account_id="alpaca-claude-prod-live",
    )

    assert openai.live_trading_allowed
    assert claude.live_trading_allowed
    assert len(registry.state.rows("shared.alpaca_account_registry")) == 2

def test_req_alp_016_02_two_model_providers_resolve_same_alpaca_account_identifier() -> None:
    """TST-REQ-ALP-016-02: Validates REQ-ALP-016

    Given: two model providers resolve to the same Alpaca account identifier in the same environment and mode
    When: checks run
    Then: live trading is blocked for the duplicate account
    """
    registry = RepositoryRegistry()
    shared = registry.shared()
    shared.register_alpaca_account(
        environment=Environment.PRODUCTION,
        account_mode="live",
        model_provider=ModelProvider.OPENAI,
        account_id="alpaca-shared-account",
    )

    result = shared.register_alpaca_account(
        environment=Environment.PRODUCTION,
        account_mode="live",
        model_provider=ModelProvider.CLAUDE,
        account_id="alpaca-shared-account",
    )

    assert not result.live_trading_allowed
    assert result.refusal_reason == "duplicate Alpaca account identifier"
    assert len(registry.state.rows("shared.alpaca_account_registry")) == 1
    audit_row = registry.state.rows("shared.audit_events")[0]
    assert audit_row["event_type"] == "alpaca_account_duplicate"
    assert audit_row["success"] is False
    assert audit_row["metadata"]["duplicate_model_provider"] == ModelProvider.CLAUDE.value

def test_req_alp_017_01_alpaca_postgres_agree_on_positions_open_orders_buying() -> None:
    """TST-REQ-ALP-017-01: Validates REQ-ALP-017

    Given: Alpaca and Postgres agree on positions, open orders, and buying power
    When: reconciliation runs
    Then: Alpaca live orders may proceed to remaining checks
    """
    repository = RepositoryRegistry().for_model(ModelProvider.OPENAI)
    snapshot = AlpacaReconciliationSnapshot(
        account_id="alpaca-openai-prod-live",
        environment=Environment.PRODUCTION,
        model_provider=ModelProvider.OPENAI,
        account_mode="live",
        configured_account_id="alpaca-openai-prod-live",
        broker_account_id="alpaca-openai-prod-live",
        account_status="active",
        positions={"SPY": Decimal("2")},
        open_orders=("order-1",),
        buying_power=Decimal("500.00"),
        freshness_seconds=30,
    )

    repository.record_alpaca_account_snapshot(
        environment=Environment.PRODUCTION,
        account_mode="live",
        snapshot=snapshot,
    )
    result = repository.reconcile_alpaca_state(snapshot, snapshot)

    assert result.live_order_allowed
    assert result.mismatch_reason is None
    snapshot_row = repository.state.rows("openai.alpaca_account_snapshots")[0]
    assert snapshot_row["configured_account_id"] == "alpaca-openai-prod-live"
    assert snapshot_row["broker_account_id"] == "alpaca-openai-prod-live"
    assert snapshot_row["account_status"] == "active"
    assert snapshot_row["freshness_seconds"] == 30
    assert snapshot_row["is_live_safe"] is True

def test_req_alp_017_02_reconciliation_not_completed_alpaca_live_execution_requested_order() -> None:
    """TST-REQ-ALP-017-02: Validates REQ-ALP-017

    Given: reconciliation has not completed
    When: Alpaca live execution is requested
    Then: the order is blocked
    """
    registry = RepositoryRegistry()
    repository = registry.for_model(ModelProvider.OPENAI)
    snapshot = AlpacaReconciliationSnapshot(
        account_id="alpaca-openai-prod-live",
        environment=Environment.PRODUCTION,
        model_provider=ModelProvider.OPENAI,
        account_mode="live",
        positions={},
        open_orders=(),
        buying_power=Decimal("500.00"),
        completed=False,
    )

    result = repository.reconcile_alpaca_state(snapshot, snapshot)

    assert not result.live_order_allowed
    assert result.mismatch_reason == "reconciliation incomplete"
    mismatch_row = registry.state.rows("openai.alpaca_reconciliation_mismatches")[0]
    assert mismatch_row["mismatch_reason"] == "reconciliation incomplete"

def test_req_alp_018_01_reconciliation_detects_no_unresolved_mismatch_alpaca_live_checks() -> None:
    """TST-REQ-ALP-018-01: Validates REQ-ALP-018

    Given: reconciliation detects no unresolved mismatch
    When: Alpaca live checks run
    Then: the mismatch gate passes
    """
    repository = RepositoryRegistry().for_model(ModelProvider.CLAUDE)
    broker_snapshot = AlpacaReconciliationSnapshot(
        account_id="alpaca-claude-dev-paper",
        environment=Environment.DEVELOPMENT,
        model_provider=ModelProvider.CLAUDE,
        account_mode="paper",
        configured_account_id="alpaca-claude-dev-paper",
        broker_account_id="alpaca-claude-dev-paper",
        account_status="active",
        positions={"VTI": Decimal("1.25")},
        open_orders=(),
        buying_power=Decimal("250.00"),
    )
    postgres_snapshot = AlpacaReconciliationSnapshot(
        account_id="alpaca-claude-dev-paper",
        environment=Environment.DEVELOPMENT,
        model_provider=ModelProvider.CLAUDE,
        account_mode="paper",
        configured_account_id="alpaca-claude-dev-paper",
        broker_account_id="alpaca-claude-dev-paper",
        account_status="active",
        positions={"VTI": Decimal("1.25")},
        open_orders=(),
        buying_power=Decimal("250.00"),
    )

    result = repository.reconcile_alpaca_state(broker_snapshot, postgres_snapshot)

    assert result.live_order_allowed
    assert result.mismatch_details is None

def test_req_alp_018_02_unresolved_broker_postgres_mismatch_alpaca_live_checks_run() -> None:
    """TST-REQ-ALP-018-02: Validates REQ-ALP-018

    Given: an unresolved broker and Postgres mismatch
    When: Alpaca live checks run
    Then: live orders are blocked for the affected provider and mismatch details are recorded
    """
    registry = RepositoryRegistry()
    repository = registry.for_model(ModelProvider.CLAUDE)
    broker_snapshot = AlpacaReconciliationSnapshot(
        account_id="alpaca-claude-dev-paper",
        environment=Environment.DEVELOPMENT,
        model_provider=ModelProvider.CLAUDE,
        account_mode="paper",
        configured_account_id="alpaca-claude-dev-paper",
        broker_account_id="unexpected-broker-account",
        account_status="restricted",
        positions={"VTI": Decimal("1.25")},
        open_orders=("broker-order",),
        buying_power=Decimal("250.00"),
        freshness_seconds=500,
        is_live_safe=False,
    )
    postgres_snapshot = AlpacaReconciliationSnapshot(
        account_id="alpaca-claude-dev-paper",
        environment=Environment.DEVELOPMENT,
        model_provider=ModelProvider.CLAUDE,
        account_mode="paper",
        configured_account_id="alpaca-claude-dev-paper",
        broker_account_id="alpaca-claude-dev-paper",
        account_status="active",
        positions={"VTI": Decimal("1.00")},
        open_orders=(),
        buying_power=Decimal("240.00"),
    )

    result = repository.reconcile_alpaca_state(broker_snapshot, postgres_snapshot)

    assert not result.live_order_allowed
    assert result.mismatch_reason == "broker and Postgres state mismatch"
    assert result.mismatch_details is not None
    assert set(result.mismatch_details) == {
        "account_id",
        "account_status",
        "buying_power",
        "freshness_seconds",
        "is_live_safe",
        "open_orders",
        "positions",
    }
    mismatch_row = registry.state.rows("claude.alpaca_reconciliation_mismatches")[0]
    assert mismatch_row["mismatch_reason"] == "broker and Postgres state mismatch"
    assert mismatch_row["mismatch_details"]["account_status"] == "restricted"
