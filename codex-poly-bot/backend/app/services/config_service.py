"""Runtime configuration service.

REQ: REQ-UI-006, REQ-UI-007, REQ-OBS-004, REQ-OBS-006
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.db import PersistenceUnavailableError, RepositoryRegistry, UnitOfWork
from app.domain import Environment
from app.services.audit_service import ActorContext, AuditService, ConfigChange, ConfigMutationResult


class ConfigConflictError(ValueError):
    """Raised when a dashboard save targets a stale config version.

    REQ: REQ-UI-007
    """


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    """One immutable config view for a trading loop.

    REQ: REQ-UI-007
    """

    environment: Environment
    version: str
    payload: dict[str, Any]
    audit_event_id: str | None = None
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ConfigReloadResult:
    """Result of loading the next-loop config snapshot.

    REQ: REQ-UI-007, REQ-OBS-006
    """

    snapshot: RuntimeConfigSnapshot
    degraded: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class ConfigSaveResult:
    """Audited config save result returned to dashboard API callers.

    REQ: REQ-UI-006, REQ-UI-007
    """

    mutation: ConfigMutationResult
    applies_on_next_loop: bool


class ConfigService:
    """Persist dashboard config changes and load stable loop snapshots."""

    def __init__(self, registry: RepositoryRegistry | None = None):
        self.registry = registry or RepositoryRegistry()
        self.audit_service = AuditService(self.registry)
        self._last_good_snapshots: dict[Environment, RuntimeConfigSnapshot] = {}

    def save_config_change(
        self,
        *,
        actor: ActorContext,
        environment: Environment,
        change: ConfigChange,
        version: str,
        payload: dict[str, Any],
        expected_version: str | None = None,
    ) -> ConfigSaveResult:
        """Persist a new version after auditing the dashboard change.

        REQ: REQ-UI-006, REQ-UI-007, REQ-OBS-004
        """

        if expected_version is not None and expected_version != self.current_version(environment):
            raise ConfigConflictError("config version conflict")

        with UnitOfWork(self.registry.state) as unit:
            audit_event = self.audit_service.record_config_change(
                actor=actor,
                environment=environment,
                change=change,
            )
            self._deactivate_active_versions(environment)
            config_version = self.registry.shared().record_config_version(
                environment=environment,
                version=version,
                payload=deepcopy(payload),
            )
            unit.commit()
        mutation = ConfigMutationResult(
            audit_event=audit_event,
            config_version=config_version,
        )
        return ConfigSaveResult(mutation=mutation, applies_on_next_loop=True)

    def config_for_next_loop(self, environment: Environment) -> ConfigReloadResult:
        """Load one config snapshot for the next trading loop.

        REQ: REQ-UI-007, REQ-OBS-006
        """

        try:
            row = self._latest_config_row(environment)
        except PersistenceUnavailableError as exc:
            return self._degraded_reload(environment, str(exc))

        if row is None:
            fallback = RuntimeConfigSnapshot(
                environment=environment,
                version="bootstrap",
                payload={},
            )
            self._last_good_snapshots[environment] = fallback
            return ConfigReloadResult(snapshot=fallback)

        snapshot = RuntimeConfigSnapshot(
            environment=environment,
            version=row["version"],
            payload=deepcopy(row["payload"]),
        )
        self._last_good_snapshots[environment] = snapshot
        return ConfigReloadResult(snapshot=snapshot)

    def current_version(self, environment: Environment) -> str | None:
        """Return the newest active config version for an environment."""

        row = self._latest_config_row(environment)
        return row["version"] if row else None

    def _latest_config_row(self, environment: Environment) -> dict | None:
        rows = [
            row
            for row in self.registry.state.rows("shared.config_versions")
            if row["environment"] == environment.value and row["active"]
        ]
        if not rows:
            return None
        return max(rows, key=lambda row: row["created_at"])

    def _deactivate_active_versions(self, environment: Environment) -> None:
        for row in self.registry.state.rows("shared.config_versions"):
            if row["environment"] == environment.value:
                row["active"] = False

    def _degraded_reload(self, environment: Environment, message: str) -> ConfigReloadResult:
        prior = self._last_good_snapshots.get(environment)
        if prior is None:
            prior = RuntimeConfigSnapshot(
                environment=environment,
                version="bootstrap",
                payload={},
            )
            self._last_good_snapshots[environment] = prior

        health_message = f"config reload failed: {message}"
        try:
            self.registry.shared().record_system_health(
                component="config",
                status="degraded",
                message=health_message,
                environment=environment,
            )
        except PersistenceUnavailableError:
            pass
        return ConfigReloadResult(
            snapshot=prior,
            degraded=True,
            error_message=health_message,
        )
