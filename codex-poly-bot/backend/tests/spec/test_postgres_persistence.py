"""Red-phase tests for Postgres Persistence."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain import (
    Environment,
    Instrument,
    InstrumentType,
    ModelProvider,
    OrderType,
    PositionState,
    PositionTransition,
    TradeDecision,
    Venue,
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


def test_req_db_001_01_live_dry_run_position_events_persistence_runs_both() -> None:
    """TST-REQ-DB-001-01: Validates REQ-DB-001

    Given: live and dry-run position events
    When: persistence runs
    Then: both position types are stored in Postgres
    """
    pending("TST-REQ-DB-001-01", "REQ-DB-001")

def test_req_db_001_02_duplicate_position_events_same_idempotency_key_persistence_runs() -> None:
    """TST-REQ-DB-001-02: Validates REQ-DB-001

    Given: duplicate position events with the same idempotency key
    When: persistence runs
    Then: the system avoids duplicate position rows
    """
    pending("TST-REQ-DB-001-02", "REQ-DB-001")

def test_req_db_002_01_claude_openai_records_migrations_repositories_run_each_model() -> None:
    """TST-REQ-DB-002-01: Validates REQ-DB-002

    Given: Claude and OpenAI records
    When: migrations and repositories run
    Then: each model provider uses its separate schema
    """
    pending("TST-REQ-DB-002-01", "REQ-DB-002")

def test_req_db_002_02_repository_attempts_write_model_record_wrong_schema_validation() -> None:
    """TST-REQ-DB-002-02: Validates REQ-DB-002

    Given: a repository attempts to write a model record to the wrong schema
    When: validation runs
    Then: the write is rejected
    """
    pending("TST-REQ-DB-002-02", "REQ-DB-002")

def test_req_db_003_01_shared_config_audit_system_health_records_persistence_runs() -> None:
    """TST-REQ-DB-003-01: Validates REQ-DB-003

    Given: shared config, audit, and system health records
    When: persistence runs
    Then: shared records are stored in the shared schema
    """
    pending("TST-REQ-DB-003-01", "REQ-DB-003")

def test_req_db_003_02_shared_record_routed_model_schema_repository_validation_runs() -> None:
    """TST-REQ-DB-003-02: Validates REQ-DB-003

    Given: a shared record is routed to a model schema
    When: repository validation runs
    Then: the write is rejected
    """
    pending("TST-REQ-DB-003-02", "REQ-DB-003")

def test_req_db_004_01_trade_decision_all_required_fields_persistence_runs_provider() -> None:
    """TST-REQ-DB-004-01: Validates REQ-DB-004

    Given: a trade decision with all required fields
    When: persistence runs
    Then: provider, venue, environment, instrument, signal, decision, order type, size, and timestamp are saved
    """
    decision = TradeDecision(
        model_provider=ModelProvider.OPENAI,
        venue=Venue.POLYMARKET_US,
        environment=Environment.LOCAL,
        instrument=prediction_instrument(),
        signal_inputs={"strategy_signal_ids": ["signal-1"], "confidence": "0.72"},
        decision="buy",
        order_type=OrderType.LIMIT,
        size=Decimal("12.50"),
    )

    dumped = decision.model_dump()
    assert dumped["model_provider"] == ModelProvider.OPENAI
    assert dumped["venue"] == Venue.POLYMARKET_US
    assert dumped["environment"] == Environment.LOCAL
    assert decision.instrument.identifier == "market-1:yes"
    assert dumped["signal_inputs"]["strategy_signal_ids"] == ["signal-1"]
    assert dumped["decision"] == "buy"
    assert dumped["order_type"] == OrderType.LIMIT
    assert dumped["size"] == Decimal("12.50")
    assert decision.created_at is not None

def test_req_db_004_02_trade_decision_missing_required_field_persistence_runs_write() -> None:
    """TST-REQ-DB-004-02: Validates REQ-DB-004

    Given: a trade decision missing a required field
    When: persistence runs
    Then: the write fails and the omission is reported
    """
    with pytest.raises(ValidationError):
        TradeDecision(
            model_provider=ModelProvider.OPENAI,
            venue=Venue.POLYMARKET_US,
            environment=Environment.LOCAL,
            instrument=prediction_instrument(),
            signal_inputs={},
            decision="buy",
            order_type=OrderType.LIMIT,
            size=Decimal("12.50"),
        )
    with pytest.raises(ValidationError):
        TradeDecision(
            model_provider=ModelProvider.OPENAI,
            venue=Venue.POLYMARKET_US,
            environment=Environment.LOCAL,
            instrument=prediction_instrument(),
            signal_inputs={"strategy_signal_ids": ["signal-1"]},
            decision="buy",
            order_type=OrderType.LIMIT,
            size=Decimal("12.50"),
            misspelled_field="ignored would be unsafe",
        )

def test_req_db_005_01_position_state_transition_persistence_runs_prior_state_new() -> None:
    """TST-REQ-DB-005-01: Validates REQ-DB-005

    Given: a position state transition
    When: persistence runs
    Then: prior state, new state, realized P&L, unrealized P&L, and reason are stored
    """
    transition = PositionTransition(
        position_id="pos-1",
        prior_state=PositionState.OPEN,
        new_state=PositionState.CLOSED,
        realized_pnl="4.25",
        unrealized_pnl="0",
        reason="profit target reached",
    )

    assert transition.prior_state == PositionState.OPEN
    assert transition.new_state == PositionState.CLOSED
    assert transition.realized_pnl == Decimal("4.25")
    assert transition.unrealized_pnl == Decimal("0")
    assert transition.reason == "profit target reached"

def test_req_db_005_02_invalid_position_state_transition_persistence_runs_transition_rejected() -> None:
    """TST-REQ-DB-005-02: Validates REQ-DB-005

    Given: an invalid position state transition
    When: persistence runs
    Then: the transition is rejected and prior state remains intact
    """
    with pytest.raises(ValidationError):
        PositionTransition(
            position_id="pos-1",
            prior_state=PositionState.OPEN,
            new_state=PositionState.OPEN,
            realized_pnl="0",
            unrealized_pnl="1.25",
            reason="no state change",
        )

def test_req_db_006_01_no_later_archive_policy_configured_retention_settings_validated() -> None:
    """TST-REQ-DB-006-01: Validates REQ-DB-006

    Given: no later archive policy is configured
    When: retention settings are validated
    Then: audit, trade, and position history have no automatic deletion
    """
    pending("TST-REQ-DB-006-01", "REQ-DB-006")

def test_req_db_007_01_postgres_available_live_order_checks_require_persistence_persistence() -> None:
    """TST-REQ-DB-007-01: Validates REQ-DB-007

    Given: Postgres is available
    When: live order checks require persistence
    Then: persistence health passes
    """
    pending("TST-REQ-DB-007-01", "REQ-DB-007")

def test_req_db_007_02_postgres_unavailable_live_order_placement_requested_order_blocked() -> None:
    """TST-REQ-DB-007-02: Validates REQ-DB-007

    Given: Postgres is unavailable
    When: live order placement is requested
    Then: the order is blocked and logs plus dashboard status surface the failure
    """
    pending("TST-REQ-DB-007-02", "REQ-DB-007")
