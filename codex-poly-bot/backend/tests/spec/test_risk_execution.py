"""Red-phase tests for Risk and Execution Engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.spec.helpers import pending
from app.bootstrap import (
    configured_slippage_threshold,
    load_runtime_defaults,
    market_order_slippage_allowed,
    safe_defaults,
    with_slippage_threshold,
)
from app.domain import (
    ModelProvider,
    OrderEvent,
    OrderEventType,
    Venue,
    kelly_sized_notional,
    record_order_event,
)


def test_req_exe_001_01_no_explicit_live_trading_override_environment_config_loaded() -> None:
    """TST-REQ-EXE-001-01: Validates REQ-EXE-001

    Given: no explicit live trading override
    When: environment config is loaded
    Then: `LIVE_ENABLED=false` in all environments
    """
    defaults = load_runtime_defaults()

    assert defaults.live_enabled is False
    assert defaults.global_execution_mode == "dry_run"

def test_req_exe_001_02_explicit_live_trading_override_absent_invalid_config_validation() -> None:
    """TST-REQ-EXE-001-02: Validates REQ-EXE-001

    Given: an explicit live trading override is absent or invalid
    When: config validation runs
    Then: live trading remains disabled
    """
    assert load_runtime_defaults(live_enabled=None).live_enabled is False
    assert load_runtime_defaults(live_enabled="not-a-bool").live_enabled is False

def test_req_exe_002_01_dry_run_mode_enabled_order_approved_simulated_order() -> None:
    """TST-REQ-EXE-002-01: Validates REQ-EXE-002

    Given: dry-run mode is enabled
    When: an order is approved
    Then: a simulated order is recorded
    """
    pending("TST-REQ-EXE-002-01", "REQ-EXE-002")

def test_req_exe_002_02_dry_run_mode_enabled_venue_client_mock_attached() -> None:
    """TST-REQ-EXE-002-02: Validates REQ-EXE-002

    Given: dry-run mode is enabled and a venue client mock is attached
    When: execution runs
    Then: no venue submission method is called
    """
    pending("TST-REQ-EXE-002-02", "REQ-EXE-002")

def test_req_exe_003_01_authorized_dashboard_user_toggles_dry_run_live_next() -> None:
    """TST-REQ-EXE-003-01: Validates REQ-EXE-003

    Given: an authorized dashboard user toggles dry-run to live
    When: the next trading loop starts
    Then: live mode config is applied
    """
    pending("TST-REQ-EXE-003-01", "REQ-EXE-003")

def test_req_exe_003_02_unauthorized_user_attempts_toggle_dry_run_live_dashboard() -> None:
    """TST-REQ-EXE-003-02: Validates REQ-EXE-003

    Given: an unauthorized user attempts to toggle dry-run to live
    When: the dashboard request is processed
    Then: the change is rejected
    """
    pending("TST-REQ-EXE-003-02", "REQ-EXE-003")

def test_req_exe_004_01_default_polymarket_risk_config_order_size_exactly_25() -> None:
    """TST-REQ-EXE-004-01: Validates REQ-EXE-004

    Given: default Polymarket risk config
    When: an order size is exactly 25 USD
    Then: the order passes the max-position boundary check
    """
    pending("TST-REQ-EXE-004-01", "REQ-EXE-004")

def test_req_exe_004_02_default_polymarket_risk_config_order_size_exceeds_25() -> None:
    """TST-REQ-EXE-004-02: Validates REQ-EXE-004

    Given: default Polymarket risk config
    When: an order size exceeds 25 USD
    Then: the order is refused
    """
    pending("TST-REQ-EXE-004-02", "REQ-EXE-004")

def test_req_exe_005_01_default_polymarket_risk_config_daily_loss_equals_50() -> None:
    """TST-REQ-EXE-005-01: Validates REQ-EXE-005

    Given: default Polymarket risk config
    When: daily loss equals 50 USD for a model provider and a new order is evaluated
    Then: the order is refused because max daily loss is reached
    """
    pending("TST-REQ-EXE-005-01", "REQ-EXE-005")

def test_req_exe_005_02_default_polymarket_risk_config_daily_loss_exceeds_50() -> None:
    """TST-REQ-EXE-005-02: Validates REQ-EXE-005

    Given: default Polymarket risk config
    When: daily loss exceeds 50 USD for a model provider
    Then: additional orders are refused
    """
    pending("TST-REQ-EXE-005-02", "REQ-EXE-005")

def test_req_exe_006_01_default_polymarket_risk_config_4_open_positions_approved() -> None:
    """TST-REQ-EXE-006-01: Validates REQ-EXE-006

    Given: default Polymarket risk config and 4 open positions
    When: an approved order would create the fifth open position
    Then: the order passes the max-open boundary check
    """
    pending("TST-REQ-EXE-006-01", "REQ-EXE-006")

def test_req_exe_006_02_default_polymarket_risk_config_sixth_open_position_would() -> None:
    """TST-REQ-EXE-006-02: Validates REQ-EXE-006

    Given: default Polymarket risk config
    When: a sixth open position would be created
    Then: the order is refused
    """
    pending("TST-REQ-EXE-006-02", "REQ-EXE-006")

def test_req_exe_007_01_authorized_dashboard_user_updates_max_position_daily_loss() -> None:
    """TST-REQ-EXE-007-01: Validates REQ-EXE-007

    Given: an authorized dashboard user updates max position, daily loss, or open positions
    When: config is saved
    Then: risk limits are persisted
    """
    pending("TST-REQ-EXE-007-01", "REQ-EXE-007")

def test_req_exe_007_02_invalid_risk_limit_values_dashboard_config_saved_validation() -> None:
    """TST-REQ-EXE-007-02: Validates REQ-EXE-007

    Given: invalid risk limit values
    When: dashboard config is saved
    Then: validation rejects the values
    """
    pending("TST-REQ-EXE-007-02", "REQ-EXE-007")

def test_req_exe_008_01_positive_kelly_result_above_configured_risk_cap_sizing() -> None:
    """TST-REQ-EXE-008-01: Validates REQ-EXE-008

    Given: a positive Kelly result above a configured risk cap
    When: sizing runs
    Then: final size is capped by the risk limit
    """
    decision = kelly_sized_notional(
        probability=Decimal("0.60"),
        decimal_odds=Decimal("2.20"),
        bankroll=Decimal("1000"),
        risk_cap=Decimal("25"),
    )

    assert decision.approved
    assert decision.approved_notional == Decimal("25")

def test_req_exe_008_02_missing_probability_odds_bankroll_inputs_kelly_sizing_runs() -> None:
    """TST-REQ-EXE-008-02: Validates REQ-EXE-008

    Given: missing probability, odds, or bankroll inputs
    When: Kelly sizing runs
    Then: sizing fails safely and no order is created
    """
    decision = kelly_sized_notional(
        probability=None,
        decimal_odds=Decimal("2.20"),
        bankroll=Decimal("1000"),
        risk_cap=Decimal("25"),
    )

    assert not decision.approved
    assert decision.refusal_reason == "missing Kelly sizing input"

def test_req_exe_009_01_kelly_calculation_returns_positive_size_execution_checks_run() -> None:
    """TST-REQ-EXE-009-01: Validates REQ-EXE-009

    Given: Kelly calculation returns a positive size
    When: execution checks run
    Then: the non-positive-size refusal gate passes
    """
    pending("TST-REQ-EXE-009-01", "REQ-EXE-009")

def test_req_exe_009_02_kelly_calculation_returns_zero_negative_size_execution_checks() -> None:
    """TST-REQ-EXE-009-02: Validates REQ-EXE-009

    Given: Kelly calculation returns zero or negative size
    When: execution checks run
    Then: the trade is refused
    """
    pending("TST-REQ-EXE-009-02", "REQ-EXE-009")

def test_req_exe_010_01_approved_limit_market_order_decisions_execution_routes_orders() -> None:
    """TST-REQ-EXE-010-01: Validates REQ-EXE-010

    Given: approved limit and market order decisions
    When: execution routes orders
    Then: both order types are supported
    """
    pending("TST-REQ-EXE-010-01", "REQ-EXE-010")

def test_req_exe_010_02_unsupported_order_type_execution_routes_order_order_rejected() -> None:
    """TST-REQ-EXE-010-02: Validates REQ-EXE-010

    Given: an unsupported order type
    When: execution routes the order
    Then: the order is rejected
    """
    pending("TST-REQ-EXE-010-02", "REQ-EXE-010")

def test_req_exe_011_01_market_order_estimated_slippage_below_threshold_execution_checks() -> None:
    """TST-REQ-EXE-011-01: Validates REQ-EXE-011

    Given: a market order with estimated slippage at or below threshold
    When: execution checks run
    Then: the slippage gate passes
    """
    pending("TST-REQ-EXE-011-01", "REQ-EXE-011")

def test_req_exe_011_02_market_order_estimated_slippage_above_threshold_execution_checks() -> None:
    """TST-REQ-EXE-011-02: Validates REQ-EXE-011

    Given: a market order with estimated slippage above threshold
    When: execution checks run
    Then: the market order is blocked
    """
    pending("TST-REQ-EXE-011-02", "REQ-EXE-011")

def test_req_exe_012_01_default_polymarket_config_market_order_slippage_threshold_loaded() -> None:
    """TST-REQ-EXE-012-01: Validates REQ-EXE-012

    Given: default Polymarket config
    When: market order slippage threshold is loaded
    Then: it equals 2 percent
    """
    assert configured_slippage_threshold("polymarket_us") == Decimal("0.02")
    assert market_order_slippage_allowed("polymarket_us", Decimal("0.02"))
    assert not market_order_slippage_allowed("polymarket_us", Decimal("0.0201"))

def test_req_exe_012_02_dashboard_override_slippage_threshold_config_loaded_override_replaces() -> None:
    """TST-REQ-EXE-012-02: Validates REQ-EXE-012

    Given: a dashboard override for slippage threshold
    When: config is loaded
    Then: the override replaces the 2 percent default only after validation
    """
    overridden = with_slippage_threshold(safe_defaults(), "polymarket_us", "0.015")

    assert configured_slippage_threshold("polymarket_us", overridden) == Decimal("0.015")
    with pytest.raises(ValueError):
        with_slippage_threshold(safe_defaults(), "polymarket_us", "-0.01")

def test_req_exe_013_01_all_live_order_gates_pass_live_order_placement() -> None:
    """TST-REQ-EXE-013-01: Validates REQ-EXE-013

    Given: all live-order gates pass
    When: live order placement is requested
    Then: the order may proceed to venue submission
    """
    pending("TST-REQ-EXE-013-01", "REQ-EXE-013")

def test_req_exe_013_02_any_configured_refusal_reason_present_live_order_placement() -> None:
    """TST-REQ-EXE-013-02: Validates REQ-EXE-013

    Given: any configured refusal reason is present
    When: live order placement is requested
    Then: the order is refused and the reason is persisted
    """
    pending("TST-REQ-EXE-013-02", "REQ-EXE-013")

def test_req_exe_014_01_kill_switch_inactive_live_eligibility_checked_normal_live() -> None:
    """TST-REQ-EXE-014-01: Validates REQ-EXE-014

    Given: the kill switch is inactive
    When: live eligibility is checked
    Then: normal live gates apply
    """
    pending("TST-REQ-EXE-014-01", "REQ-EXE-014")

def test_req_exe_014_02_kill_switch_activated_live_eligibility_checked_live_trading() -> None:
    """TST-REQ-EXE-014-02: Validates REQ-EXE-014

    Given: the kill switch is activated
    When: live eligibility is checked
    Then: live trading is disabled for all models and venues
    """
    pending("TST-REQ-EXE-014-02", "REQ-EXE-014")

def test_req_exe_015_01_kill_switch_activation_enabled_live_venues_open_orders() -> None:
    """TST-REQ-EXE-015-01: Validates REQ-EXE-015

    Given: kill switch activation and enabled live venues with open orders
    When: kill switch handling runs
    Then: cancel attempts are issued for open orders
    """
    pending("TST-REQ-EXE-015-01", "REQ-EXE-015")

def test_req_exe_015_02_venue_cancel_attempt_fails_kill_switch_handling_runs() -> None:
    """TST-REQ-EXE-015-02: Validates REQ-EXE-015

    Given: a venue cancel attempt fails
    When: kill switch handling runs
    Then: the failure is recorded and remaining cancel attempts continue
    """
    pending("TST-REQ-EXE-015-02", "REQ-EXE-015")

def test_req_exe_016_01_order_refused_submitted_filled_canceled_failed_event_processed() -> None:
    """TST-REQ-EXE-016-01: Validates REQ-EXE-016

    Given: an order is refused, submitted, filled, canceled, or failed
    When: the event is processed
    Then: it is persisted and visible in dashboard status
    """
    for event_type in OrderEventType:
        event = OrderEvent(
            order_id=f"order-{event_type.value}",
            event_type=event_type,
            venue=Venue.POLYMARKET_US,
            model_provider=ModelProvider.OPENAI,
            message=f"order {event_type.value}",
        )
        result = record_order_event(event, persistence_ok=True)
        assert result.persisted
        assert result.dashboard_visible
        assert not result.degraded

def test_req_exe_016_02_event_persistence_fails_order_event_processed_system_reports() -> None:
    """TST-REQ-EXE-016-02: Validates REQ-EXE-016

    Given: event persistence fails
    When: an order event is processed
    Then: the system reports degraded status and avoids hiding the failure
    """
    event = OrderEvent(
        order_id="order-1",
        event_type=OrderEventType.FAILED,
        venue=Venue.POLYMARKET_US,
        model_provider=ModelProvider.OPENAI,
        message="venue failed",
    )

    result = record_order_event(event, persistence_ok=False)

    assert not result.persisted
    assert result.dashboard_visible
    assert result.degraded
    assert result.error_message == "order event persistence failed"

def test_req_exe_017_01_dry_run_disabled_venue_enabled_account_mode_valid() -> None:
    """TST-REQ-EXE-017-01: Validates REQ-EXE-017

    Given: dry-run is disabled, venue is enabled, account mode is valid, and all checks pass
    When: live execution runs
    Then: live orders are permitted
    """
    pending("TST-REQ-EXE-017-01", "REQ-EXE-017")

def test_req_exe_017_02_dry_run_disabled_but_venue_disabled_account_mode() -> None:
    """TST-REQ-EXE-017-02: Validates REQ-EXE-017

    Given: dry-run is disabled but a venue is disabled or account mode fails checks
    When: live execution runs
    Then: live orders are blocked
    """
    pending("TST-REQ-EXE-017-02", "REQ-EXE-017")
