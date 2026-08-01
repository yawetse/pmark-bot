"""Dashboard operational controls.

REQ: REQ-UI-008, REQ-EXE-014, REQ-OBS-004
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.db import RepositoryRegistry, UnitOfWork
from app.domain import Environment
from app.services.audit_service import ActorContext, AuditService, ConfigChange
from app.services.auth_service import DashboardAccessResult


@dataclass(frozen=True)
class KillSwitchState:
    """Global kill switch state for one environment.

    REQ: REQ-UI-008, REQ-EXE-014
    """

    environment: Environment
    active: bool
    activated_by: str | None = None
    activated_at: datetime | None = None


@dataclass(frozen=True)
class KillSwitchActivationResult:
    """Result of processing a dashboard kill switch request.

    REQ: REQ-UI-008
    """

    accepted: bool
    status_code: int
    state: KillSwitchState
    audit_event: dict | None = None
    reason: str | None = None


class KillSwitchService:
    """Apply global live-trading kill switch requests."""

    def __init__(self, registry: RepositoryRegistry | None = None):
        self.registry = registry or RepositoryRegistry()
        self.audit_service = AuditService(self.registry)
        self._states: dict[Environment, KillSwitchState] = {}

    def process_activation_request(
        self,
        *,
        access: DashboardAccessResult,
        actor: ActorContext,
        environment: Environment,
    ) -> KillSwitchActivationResult:
        """Activate the kill switch only for authorized dashboard users.

        REQ: REQ-UI-008, REQ-EXE-014, REQ-OBS-004
        """

        if not access.authorized:
            return KillSwitchActivationResult(
                accepted=False,
                status_code=access.status_code,
                state=self.state(environment),
                reason=access.reason,
            )

        state = KillSwitchState(
            environment=environment,
            active=True,
            activated_by=actor.username,
            activated_at=datetime.now(UTC),
        )
        with UnitOfWork(self.registry.state) as unit:
            self.registry.state.lock_transaction_key(
                f"funding-controls:{environment.value}:global"
            )
            self._states[environment] = state
            self.registry.state.upsert_by_id(
                "shared.operational_controls",
                f"{environment.value}:global_kill_switch",
                {
                    "environment": environment.value,
                    "control": "global_kill_switch",
                    "active": True,
                    "actor": actor.username,
                    "updated_at": state.activated_at,
                },
            )
            audit_event = self.audit_service.record_config_change(
                actor=actor,
                action="kill_switch.activate",
                environment=environment,
                change=ConfigChange(
                    path="kill_switch.enabled",
                    old_value=False,
                    new_value=True,
                ),
            )
            unit.commit()
        return KillSwitchActivationResult(
            accepted=True,
            status_code=200,
            state=state,
            audit_event=audit_event,
        )

    def state(self, environment: Environment) -> KillSwitchState:
        """Return current kill switch state for an environment."""

        rows = self.registry.state.rows(
            "shared.operational_controls",
            filters={
                "environment": environment.value,
                "control": "global_kill_switch",
            },
        )
        if rows:
            latest = rows[0]
            return KillSwitchState(
                environment=environment,
                active=bool(latest.get("active")),
                activated_by=str(latest.get("actor") or "system"),
                activated_at=latest.get("updated_at"),
            )
        return self._states.get(
            environment,
            KillSwitchState(environment=environment, active=False),
        )
