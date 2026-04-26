"""Red-phase tests for Strategy and Signal Engine."""

from __future__ import annotations

from app.domain import (
    Instrument,
    InstrumentType,
    ModelProvider,
    OrderSide,
    StrategySignal,
    Venue,
    ensure_signals_persisted,
)
from tests.spec.helpers import pending


def prediction_instrument() -> Instrument:
    return Instrument(
        venue=Venue.POLYMARKET_US,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        market_id="market-1",
        outcome_id="yes",
        display_name="Will the event happen?",
    )


def test_req_str_001_01_default_scheduler_config_worker_starts_trading_loop_interval() -> None:
    """TST-REQ-STR-001-01: Validates REQ-STR-001

    Given: default scheduler config
    When: the worker starts
    Then: the trading loop interval is 60 seconds
    """
    pending("TST-REQ-STR-001-01", "REQ-STR-001")

def test_req_str_001_02_scheduler_drift_slow_loop_body_next_loop_scheduled() -> None:
    """TST-REQ-STR-001-02: Validates REQ-STR-001

    Given: scheduler drift or a slow loop body
    When: the next loop is scheduled
    Then: the cadence is measured and logged without overlapping unsafe work
    """
    pending("TST-REQ-STR-001-02", "REQ-STR-001")

def test_req_str_002_01_authorized_dashboard_update_loop_interval_config_saved_new() -> None:
    """TST-REQ-STR-002-01: Validates REQ-STR-002

    Given: an authorized dashboard update to loop interval
    When: config is saved
    Then: the new interval is persisted
    """
    pending("TST-REQ-STR-002-01", "REQ-STR-002")

def test_req_str_002_02_invalid_loop_interval_dashboard_config_saved_validation_rejects() -> None:
    """TST-REQ-STR-002-02: Validates REQ-STR-002

    Given: an invalid loop interval
    When: dashboard config is saved
    Then: validation rejects the value
    """
    pending("TST-REQ-STR-002-02", "REQ-STR-002")

def test_req_str_003_01_enabled_venues_markets_pass_deterministic_filters_trading_loop() -> None:
    """TST-REQ-STR-003-01: Validates REQ-STR-003

    Given: enabled venues and markets that pass deterministic filters
    When: the trading loop runs
    Then: filtered markets are sent to LLM scoring
    """
    pending("TST-REQ-STR-003-01", "REQ-STR-003")

def test_req_str_003_02_markets_fail_deterministic_filters_trading_loop_runs_no() -> None:
    """TST-REQ-STR-003-02: Validates REQ-STR-003

    Given: markets fail deterministic filters
    When: the trading loop runs
    Then: no LLM scoring request is created for them
    """
    pending("TST-REQ-STR-003-02", "REQ-STR-003")

def test_req_str_004_01_related_market_prices_configured_dislocation_arbitrage_strategy_runs() -> None:
    """TST-REQ-STR-004-01: Validates REQ-STR-004

    Given: related-market prices with a configured dislocation
    When: arbitrage strategy runs
    Then: an arbitrage signal is produced
    """
    pending("TST-REQ-STR-004-01", "REQ-STR-004")

def test_req_str_004_02_dislocation_below_threshold_data_stale_arbitrage_strategy_runs() -> None:
    """TST-REQ-STR-004-02: Validates REQ-STR-004

    Given: dislocation is below threshold or data is stale
    When: arbitrage strategy runs
    Then: no arbitrage signal is produced
    """
    pending("TST-REQ-STR-004-02", "REQ-STR-004")

def test_req_str_005_01_market_price_differs_model_estimate_beyond_threshold_convergence() -> None:
    """TST-REQ-STR-005-01: Validates REQ-STR-005

    Given: market price differs from model estimate beyond threshold
    When: convergence strategy runs
    Then: a convergence signal is produced
    """
    pending("TST-REQ-STR-005-01", "REQ-STR-005")

