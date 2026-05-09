"""Audit and observability service.

REQ: REQ-OBS-001, REQ-OBS-002, REQ-OBS-003, REQ-OBS-004, REQ-OBS-005,
REQ-OBS-006, REQ-UI-006, REQ-EXE-016, REQ-DB-006
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.db import (
    OrderEventHandlingResult,
    PersistenceUnavailableError,
    RepositoryRegistry,
    UnitOfWork,
)
from app.domain import Environment, OrderEvent, StructuredLogEvent, redact_metadata


@dataclass(frozen=True)
class ActorContext:
    """Dashboard or system actor context.

    REQ: REQ-OBS-004, REQ-UI-006
    """

    username: str
    ip_address: str


@dataclass(frozen=True)
class ConfigChange:
    """Auditable configuration change.

    REQ: REQ-OBS-004, REQ-UI-006
    """

    path: str
    old_value: Any
    new_value: Any


@dataclass(frozen=True)
class LogEmissionResult:
    """Result of local and CloudWatch log emission.

    REQ: REQ-OBS-001, REQ-OBS-002
    """

    local_event: dict
    cloudwatch_delivered: bool
    degraded: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class ObservabilitySnapshot:
    """Dashboard-ready audit and health snapshot.

    REQ: REQ-OBS-005, REQ-OBS-006
    """

    audit_events: list[dict]
    health_indicators: list[dict]


@dataclass(frozen=True)
class ConfigMutationResult:
    """Result of auditing and persisting a config version together.

    REQ: REQ-OBS-004, REQ-UI-006
    """

    audit_event: dict
    config_version: dict


@dataclass
class CloudWatchLogSink:
    """Small testable adapter for CloudWatch log delivery.

    REQ: REQ-OBS-002
    """

    enabled: bool
    fail_delivery: bool = False
    delivered_events: list[dict] = field(default_factory=list)

    def send(self, event: dict) -> None:
        if not self.enabled:
            return
        if self.fail_delivery:
            raise RuntimeError("CloudWatch delivery failed")
        self.delivered_events.append(event)


class AuditService:
    """Service API for audit events, structured logs, and health status."""

    def __init__(self, registry: RepositoryRegistry | None = None):
        self.registry = registry or RepositoryRegistry()
        self.local_logs: list[dict] = []

    def emit_log(
        self,
        event: StructuredLogEvent,
        *,
        sink: CloudWatchLogSink | None = None,
    ) -> LogEmissionResult:
        """Emit a redacted structured log locally and optionally to CloudWatch.

        REQ: REQ-OBS-001, REQ-OBS-002
        """

        payload = self._structured_log_payload(event)
        self.local_logs.append(payload)
        if sink is None or not sink.enabled:
            return LogEmissionResult(local_event=payload, cloudwatch_delivered=False)
        try:
            sink.send(payload)
        except RuntimeError as exc:
            health_message = str(exc)
            try:
                self.registry.shared().record_system_health(
                    component="cloudwatch",
                    status="degraded",
                    message=health_message,
                    environment=event.environment,
                )
            except PersistenceUnavailableError as health_exc:
                health_message = f"{health_message}; health persistence failed: {health_exc}"
            return LogEmissionResult(
                local_event=payload,
                cloudwatch_delivered=False,
                degraded=True,
                error_message=health_message,
            )
        return LogEmissionResult(local_event=payload, cloudwatch_delivered=True)

    def record_order_event(
        self,
        event: OrderEvent,
        *,
        environment: Environment,
        actor: str = "system",
    ) -> OrderEventHandlingResult:
        """Persist an order event and matching audit row.

        REQ: REQ-OBS-003, REQ-EXE-016
        """

        return self.registry.record_order_event_with_audit(
            event,
            environment=environment,
            actor=actor,
        )

    def record_config_change(
        self,
        *,
        actor: ActorContext,
        environment: Environment,
        change: ConfigChange,
        action: str = "config.update",
        success: bool = True,
    ) -> dict:
        """Persist a dashboard configuration audit event.

        REQ: REQ-OBS-004, REQ-UI-006
        """

        metadata = redact_metadata(
            {
                "path": change.path,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "ip_address": actor.ip_address,
            }
        )
        return self.registry.shared().record_audit_event(
            event_type="dashboard_config_change",
            actor=actor.username,
            action=action,
            environment=environment,
            success=success,
            metadata=metadata,
        )

    def record_config_change_and_version(
        self,
        *,
        actor: ActorContext,
        environment: Environment,
        change: ConfigChange,
        version: str,
        payload: dict,
        action: str = "config.update",
    ) -> ConfigMutationResult:
        """Persist audit and config version under one unit of work.

        REQ: REQ-OBS-004, REQ-UI-006
        """

        with UnitOfWork(self.registry.state) as unit:
            audit_event = self.record_config_change(
                actor=actor,
                environment=environment,
                change=change,
                action=action,
            )
            config_version = self.registry.shared().record_config_version(
                environment=environment,
                version=version,
                payload=payload,
            )
            unit.commit()
        return ConfigMutationResult(
            audit_event=audit_event,
            config_version=config_version,
        )

    def record_corrective_audit_event(
        self,
        *,
        actor: ActorContext,
        environment: Environment,
        original_event_id: str,
        reason: str,
        metadata: dict | None = None,
    ) -> dict:
        """Add a new audit event to correct prior audit context.

        REQ: REQ-DB-006, REQ-OBS-004
        """

        return self.registry.shared().record_audit_event(
            event_type="audit_correction",
            actor=actor.username,
            action="audit.correct",
            environment=environment,
            entity_id=original_event_id,
            metadata={
                "reason": reason,
                "ip_address": actor.ip_address,
                **(metadata or {}),
            },
        )

    def record_denied_dashboard_action(
        self,
        *,
        actor: ActorContext,
        environment: Environment,
        action: str,
        reason: str,
    ) -> dict:
        """Persist an audit row for denied dashboard actions.

        REQ: REQ-OBS-004, REQ-UI-006
        """

        return self.registry.shared().record_audit_event(
            event_type="authorization_denied",
            actor=actor.username,
            action=action,
            environment=environment,
            success=False,
            metadata={
                "reason": reason,
                "ip_address": actor.ip_address,
                "applied": False,
            },
        )

    def record_worker_failure(
        self,
        *,
        environment: Environment,
        worker_name: str,
        message: str,
    ) -> dict:
        """Record a failed worker and expose degraded dashboard status.

        REQ: REQ-OBS-006
        """

        health = self.registry.shared().record_system_health(
            component=worker_name,
            status="degraded",
            message=message,
            environment=environment,
        )
        self.registry.shared().record_audit_event(
            event_type="worker_failure",
            actor="system",
            action="worker.failed",
            environment=environment,
            entity_id=worker_name,
            success=False,
            metadata={"message": message},
        )
        return health

    def dashboard_observability_snapshot(
        self,
        *,
        environment: Environment | None = None,
        limit: int = 100,
    ) -> ObservabilitySnapshot:
        """Return recent audit events and health indicators for the dashboard.

        REQ: REQ-OBS-005
        """

        bounded_limit = min(max(limit, 1), 100)
        audit_rows = self.registry.state.rows("shared.audit_events")
        if environment is not None:
            audit_rows = [
                row for row in audit_rows
                if row["environment"] == environment.value
            ]
        audit_events = sorted(
            audit_rows,
            key=lambda row: row["created_at"],
            reverse=True,
        )[:bounded_limit]
        health_rows = self.registry.state.rows("shared.system_health")
        if environment is not None:
            health_rows = [
                row for row in health_rows
                if row.get("environment") == environment.value
            ]
        health_indicators = sorted(
            health_rows,
            key=lambda row: row["created_at"],
            reverse=True,
        )[:bounded_limit]
        return ObservabilitySnapshot(
            audit_events=audit_events,
            health_indicators=health_indicators,
        )

    @staticmethod
    def _structured_log_payload(event: StructuredLogEvent) -> dict:
        return {
            "event_name": event.event_name,
            "correlation_id": event.correlation_id,
            "environment": event.environment.value,
            "venue": event.venue.value if event.venue else None,
            "model_provider": event.model_provider.value if event.model_provider else None,
            "entity_id": event.entity_id,
            "metadata": event.metadata,
            "created_at": datetime.now(UTC),
        }
