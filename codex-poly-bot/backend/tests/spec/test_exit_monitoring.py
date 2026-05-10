"""Red-phase tests for Exit Monitoring."""

from __future__ import annotations

from decimal import Decimal

from app.domain import (
    ExitTrigger,
    ExitTriggerType,
    Instrument,
    InstrumentType,
    PositionSnapshot,
    PositionState,
    Venue,
    evaluate_exit_triggers,
)
from app.services import (
    ExitExecutionRequest,
    FakeVenueSubmitter,
    evaluate_profit_target_exit,
    evaluate_stale_thesis_exit,
    evaluate_volume_spike_exit,
    execute_exit_order,
)


def prediction_instrument() -> Instrument:
    return Instrument(
        venue=Venue.POLYMARKET_US,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        market_id="market-1",
        outcome_id="yes",
        display_name="Will the event happen?",
    )


def test_req_ext_001_01_open_positions_configured_exit_triggers_exit_monitoring_runs() -> None:
    """TST-REQ-EXT-001-01: Validates REQ-EXT-001

    Given: open positions and configured exit triggers
    When: exit monitoring runs
    Then: positions are evaluated against the triggers
    """
    position = PositionSnapshot(
        position_id="pos-1",
        instrument=prediction_instrument(),
        state=PositionState.OPEN,
        unrealized_pnl="8.50",
    )
    trigger = ExitTrigger(
        trigger_type=ExitTriggerType.PROFIT_TARGET,
        position_id="pos-1",
        threshold="5",
        observed_value="8.50",
        reason="profit target reached",
    )

    assert evaluate_exit_triggers([position], [trigger]) == [trigger]
    assert trigger.created_at is not None


def test_req_ext_001_02_no_open_positions_exit_monitoring_runs_no_exit() -> None:
    """TST-REQ-EXT-001-02: Validates REQ-EXT-001

    Given: no open positions
    When: exit monitoring runs
    Then: no exit decisions are created and the loop records an empty result
    """
    trigger = ExitTrigger(
        trigger_type=ExitTriggerType.PROFIT_TARGET,
        position_id="pos-1",
        threshold="5",
        observed_value="8.50",
        reason="profit target reached",
    )

    assert evaluate_exit_triggers([], [trigger]) == []


def test_req_ext_002_01_position_reaches_configured_profit_target_exit_monitoring_runs() -> None:
    """TST-REQ-EXT-002-01: Validates REQ-EXT-002

    Given: a position reaches the configured profit target
    When: exit monitoring runs
    Then: an exit decision is created
    """
    position = PositionSnapshot(
        position_id="pos-1",
        instrument=prediction_instrument(),
        state=PositionState.OPEN,
        unrealized_pnl=Decimal("5.00"),
    )

    trigger = evaluate_profit_target_exit(position, profit_target=Decimal("5.00"))

    assert trigger is not None
    assert trigger.trigger_type == ExitTriggerType.PROFIT_TARGET
    assert trigger.reason == "profit target reached"

def test_req_ext_002_02_position_just_below_profit_target_exit_monitoring_runs() -> None:
    """TST-REQ-EXT-002-02: Validates REQ-EXT-002

    Given: a position is just below the profit target
    When: exit monitoring runs
    Then: no profit-target exit decision is created
    """
    position = PositionSnapshot(
        position_id="pos-1",
        instrument=prediction_instrument(),
        state=PositionState.OPEN,
        unrealized_pnl=Decimal("4.99"),
    )

    assert evaluate_profit_target_exit(position, profit_target=Decimal("5.00")) is None

def test_req_ext_003_01_volume_spike_exceeds_configured_threshold_exit_monitoring_runs() -> None:
    """TST-REQ-EXT-003-01: Validates REQ-EXT-003

    Given: volume spike exceeds the configured threshold
    When: exit monitoring runs
    Then: an exit decision is created
    """
    trigger = evaluate_volume_spike_exit(
        position_id="pos-1",
        observed_volume=Decimal("220"),
        baseline_volume=Decimal("100"),
        multiplier_threshold=Decimal("2"),
        stale_data=False,
    )

    assert trigger is not None
    assert trigger.trigger_type == ExitTriggerType.VOLUME_SPIKE
    assert trigger.observed_value == Decimal("2.2")

def test_req_ext_003_02_volume_spike_below_threshold_data_stale_exit_monitoring() -> None:
    """TST-REQ-EXT-003-02: Validates REQ-EXT-003

    Given: volume spike is below threshold or data is stale
    When: exit monitoring runs
    Then: no volume-spike exit decision is created
    """
    below = evaluate_volume_spike_exit(
        position_id="pos-1",
        observed_volume=Decimal("190"),
        baseline_volume=Decimal("100"),
        multiplier_threshold=Decimal("2"),
        stale_data=False,
    )
    stale = evaluate_volume_spike_exit(
        position_id="pos-1",
        observed_volume=Decimal("300"),
        baseline_volume=Decimal("100"),
        multiplier_threshold=Decimal("2"),
        stale_data=True,
    )

    assert below is None
    assert stale is None