def test_req_str_005_02_price_model_estimate_within_threshold_convergence_strategy_runs() -> None:
    """TST-REQ-STR-005-02: Validates REQ-STR-005

    Given: price and model estimate are within threshold
    When: convergence strategy runs
    Then: no convergence signal is produced
    """
    pending("TST-REQ-STR-005-02", "REQ-STR-005")

def test_req_str_006_01_target_wallet_activity_configured_delay_settings_whale_copy() -> None:
    """TST-REQ-STR-006-01: Validates REQ-STR-006

    Given: target wallet activity and configured delay settings
    When: whale-copy strategy runs after the delay
    Then: a whale-copy signal is produced
    """
    pending("TST-REQ-STR-006-01", "REQ-STR-006")

def test_req_str_006_02_target_wallet_activity_occurs_within_blocked_delay_unconfigured() -> None:
    """TST-REQ-STR-006-02: Validates REQ-STR-006

    Given: target wallet activity occurs within a blocked delay or from an unconfigured wallet
    When: whale-copy strategy runs
    Then: no signal is produced
    """
    pending("TST-REQ-STR-006-02", "REQ-STR-006")

def test_req_str_007_01_multiple_strategies_produce_signals_same_market_model_decision() -> None:
    """TST-REQ-STR-007-01: Validates REQ-STR-007

    Given: multiple strategies produce signals for the same market and model
    When: decision creation starts
    Then: each strategy signal is recorded first
    """
    signals = [
        StrategySignal(
            strategy_name="arbitrage",
            model_provider=ModelProvider.OPENAI,
            instrument=prediction_instrument(),
            direction=OrderSide.BUY,
            confidence="0.7",
            inputs_hash="arb-inputs",
            persisted=True,
        ),
        StrategySignal(
            strategy_name="convergence",
            model_provider=ModelProvider.OPENAI,
            instrument=prediction_instrument(),
            direction=OrderSide.BUY,
            confidence="0.65",
            inputs_hash="conv-inputs",
            persisted=True,
        ),
    ]

    assert ensure_signals_persisted(signals)
    assert [signal.strategy_name for signal in signals] == ["arbitrage", "convergence"]
    assert all(signal.created_at is not None for signal in signals)

def test_req_str_007_02_signal_persistence_fails_decision_creation_starts_execution_decision() -> None:
    """TST-REQ-STR-007-02: Validates REQ-STR-007

    Given: signal persistence fails
    When: decision creation starts
    Then: execution decision creation is blocked
    """
    signal = StrategySignal(
        strategy_name="arbitrage",
        model_provider=ModelProvider.OPENAI,
        instrument=prediction_instrument(),
        direction=OrderSide.BUY,
        confidence="0.7",
        inputs_hash="arb-inputs",
        persisted=False,
    )

    assert not ensure_signals_persisted([signal])

def test_req_str_008_01_strategy_signals_disagree_consensus_rules_run_configured_rule() -> None:
    """TST-REQ-STR-008-01: Validates REQ-STR-008

    Given: strategy signals disagree
    When: consensus rules run
    Then: the configured rule determines whether an order decision is created
    """
    pending("TST-REQ-STR-008-01", "REQ-STR-008")

def test_req_str_008_02_unknown_consensus_rule_signals_disagree_no_order_created() -> None:
    """TST-REQ-STR-008-02: Validates REQ-STR-008

    Given: an unknown consensus rule
    When: signals disagree
    Then: no order is created and config validation reports the issue
    """
    pending("TST-REQ-STR-008-02", "REQ-STR-008")

def test_req_str_009_01_authorized_dashboard_user_changes_strategy_enabled_flags_settings() -> None:
    """TST-REQ-STR-009-01: Validates REQ-STR-009

    Given: an authorized dashboard user changes strategy enabled flags or settings
    When: config is saved
    Then: strategy config is persisted and available to the next loop
    """
    pending("TST-REQ-STR-009-01", "REQ-STR-009")
