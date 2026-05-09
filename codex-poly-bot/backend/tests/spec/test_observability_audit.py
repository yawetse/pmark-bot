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
from app.services import ActorContext, AuditService, CloudWatchLogSink, ConfigChange


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
    service = AuditService()
    sink = CloudWatchLogSink(enabled=True)
    event = StructuredLogEvent(
        event_name="deployment.health",
        correlation_id="corr-aws-1",
        environment=Environment.PRODUCTION,
        metadata={"component": "api", "status": "healthy"},
    )

    result = service.emit_log(event, sink=sink)

    assert result.cloudwatch_delivered
    assert not result.degraded
    assert sink.delivered_events[0]["event_name"] == "deployment.health"
    assert service.local_logs[0]["correlation_id"] == "corr-aws-1"

def test_req_obs_002_02_cloudwatch_delivery_fails_app_logs_emitted_local_structured() -> None:
    """TST-REQ-OBS-002-02: Validates REQ-OBS-002

    Given: CloudWatch delivery fails
    When: app logs are emitted
    Then: local structured logs remain available and degraded status is recorded
    """
    service = AuditService()
    sink = CloudWatchLogSink(enabled=True, fail_delivery=True)
    event = StructuredLogEvent(
        event_name="deployment.health",
        correlation_id="corr-aws-2",
        environment=Environment.PRODUCTION,
        metadata={"component": "api", "status": "healthy"},
    )

    result = service.emit_log(event, sink=sink)
    health = service.registry.state.rows("shared.system_health")[0]

    assert not result.cloudwatch_delivered
    assert result.degraded
    assert result.error_message == "CloudWatch delivery failed"
    assert service.local_logs[0]["event_name"] == "deployment.health"
    assert health["component"] == "cloudwatch"
    assert health["status"] == "degraded"

    unavailable_health = AuditService(
        RepositoryRegistry(DatabaseState(fail_on_tables={"shared.system_health"}))
    )
    unavailable_result = unavailable_health.emit_log(event, sink=sink)
    assert unavailable_result.degraded
    assert "health persistence failed" in (unavailable_result.error_message or "")
    assert unavailable_health.local_logs[0]["event_name"] == "deployment.health"

def test_req_obs_003_01_live_order_refused_submitted_filled_canceled_failed_order() -> None:
    """TST-REQ-OBS-003-01: Validates REQ-OBS-003

    Given: a live order is refused, submitted, filled, canceled, or failed
    When: the order event is handled
    Then: an audit event is produced
    """
    service = AuditService()

    for event_type in OrderEventType:
        event = OrderEvent(
            order_id=f"order-{event_type.value}",
            event_type=event_type,
            venue=Venue.POLYMARKET_US,
            model_provider=ModelProvider.OPENAI,
            message=f"order {event_type.value}",
        )
        result = service.record_order_event(
            event,
            environment=Environment.DEVELOPMENT,
            actor="execution-worker",
        )

        assert result.order_event["order_id"] == event.order_id
        assert result.audit_event["entity_id"] == event.order_id
        assert result.audit_event["action"] == event_type.value

    registry = service.registry
    assert len(registry.state.rows("openai.order_events")) == len(OrderEventType)
    assert len(registry.state.rows("shared.audit_events")) == len(OrderEventType)

def test_req_obs_003_02_audit_event_persistence_fails_order_event_event_handled() -> None:
    """TST-REQ-OBS-003-02: Validates REQ-OBS-003

    Given: audit event persistence fails for an order event
    When: the event is handled
    Then: failure is surfaced and not ignored
    """
    registry = RepositoryRegistry(DatabaseState(fail_on_tables={"shared.audit_events"}))
    service = AuditService(registry)
    event = OrderEvent(
        order_id="order-1",
        event_type=OrderEventType.FAILED,
        venue=Venue.POLYMARKET_US,
        model_provider=ModelProvider.OPENAI,
        message="venue rejected the order",
    )

    with pytest.raises(PersistenceUnavailableError):
        service.record_order_event(event, environment=Environment.PRODUCTION)
    assert registry.state.rows("openai.order_events") == []

