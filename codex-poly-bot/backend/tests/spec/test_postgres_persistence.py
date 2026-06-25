"""Red-phase tests for Postgres Persistence."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db import (
    DatabaseState,
    PersistenceConfigurationError,
    PersistenceUnavailableError,
    RepositoryRegistry,
    SchemaViolationError,
    UnitOfWork,
    create_session_factory,
    live_order_persistence_gate,
    migration_plan,
    retention_policy,
)
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
    registry = RepositoryRegistry()
    repository = registry.for_model(ModelProvider.OPENAI)
    live_transition = PositionTransition(
        position_id="live-pos-1",
        prior_state=PositionState.OPEN,
        new_state=PositionState.CLOSED,
        realized_pnl="2.25",
        unrealized_pnl="0",
        reason="live exit",
    )
    dry_run_transition = PositionTransition(
        position_id="dry-pos-1",
        prior_state=PositionState.OPEN,
        new_state=PositionState.EXITING,
        realized_pnl="0",
        unrealized_pnl="1.50",
        reason="dry-run exit check",
    )

    repository.record_position_event(
        live_transition,
        execution_mode="live",
        idempotency_key="live-event-1",
    )
    repository.record_position_event(
        dry_run_transition,
        execution_mode="dry_run",
        idempotency_key="dry-event-1",
    )

    rows = registry.state.rows("openai.position_events")
    assert {row["execution_mode"] for row in rows} == {"live", "dry_run"}
    assert {row["position_id"] for row in rows} == {"live-pos-1", "dry-pos-1"}

def test_req_db_001_02_duplicate_position_events_same_idempotency_key_persistence_runs() -> None:
    """TST-REQ-DB-001-02: Validates REQ-DB-001

    Given: duplicate position events with the same idempotency key
    When: persistence runs
    Then: the system avoids duplicate position rows
    """
    registry = RepositoryRegistry()
    repository = registry.for_model(ModelProvider.OPENAI)
    transition = PositionTransition(
        position_id="pos-1",
        prior_state=PositionState.OPEN,
        new_state=PositionState.CLOSED,
        realized_pnl="1.00",
        unrealized_pnl="0",
        reason="closed once",
    )

    first = repository.record_position_event(
        transition,
        execution_mode="live",
        idempotency_key="idem-1",
    )
    second = repository.record_position_event(
        transition,
        execution_mode="live",
        idempotency_key="idem-1",
    )

    assert second == first
    assert len(registry.state.rows("openai.position_events")) == 1

def test_req_db_002_01_claude_openai_records_migrations_repositories_run_each_model() -> None:
    """TST-REQ-DB-002-01: Validates REQ-DB-002

    Given: Claude and OpenAI records
    When: migrations and repositories run
    Then: each model provider uses its separate schema
    """
    plan = migration_plan()
    registry = RepositoryRegistry()

    assert plan.schema_names == ("shared", "claude", "openai")
    assert "claude.trade_decisions" in plan.table_names
    assert "openai.trade_decisions" in plan.table_names
    assert "openai.alpaca_reconciliation_mismatches" in plan.table_names
    assert "shared.job_runs" in plan.table_names
    assert "shared.comparison_metric_snapshots" in plan.table_names
    assert "shared.pipeline_runs" in plan.table_names
    assert "shared.pipeline_steps" in plan.table_names
    assert "openai.order_intents" in plan.table_names
    assert "openai.strategy_signals" in plan.table_names
    assert all("..." not in statement for statement in plan.sql)
    assert any("CREATE TABLE IF NOT EXISTS openai.trade_decisions" in statement for statement in plan.sql)
    assert registry.for_model(ModelProvider.CLAUDE).schema_name == "claude"
    assert registry.for_model(ModelProvider.OPENAI).schema_name == "openai"

def test_req_db_002_02_repository_attempts_write_model_record_wrong_schema_validation() -> None:
    """TST-REQ-DB-002-02: Validates REQ-DB-002

    Given: a repository attempts to write a model record to the wrong schema
    When: validation runs
    Then: the write is rejected
    """
    registry = RepositoryRegistry()

    with pytest.raises(SchemaViolationError):
        registry.for_model(ModelProvider.OPENAI).ensure_schema("claude")

def test_req_db_003_01_shared_config_audit_system_health_records_persistence_runs() -> None:
    """TST-REQ-DB-003-01: Validates REQ-DB-003

    Given: shared config, audit, and system health records
    When: persistence runs
    Then: shared records are stored in the shared schema
    """
    registry = RepositoryRegistry()
    shared = registry.shared()

    shared.record_config_version(
        environment=Environment.DEVELOPMENT,
        version="v1",
        payload={"global_execution_mode": "dry_run"},
    )
    shared.record_audit_event(
        event_type="config_change",
        actor="yaw",
        action="risk_limit.update",
        environment=Environment.DEVELOPMENT,
        metadata={"max_position": "25"},
    )
    shared.record_system_health(component="postgres", status="healthy")

    assert len(registry.state.rows("shared.config_versions")) == 1
    assert len(registry.state.rows("shared.audit_events")) == 1
    assert len(registry.state.rows("shared.system_health")) == 1

def test_req_db_003_02_shared_record_routed_model_schema_repository_validation_runs() -> None:
    """TST-REQ-DB-003-02: Validates REQ-DB-003

    Given: a shared record is routed to a model schema
    When: repository validation runs
    Then: the write is rejected
    """
    registry = RepositoryRegistry()

    with pytest.raises(SchemaViolationError):
        registry.shared().ensure_schema("openai")

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

    row = RepositoryRegistry().for_model(ModelProvider.OPENAI).record_trade_decision(decision)

    assert row["model_provider"] == ModelProvider.OPENAI.value
    assert row["venue"] == Venue.POLYMARKET_US.value
    assert row["environment"] == Environment.LOCAL.value
    assert row["instrument_identifier"] == "market-1:yes"
    assert row["signal_inputs"]["strategy_signal_ids"] == ["signal-1"]
    assert row["decision"] == "buy"
    assert row["order_type"] == OrderType.LIMIT.value
    assert row["size"] == Decimal("12.50")
    assert row["created_at"] is not None

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
    registry = RepositoryRegistry()

    row = registry.for_model(ModelProvider.OPENAI).record_position_event(
        transition,
        execution_mode="live",
        idempotency_key="pos-event-1",
    )
    position = registry.state.rows("openai.positions")[0]

    assert row["prior_state"] == PositionState.OPEN.value
    assert row["new_state"] == PositionState.CLOSED.value
    assert row["realized_pnl"] == Decimal("4.25")
    assert row["unrealized_pnl"] == Decimal("0")
    assert row["reason"] == "profit target reached"
    assert position["state"] == PositionState.CLOSED.value

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
    policy = retention_policy()

    assert policy.audit_delete_after_days is None
    assert policy.trade_delete_after_days is None
    assert policy.position_delete_after_days is None

def test_req_db_007_01_postgres_available_live_order_checks_require_persistence_persistence() -> None:
    """TST-REQ-DB-007-01: Validates REQ-DB-007

    Given: Postgres is available
    When: live order checks require persistence
    Then: persistence health passes
    """
    state = DatabaseState(available=True)
    gate = live_order_persistence_gate(state)
    session_factory = create_session_factory("postgresql+psycopg://user:pass@localhost:5432/codex_poly_bot")

    with UnitOfWork(state) as unit:
        unit.commit()

    assert gate.live_order_allowed
    assert not gate.degraded
    assert gate.system_health is not None
    assert gate.system_health["status"] == "healthy"
    assert session_factory.kw["expire_on_commit"] is False

def test_req_db_007_02_postgres_unavailable_live_order_placement_requested_order_blocked() -> None:
    """TST-REQ-DB-007-02: Validates REQ-DB-007

    Given: Postgres is unavailable
    When: live order placement is requested
    Then: the order is blocked and logs plus dashboard status surface the failure
    """
    state = DatabaseState(available=False)
    gate = live_order_persistence_gate(state)

    assert not gate.live_order_allowed
    assert gate.degraded
    assert gate.reason == "Postgres persistence is unavailable"
    assert gate.system_health is not None
    assert gate.system_health["status"] == "degraded"
    assert gate.log_event is not None
    assert gate.log_event["event_name"] == "postgres.persistence.unavailable"
    with pytest.raises(PersistenceUnavailableError):
        with UnitOfWork(state):
            pass
    with pytest.raises(PersistenceConfigurationError):
        create_session_factory("sqlite:///local.db")
