"""Red-phase tests for Strategy and Signal Engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain import (
    Environment,
    Instrument,
    InstrumentType,
    ModelProvider,
    OrderSide,
    ScoringOutput,
    StrategySignal,
    Venue,
    ensure_signals_persisted,
)
from app.services import (
    ActorContext,
    AuthService,
    ConfigPatchOperation,
    ConfigService,
    ConfigValidationError,
)
from app.strategies import (
    ArbitrageStrategy,
    CandidateFilterConfig,
    ConvergenceStrategy,
    MarketCandidate,
    WhaleCopyStrategy,
    apply_strategy_consensus,
    default_trading_loop_interval_seconds,
    filter_strategy_candidates,
    schedule_next_trading_loop,
    validate_consensus_rule,
)


def prediction_instrument() -> Instrument:
    return Instrument(
        venue=Venue.POLYMARKET_US,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        market_id="market-1",
        outcome_id="yes",
        display_name="Will the event happen?",
    )


def market_candidate(
    *,
    current_price: str = "0.50",
    liquidity: str = "500",
    active: bool = True,
    stale_data: bool = False,
    spread: str = "0.02",
    hours_to_resolution: str = "24",
    related_group: str | None = None,
    related_price: str | None = None,
) -> MarketCandidate:
    return MarketCandidate(
        instrument=prediction_instrument(),
        current_price=Decimal(current_price),
        liquidity=Decimal(liquidity),
        active=active,
        stale_data=stale_data,
        spread=Decimal(spread),
        hours_to_resolution=Decimal(hours_to_resolution),
        related_group=related_group,
        related_price=Decimal(related_price) if related_price is not None else None,
    )


def scoring_output(*, estimated_probability: str = "0.70") -> ScoringOutput:
    return ScoringOutput(
        model_provider=ModelProvider.OPENAI,
        prompt_version="pm-v1",
        input_summary="market context",
        output_thesis="model probability is above market midpoint",
        confidence=Decimal("0.72"),
        estimated_probability=Decimal(estimated_probability),
        cost_estimate=Decimal("0.01"),
        instrument=prediction_instrument(),
    )


def strategy_signal(
    strategy_name: str,
    *,
    direction: OrderSide = OrderSide.BUY,
) -> StrategySignal:
    return StrategySignal(
        strategy_name=strategy_name,
        model_provider=ModelProvider.OPENAI,
        instrument=prediction_instrument(),
        direction=direction,
        confidence=Decimal("0.70"),
        inputs_hash=f"{strategy_name}-inputs",
        persisted=True,
    )


def test_req_str_001_01_default_scheduler_config_worker_starts_trading_loop_interval() -> None:
    """TST-REQ-STR-001-01: Validates REQ-STR-001

    Given: default scheduler config
    When: the worker starts
    Then: the trading loop interval is 15 minutes
    """
    now = datetime(2026, 5, 10, 12, 15, tzinfo=UTC)
    decision = schedule_next_trading_loop(
        last_started_at=now - timedelta(minutes=15),
        now=now,
    )

    assert default_trading_loop_interval_seconds() == 900
    assert decision.should_run
    assert decision.interval_seconds == 900


def test_req_str_001_02_scheduler_drift_slow_loop_body_next_loop_scheduled() -> None:
    """TST-REQ-STR-001-02: Validates REQ-STR-001

    Given: scheduler drift or a slow loop body
    When: the next loop is scheduled
    Then: the cadence is measured and logged without overlapping unsafe work
    """
    now = datetime(2026, 5, 10, 12, 2, tzinfo=UTC)

    running = schedule_next_trading_loop(
        last_started_at=now - timedelta(seconds=15),
        now=now,
        running=True,
    )
    slow_loop = schedule_next_trading_loop(
        last_started_at=now - timedelta(seconds=935),
        now=now,
    )

    assert not running.should_run
    assert running.skipped_reason == "trading loop already running"
    assert slow_loop.should_run
    assert slow_loop.drift_seconds == 35


def test_req_str_002_01_authorized_dashboard_update_loop_interval_config_saved_new() -> None:
    """TST-REQ-STR-002-01: Validates REQ-STR-002

    Given: an authorized dashboard update to loop interval
    When: config is saved
    Then: the new interval is persisted
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)
    result = service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=auth.authorize_request(auth.create_session_token(username="yaw")),
        environment=Environment.DEVELOPMENT,
        expected_version=None,
        version="v1",
        patches=[ConfigPatchOperation("replace", "trading_loop_interval_seconds", 120)],
    )

    assert result.mutation.config_version["payload"]["trading_loop_interval_seconds"] == 120