def test_req_obs_004_01_dashboard_user_changes_config_toggles_live_mode_activates() -> None:
    """TST-REQ-OBS-004-01: Validates REQ-OBS-004

    Given: a dashboard user changes config, toggles live mode, or activates kill switch
    When: the action succeeds
    Then: an audit event is produced
    """
    service = AuditService()
    actor = ActorContext(username="yaw", ip_address="203.0.113.10")

    service.record_config_change(
        actor=actor,
        environment=Environment.DEVELOPMENT,
        change=ConfigChange(path="training_loop_seconds", old_value=30, new_value=60),
    )
    service.record_config_change(
        actor=actor,
        action="live_mode.toggle",
        environment=Environment.DEVELOPMENT,
        change=ConfigChange(path="live_enabled", old_value=False, new_value=True),
    )
    service.record_config_change(
        actor=actor,
        action="kill_switch.activate",
        environment=Environment.DEVELOPMENT,
        change=ConfigChange(path="kill_switch.enabled", old_value=False, new_value=True),
    )

    rows = service.registry.state.rows("shared.audit_events")
    assert {row["action"] for row in rows} == {
        "config.update",
        "live_mode.toggle",
        "kill_switch.activate",
    }
    assert rows[0]["metadata"]["ip_address"] == "203.0.113.10"

def test_req_obs_004_02_dashboard_action_denied_authorization_fails_security_relevant_audit() -> None:
    """TST-REQ-OBS-004-02: Validates REQ-OBS-004

    Given: a dashboard action is denied
    When: authorization fails
    Then: a security-relevant audit event is produced without applying the action
    """
    service = AuditService()

    audit_row = service.record_denied_dashboard_action(
        actor=ActorContext(username="not-allowed-user", ip_address="198.51.100.42"),
        action="live_mode.toggle",
        environment=Environment.PRODUCTION,
        reason="user not in allowlist",
    )

    assert audit_row["success"] is False
    assert audit_row["metadata"]["applied"] is False
    assert audit_row["metadata"]["ip_address"] == "198.51.100.42"
    assert service.registry.state.rows("shared.config_versions") == []

    original_before_correction = dict(audit_row)
    correction = service.record_corrective_audit_event(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        environment=Environment.PRODUCTION,
        original_event_id=audit_row["id"],
        reason="added missing authorization context",
    )
    audit_rows = service.registry.state.rows("shared.audit_events")

    assert correction["event_type"] == "audit_correction"
    assert correction["entity_id"] == audit_row["id"]
    assert len(audit_rows) == 2
    assert audit_rows[0] == original_before_correction
    assert audit_rows[1]["id"] == correction["id"]

def test_req_obs_005_01_recent_audit_events_health_indicators_exist_dashboard_observability() -> None:
    """TST-REQ-OBS-005-01: Validates REQ-OBS-005

    Given: recent audit events and health indicators exist
    When: dashboard observability views render
    Then: recent events and health are visible
    """
    service = AuditService()
    service.record_config_change(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        environment=Environment.DEVELOPMENT,
        change=ConfigChange(path="live_enabled", old_value=False, new_value=True),
    )
    service.record_config_change(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        environment=Environment.PRODUCTION,
        change=ConfigChange(path="live_enabled", old_value=False, new_value=True),
    )
    service.registry.shared().record_system_health(
        component="trading-loop",
        status="healthy",
        message="loop heartbeat current",
        environment=Environment.DEVELOPMENT,
    )
    service.registry.shared().record_system_health(
        component="trading-loop",
        status="degraded",
        message="production status should not appear",
        environment=Environment.PRODUCTION,
    )

    snapshot = service.dashboard_observability_snapshot(
        environment=Environment.DEVELOPMENT,
        limit=1,
    )

    assert snapshot.audit_events[0]["event_type"] == "dashboard_config_change"
    assert snapshot.audit_events[0]["environment"] == Environment.DEVELOPMENT.value
    assert len(snapshot.audit_events) == 1
    assert snapshot.health_indicators[0]["component"] == "trading-loop"
    assert snapshot.health_indicators[0]["environment"] == Environment.DEVELOPMENT.value
    assert len(snapshot.health_indicators) == 1

def test_req_obs_006_01_background_worker_fails_worker_supervision_records_failure_dashboard() -> None:
    """TST-REQ-OBS-006-01: Validates REQ-OBS-006

    Given: a background worker fails
    When: worker supervision records the failure
    Then: dashboard health shows degraded status
    """
    service = AuditService()

    health = service.record_worker_failure(
        environment=Environment.DEVELOPMENT,
        worker_name="ingestion-worker",
        message="daily full download failed",
    )
    snapshot = service.dashboard_observability_snapshot()

    assert health["component"] == "ingestion-worker"
    assert health["status"] == "degraded"
    assert snapshot.health_indicators[0]["message"] == "daily full download failed"
    assert snapshot.audit_events[0]["event_type"] == "worker_failure"