def test_req_ext_004_01_thesis_age_price_movement_exceed_stale_thesis_thresholds() -> None:
    """TST-REQ-EXT-004-01: Validates REQ-EXT-004

    Given: thesis age and price movement exceed stale-thesis thresholds
    When: exit monitoring runs
    Then: an exit decision is created
    """
    trigger = evaluate_stale_thesis_exit(
        position_id="pos-1",
        thesis_age_hours=Decimal("49"),
        max_age_hours=Decimal("48"),
        price_move_pct=Decimal("0.16"),
        min_price_move_pct=Decimal("0.15"),
    )

    assert trigger is not None
    assert trigger.trigger_type == ExitTriggerType.STALE_THESIS

def test_req_ext_004_02_only_one_stale_thesis_condition_met_both_required() -> None:
    """TST-REQ-EXT-004-02: Validates REQ-EXT-004

    Given: only one stale-thesis condition is met when both are required by config
    When: exit monitoring runs
    Then: no stale-thesis exit is created
    """
    age_only = evaluate_stale_thesis_exit(
        position_id="pos-1",
        thesis_age_hours=Decimal("49"),
        max_age_hours=Decimal("48"),
        price_move_pct=Decimal("0.10"),
        min_price_move_pct=Decimal("0.15"),
    )
    move_only = evaluate_stale_thesis_exit(
        position_id="pos-1",
        thesis_age_hours=Decimal("47"),
        max_age_hours=Decimal("48"),
        price_move_pct=Decimal("0.16"),
        min_price_move_pct=Decimal("0.15"),
    )

    assert age_only is None
    assert move_only is None

def test_req_ext_005_01_dry_run_mode_enabled_exit_approved_exit_execution() -> None:
    """TST-REQ-EXT-005-01: Validates REQ-EXT-005

    Given: dry-run mode is enabled and an exit is approved
    When: exit execution runs
    Then: a simulated exit is recorded
    """
    submitter = FakeVenueSubmitter()
    result = execute_exit_order(
        ExitExecutionRequest(
            position_id="pos-1",
            venue=Venue.POLYMARKET_US,
            global_execution_mode="dry_run",
            risk_approved=True,
        ),
        submitter=submitter,
    )

    assert result.status == "simulated"
    assert result.exit_recorded
    assert not result.venue_submitted

def test_req_ext_005_02_dry_run_mode_enabled_venue_clients_mocked_exit() -> None:
    """TST-REQ-EXT-005-02: Validates REQ-EXT-005

    Given: dry-run mode is enabled and venue clients are mocked
    When: exit execution runs
    Then: no venue exit order is submitted
    """
    submitter = FakeVenueSubmitter()
    execute_exit_order(
        ExitExecutionRequest(
            position_id="pos-1",
            venue=Venue.POLYMARKET_US,
            global_execution_mode="dry_run",
            risk_approved=True,
        ),
        submitter=submitter,
    )

    assert submitter.submit_calls == 0

def test_req_ext_006_01_live_mode_enabled_exit_approved_exit_execution_runs() -> None:
    """TST-REQ-EXT-006-01: Validates REQ-EXT-006

    Given: live mode is enabled and an exit is approved
    When: exit execution runs
    Then: the exit is routed through risk and execution
    """
    submitter = FakeVenueSubmitter()
    result = execute_exit_order(
        ExitExecutionRequest(
            position_id="pos-1",
            venue=Venue.POLYMARKET_US,
            global_execution_mode="live",
            risk_approved=True,
        ),
        submitter=submitter,
    )

    assert result.status == "submitted"
    assert result.venue_submitted
    assert submitter.submit_calls == 1

def test_req_ext_006_02_live_mode_enabled_but_risk_checks_fail_exit() -> None:
    """TST-REQ-EXT-006-02: Validates REQ-EXT-006

    Given: live mode is enabled but risk checks fail
    When: exit execution runs
    Then: no venue exit order is submitted
    """
    submitter = FakeVenueSubmitter()
    result = execute_exit_order(
        ExitExecutionRequest(
            position_id="pos-1",
            venue=Venue.POLYMARKET_US,
            global_execution_mode="live",
            risk_approved=False,
            risk_refusal_reason="STALE_MARKET_DATA",
        ),
        submitter=submitter,
    )

    assert result.status == "refused"
    assert result.refusal_reason == "STALE_MARKET_DATA"
    assert submitter.submit_calls == 0