def test_req_str_002_02_invalid_loop_interval_dashboard_config_saved_validation_rejects() -> None:
    """TST-REQ-STR-002-02: Validates REQ-STR-002

    Given: an invalid loop interval
    When: dashboard config is saved
    Then: validation rejects the value
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)

    with pytest.raises(ConfigValidationError):
        service.save_config_patches(
            actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
            access=auth.authorize_request(auth.create_session_token(username="yaw")),
            environment=Environment.DEVELOPMENT,
            expected_version=None,
            version="v1",
            patches=[ConfigPatchOperation("replace", "trading_loop_interval_seconds", 0)],
        )


def test_req_str_003_01_enabled_venues_markets_pass_deterministic_filters_trading_loop() -> None:
    """TST-REQ-STR-003-01: Validates REQ-STR-003

    Given: enabled venues and markets that pass deterministic filters
    When: the trading loop runs
    Then: filtered markets are sent to LLM scoring
    """
    accepted = market_candidate()
    result = filter_strategy_candidates(
        (
            accepted,
            market_candidate(liquidity="25"),
            market_candidate(stale_data=True),
        ),
        CandidateFilterConfig(enabled_venues=frozenset({Venue.POLYMARKET_US})),
    )

    assert result.candidates == (accepted,)
    assert result.scoring_instruments == (accepted.instrument,)


def test_req_str_003_02_markets_fail_deterministic_filters_trading_loop_runs_no() -> None:
    """TST-REQ-STR-003-02: Validates REQ-STR-003

    Given: markets fail deterministic filters
    When: the trading loop runs
    Then: no LLM scoring request is created for them
    """
    result = filter_strategy_candidates(
        (
            market_candidate(active=False),
            market_candidate(stale_data=True),
            market_candidate(spread="0.08"),
        ),
        CandidateFilterConfig(enabled_venues=frozenset({Venue.POLYMARKET_US})),
    )

    assert result.candidates == ()
    assert result.scoring_instruments == ()
    assert result.refusal_reasons == (
        "market inactive",
        "stale market data",
        "spread too wide",
    )


def test_req_str_004_01_related_market_prices_configured_dislocation_arbitrage_strategy_runs() -> None:
    """TST-REQ-STR-004-01: Validates REQ-STR-004

    Given: related-market prices with a configured dislocation
    When: arbitrage strategy runs
    Then: an arbitrage signal is produced
    """
    signal = ArbitrageStrategy(min_dislocation=Decimal("0.10")).evaluate(
        market_candidate(
            current_price="0.50",
            related_price="0.65",
            related_group="election",
        ),
        model_provider=ModelProvider.OPENAI,
    )

    assert signal is not None
    assert signal.strategy_name == "arbitrage"
    assert signal.direction == OrderSide.BUY
    assert signal.persisted is False


def test_req_str_004_02_dislocation_below_threshold_data_stale_arbitrage_strategy_runs() -> None:
    """TST-REQ-STR-004-02: Validates REQ-STR-004

    Given: dislocation is below threshold or data is stale
    When: arbitrage strategy runs
    Then: no arbitrage signal is produced
    """
    strategy = ArbitrageStrategy(min_dislocation=Decimal("0.10"))

    below_threshold = strategy.evaluate(
        market_candidate(
            current_price="0.50",
            related_price="0.56",
            related_group="election",
        ),
        model_provider=ModelProvider.OPENAI,
    )
    stale = strategy.evaluate(
        market_candidate(
            current_price="0.50",
            related_price="0.70",
            related_group="election",
            stale_data=True,
        ),
        model_provider=ModelProvider.OPENAI,
    )

    assert below_threshold is None
    assert stale is None


def test_req_str_005_01_market_price_differs_model_estimate_beyond_threshold_convergence() -> None:
    """TST-REQ-STR-005-01: Validates REQ-STR-005

    Given: market price differs from model estimate beyond threshold
    When: convergence strategy runs
    Then: a convergence signal is produced
    """
    signal = ConvergenceStrategy(min_probability_gap=Decimal("0.10")).evaluate(
        scoring_output(estimated_probability="0.70"),
        current_price=Decimal("0.55"),
    )

    assert signal is not None
    assert signal.strategy_name == "convergence"
    assert signal.direction == OrderSide.BUY


def test_req_str_005_02_price_model_estimate_within_threshold_convergence_strategy_runs() -> None:
    """TST-REQ-STR-005-02: Validates REQ-STR-005

    Given: price and model estimate are within threshold
    When: convergence strategy runs
    Then: no convergence signal is produced
    """
    signal = ConvergenceStrategy(min_probability_gap=Decimal("0.10")).evaluate(
        scoring_output(estimated_probability="0.58"),
        current_price=Decimal("0.55"),
    )

    assert signal is None


def test_req_str_006_01_target_wallet_activity_configured_delay_settings_whale_copy() -> None:
    """TST-REQ-STR-006-01: Validates REQ-STR-006

    Given: target wallet activity and configured delay settings
    When: whale-copy strategy runs after the delay
    Then: a whale-copy signal is produced
    """
    signal = WhaleCopyStrategy(target_wallets=frozenset({"wallet-1"}), delay_seconds=60).evaluate(
        market_candidate(),
        model_provider=ModelProvider.OPENAI,
        wallet_id="wallet-1",
        action_age_seconds=90,
        side=OrderSide.BUY,
    )

    assert signal is not None
    assert signal.strategy_name == "whale_copy"
    assert signal.direction == OrderSide.BUY


def test_req_str_006_02_target_wallet_activity_occurs_within_blocked_delay_unconfigured() -> None:
    """TST-REQ-STR-006-02: Validates REQ-STR-006

    Given: target wallet activity occurs within a blocked delay or from an unconfigured wallet
    When: whale-copy strategy runs
    Then: no signal is produced
    """
    strategy = WhaleCopyStrategy(target_wallets=frozenset({"wallet-1"}), delay_seconds=60)

    within_delay = strategy.evaluate(
        market_candidate(),
        model_provider=ModelProvider.OPENAI,
        wallet_id="wallet-1",
        action_age_seconds=30,
        side=OrderSide.BUY,
    )
    unconfigured = strategy.evaluate(
        market_candidate(),
        model_provider=ModelProvider.OPENAI,
        wallet_id="wallet-2",
        action_age_seconds=90,
        side=OrderSide.BUY,
    )

    assert within_delay is None
    assert unconfigured is None


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
    full = apply_strategy_consensus(
        (strategy_signal("arbitrage"), strategy_signal("convergence")),
        enabled_strategies=frozenset({"arbitrage", "convergence", "whale_copy"}),
    )
    half = apply_strategy_consensus(
        (strategy_signal("arbitrage"),),
        enabled_strategies=frozenset({"arbitrage", "convergence", "whale_copy"}),
    )

    assert full.approved
    assert full.side == OrderSide.BUY
    assert full.size_multiplier == Decimal("1")
    assert half.approved
    assert half.size_multiplier == Decimal("0.5")


def test_req_str_008_02_unknown_consensus_rule_signals_disagree_no_order_created() -> None:
    """TST-REQ-STR-008-02: Validates REQ-STR-008

    Given: an unknown consensus rule
    When: signals disagree
    Then: no order is created and config validation reports the issue
    """
    validation = validate_consensus_rule("unknown")
    conflict = apply_strategy_consensus(
        (
            strategy_signal("arbitrage", direction=OrderSide.BUY),
            strategy_signal("convergence", direction=OrderSide.SELL),
        ),
        enabled_strategies=frozenset({"arbitrage", "convergence"}),
    )

    assert not validation.ok
    assert validation.refusal_reason == "unsupported consensus rule"
    assert not conflict.approved
    assert conflict.refusal_reason == "strategy direction conflict"


def test_req_str_009_01_authorized_dashboard_user_changes_strategy_enabled_flags_settings() -> None:
    """TST-REQ-STR-009-01: Validates REQ-STR-009

    Given: an authorized dashboard user changes strategy enabled flags or settings
    When: config is saved
    Then: strategy config is persisted and available to the next loop
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)

    service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=auth.authorize_request(auth.create_session_token(username="yaw")),
        environment=Environment.DEVELOPMENT,
        expected_version=None,
        version="v1",
        patches=[
            ConfigPatchOperation("replace", "strategies.whale_copy.enabled", False),
            ConfigPatchOperation("replace", "strategies.whale_copy.settings.delay_seconds", 300),
        ],
    )
    snapshot = service.config_for_next_loop(Environment.DEVELOPMENT)
    strategy = snapshot.snapshot.payload["strategies"]["whale_copy"]

    assert strategy["enabled"] is False
    assert strategy["settings"]["delay_seconds"] == 300
