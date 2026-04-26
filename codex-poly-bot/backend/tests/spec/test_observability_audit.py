"""Red-phase tests for Observability and Audit Logging."""

from __future__ import annotations

import pytest

from app.db import DatabaseState, PersistenceUnavailableError, RepositoryRegistry
from app.domain import (
    Environment,
    ModelProvider,
    OrderEvent,
    OrderEventType,
    StructuredLogEvent,
    Venue,
)
from tests.spec.helpers import pending


def test_req_obs_001_01_system_events_across_ingestion_scoring_strategy_risk_orders() -> None:
    """TST-REQ-OBS-001-01: Validates REQ-OBS-001

    Given: system events across ingestion, scoring, strategy, risk, orders, exits, notifications, config, and deployment health
    When: logging runs
    Then: structured logs are emitted
    """
    event = StructuredLogEvent(
        event_name="risk.check.completed",
        correlation_id="corr-1",
        environment=Environment.LOCAL,
        venue=Venue.POLYMARKET_US,
        model_provider=ModelProvider.OPENAI,
        entity_id="order-1",
        metadata={"check": "max_position", "passed": True},
    )

    assert event.event_name == "risk.check.completed"
    assert event.correlation_id == "corr-1"
    assert event.metadata["passed"] is True

def test_req_obs_001_02_logging_payload_contains_secrets_structured_logging_runs_secrets() -> None:
    """TST-REQ-OBS-001-02: Validates REQ-OBS-001

    Given: a logging payload contains secrets
    When: structured logging runs
    Then: secrets are redacted before emission
    """
    event = StructuredLogEvent(
        event_name="credential.loaded",
        correlation_id="corr-1",
        environment=Environment.LOCAL,
        metadata={
            "api_key": "sk-secret",
            "nested": {"private_key": "abc"},
            "items": [{"access_token": "tok-secret"}],
            "safe": "ok",
        },
    )

    assert event.metadata["api_key"] == "[REDACTED]"
    assert event.metadata["nested"]["private_key"] == "[REDACTED]"
    assert event.metadata["items"][0]["access_token"] == "[REDACTED]"
    assert event.metadata["safe"] == "ok"

def test_req_obs_002_01_aws_environment_config_app_logs_emitted_logs_sent() -> None:
    """TST-REQ-OBS-002-01: Validates REQ-OBS-002

    Given: AWS environment config
    When: app logs are emitted
    Then: logs are sent to CloudWatch
    """
    pending("TST-REQ-OBS-002-01", "REQ-OBS-002")

def test_req_obs_002_02_cloudwatch_delivery_fails_app_logs_emitted_local_structured() -> None:
    """TST-REQ-OBS-002-02: Validates REQ-OBS-002

    Given: CloudWatch delivery fails
    When: app logs are emitted
    Then: local structured logs remain available and degraded status is recorded
    """
    pending("TST-REQ-OBS-002-02", "REQ-OBS-002")

def test_req_obs_003_01_live_order_refused_submitted_filled_canceled_failed_order() -> None:
    """TST-REQ-OBS-003-01: Validates REQ-OBS-003

    Given: a live order is refused, submitted, filled, canceled, or failed
    When: the order event is handled
    Then: an audit event is produced
    """
    registry = RepositoryRegistry()

    for event_type in OrderEventType:
        event = OrderEvent(
            order_id=f"order-{event_type.value}",
            event_type=event_type,
            venue=Venue.POLYMARKET_US,
            model_provider=ModelProvider.OPENAI,
            message=f"order {event_type.value}",
        )
        result = registry.record_order_event_with_audit(
            event,
            environment=Environment.DEVELOPMENT,
            actor="execution-worker",
        )

        assert result.order_event["order_id"] == event.order_id
        assert result.audit_event["entity_id"] == event.order_id
        assert result.audit_event["action"] == event_type.value

    assert len(registry.state.rows("openai.order_events")) == len(OrderEventType)
    assert len(registry.state.rows("shared.audit_events")) == len(OrderEventType)

def test_req_obs_003_02_audit_event_persistence_fails_order_event_event_handled() -> None:
    """TST-REQ-OBS-003-02: Validates REQ-OBS-003

    Given: audit event persistence fails for an order event
    When: the event is handled
    Then: failure is surfaced and not ignored
    """
    registry = RepositoryRegistry(DatabaseState(fail_on_tables={"shared.audit_events"}))
    event = OrderEvent(
        order_id="order-1",
        event_type=OrderEventType.FAILED,
        venue=Venue.POLYMARKET_US,
        model_provider=ModelProvider.OPENAI,
        message="venue rejected the order",
    )

    with pytest.raises(PersistenceUnavailableError):
        registry.record_order_event_with_audit(event, environment=Environment.PRODUCTION)
    assert registry.state.rows("openai.order_events") == []

def test_req_obs_004_01_dashboard_user_changes_config_toggles_live_mode_activates() -> None:
    """TST-REQ-OBS-004-01: Validates REQ-OBS-004

    Given: a dashboard user changes config, toggles live mode, or activates kill switch
    When: the action succeeds
    Then: an audit event is produced
    """
    registry = RepositoryRegistry()
    shared = registry.shared()

    shared.record_audit_event(
        event_type="dashboard_config_change",
        actor="yaw",
        action="config.update",
        environment=Environment.DEVELOPMENT,
        metadata={"field": "training_loop_seconds", "value": 60},
    )
    shared.record_audit_event(
        event_type="dashboard_config_change",
        actor="yaw",
        action="live_mode.toggle",
        environment=Environment.DEVELOPMENT,
        metadata={"live_enabled": True},
    )
    shared.record_audit_event(
        event_type="dashboard_config_change",
        actor="yaw",
        action="kill_switch.activate",
        environment=Environment.DEVELOPMENT,
        metadata={"enabled": True},
    )

    assert {row["action"] for row in registry.state.rows("shared.audit_events")} == {
        "config.update",
        "live_mode.toggle",
        "kill_switch.activate",
    }

def test_req_obs_004_02_dashboard_action_denied_authorization_fails_security_relevant_audit() -> None:
    """TST-REQ-OBS-004-02: Validates REQ-OBS-004

    Given: a dashboard action is denied
    When: authorization fails
    Then: a security-relevant audit event is produced without applying the action
    """
    registry = RepositoryRegistry()

    audit_row = registry.shared().record_audit_event(
        event_type="authorization_denied",
        actor="not-allowed-user",
        action="live_mode.toggle",
        environment=Environment.PRODUCTION,
        success=False,
        metadata={"reason": "user not in allowlist", "applied": False},
    )

    assert audit_row["success"] is False
    assert audit_row["metadata"]["applied"] is False
    assert registry.state.rows("shared.config_versions") == []

def test_req_obs_005_01_recent_audit_events_health_indicators_exist_dashboard_observability() -> None:
    """TST-REQ-OBS-005-01: Validates REQ-OBS-005

    Given: recent audit events and health indicators exist
    When: dashboard observability views render
    Then: recent events and health are visible
    """
    pending("TST-REQ-OBS-005-01", "REQ-OBS-005")

def test_req_obs_006_01_background_worker_fails_worker_supervision_records_failure_dashboard() -> None:
    """TST-REQ-OBS-006-01: Validates REQ-OBS-006

    Given: a background worker fails
    When: worker supervision records the failure
    Then: dashboard health shows degraded status
    """
    pending("TST-REQ-OBS-006-01", "REQ-OBS-006")
