"""Dashboard API router implementations.

REQ: REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-005,
REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-009, REQ-UI-010,
REQ-UI-011, REQ-WAL-005, REQ-EXE-003, REQ-EXE-014, REQ-EXE-016,
REQ-OBS-004, REQ-OBS-005, REQ-OBS-006
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.domain import Environment, ModelProvider
from app.services import (
    ActorContext,
    ConfigAuthorizationError,
    ConfigConflictError,
    ConfigPatchOperation,
    ConfigValidationError,
    DashboardAccessResult,
)


@dataclass(frozen=True)
class DashboardRequestContext:
    """Authorized dashboard request context.

    REQ: REQ-UI-002, REQ-UI-003, REQ-OBS-004
    """

    access: DashboardAccessResult
    actor: ActorContext
    environment: Environment


def build_dashboard_router(settings: Any, services: Any) -> APIRouter:
    """Build FastAPI routes for dashboard reads and mutations.

    REQ: REQ-UI-001, REQ-UI-004, REQ-UI-005, REQ-UI-008
    """

    router = APIRouter()

    def require_dashboard_access(
        request: Request,
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_environment: str | None = Header(default=None, alias="X-Environment"),
    ) -> DashboardRequestContext:
        token = _bearer_token(authorization)
        environment = _parse_environment(x_environment, settings.environment)
        access = services.auth.authorize_request(
            token,
            environment=environment,
            ip_address=_client_ip(request),
        )
        if not access.authorized:
            raise HTTPException(
                status_code=access.status_code,
                detail={
                    "error_code": "dashboard_access_denied",
                    "message": access.reason or "dashboard access denied",
                },
            )
        assert access.username is not None
        return DashboardRequestContext(
            access=access,
            actor=ActorContext(username=access.username, ip_address=_client_ip(request)),
            environment=environment,
        )

    def require_mutation_context(
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> None:
        result = services.auth.validate_mutation_context(
            origin=request.headers.get("origin", ""),
            csrf_token=csrf_token or "",
            expected_csrf_token=settings.csrf_token,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=result.status_code,
                detail={
                    "error_code": "mutation_context_denied",
                    "message": result.reason or "mutation context denied",
                },
            )

    @router.get("/health")
    def health() -> dict[str, str]:
        """Public liveness endpoint.

        REQ: REQ-OBS-006
        """

        return {"status": "ok"}

    @router.get("/api/health")
    def api_health(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Authenticated dashboard health endpoint.

        REQ: REQ-OBS-005, REQ-OBS-006
        """

        return {
            "environment": context.environment.value,
            "status": "ok",
            "generated_at": _now(),
        }

    @router.get("/api/dashboard/summary")
    def dashboard_summary(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return a secret-safe dashboard summary.

        REQ: REQ-UI-004, REQ-WAL-005, REQ-EXE-016, REQ-OBS-005
        """

        config_snapshot = _current_config(context.environment)
        settings_payload = config_snapshot["settings"]
        preferences = services.runtime_status.user_preferences(
            username=context.access.username or context.actor.username,
            environment=context.environment,
        )
        market_data = services.runtime_status.market_data_pull(
            environment=context.environment,
            config_payload=settings_payload,
        )
        economics = services.runtime_status.economics_summary(
            environment=context.environment,
            config_payload=settings_payload,
            preferences=preferences["settings"],
        )
        credentials = services.runtime_status.credential_rows(context.environment)
        operations = services.runtime_status.operations_summary(context.environment)
        kill_switch_active = services.kill_switch.state(context.environment).active
        operations["killSwitch"] = "active" if kill_switch_active else "inactive"
        notifications = services.runtime_status.notification_summary(settings_payload)
        return {
            "data_source": "fastapi",
            "environment": context.environment.value,
            "generated_at": _now(),
            "status": {
                "health": "ok",
                "kill_switch_active": services.kill_switch.state(context.environment).active,
                "items": services.runtime_status.status_items(
                    environment=context.environment,
                    config_payload=settings_payload,
                ),
                "worker": services.runtime_status.worker_status(),
            },
            "config": config_snapshot,
            "wallet": {"credentials": credentials},
            "orders": {"items": operations["orderEvents"]},
            "models": {
                "providers": [
                    services.runtime_status.model_summary(
                        provider=ModelProvider.CLAUDE,
                        environment=context.environment,
                        config_payload=settings_payload,
                    ),
                    services.runtime_status.model_summary(
                        provider=ModelProvider.OPENAI,
                        environment=context.environment,
                        config_payload=settings_payload,
                    ),
                ]
            },
            "comparison": {"metrics": [], "degraded_sections": []},
            "notifications": notifications,
            "preferences": preferences,
            "marketData": market_data,
            "economics": economics,
            "operations": operations,
            "loop": services.runtime_status.loop_observability(
                environment=context.environment,
                config_payload=settings_payload,
                config_degraded=config_snapshot["degraded"],
                kill_switch_active=kill_switch_active,
            ),
            "audit": {"items": _audit_events()},
            "degraded_sections": [],
        }

    @router.get("/api/preferences")
    def preferences_current(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return saved dashboard display preferences for the current user.

        REQ: REQ-UI-004, REQ-OBS-005
        """

        return services.runtime_status.user_preferences(
            username=context.actor.username,
            environment=context.environment,
        )

    @router.put("/api/preferences")
    async def update_preferences(
        request: Request,
        response: Response,
        context: DashboardRequestContext = Depends(require_dashboard_access),
        _: None = Depends(require_mutation_context),
    ) -> dict[str, Any]:
        """Save dashboard display preferences for the current user.

        REQ: REQ-UI-004, REQ-OBS-004, REQ-OBS-005
        """

        payload = await request.json()
        try:
            return services.runtime_status.save_user_preferences(
                username=context.actor.username,
                ip_address=context.actor.ip_address,
                environment=context.environment,
                payload=payload.get("settings", payload),
            )
        except ValueError as exc:
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            return {"error_code": "preferences_validation_error", "message": str(exc)}

    @router.get("/api/config/current")
    def config_current(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return the active dashboard config snapshot.

        REQ: REQ-UI-005, REQ-UI-007
        """

        return _current_config(context.environment)

    @router.put("/api/config")
    async def update_config(
        request: Request,
        response: Response,
        context: DashboardRequestContext = Depends(require_dashboard_access),
        _: None = Depends(require_mutation_context),
    ) -> dict[str, Any]:
        """Persist authorized dashboard config patches.

        REQ: REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-OBS-004
        """

        payload = await request.json()
        environment = _parse_environment(payload.get("environment"), context.environment)
        patches = [
            ConfigPatchOperation(
                op=str(item.get("op")),
                path=str(item.get("path")),
                value=item.get("value"),
            )
            for item in payload.get("patches", [])
            if isinstance(item, dict)
        ]
        try:
            result = services.config.save_config_patches(
                actor=context.actor,
                access=context.access,
                environment=environment,
                expected_version=payload.get("expected_version"),
                version=payload.get("version") or _next_config_version(environment),
                patches=patches,
            )
        except ConfigConflictError as exc:
            response.status_code = status.HTTP_409_CONFLICT
            return {
                "error_code": "config_version_conflict",
                "message": str(exc),
                "current_version": services.config.current_version(environment),
            }
        except ConfigValidationError as exc:
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            return {"error_code": "config_validation_error", "message": str(exc)}
        except ConfigAuthorizationError as exc:
            response.status_code = status.HTTP_403_FORBIDDEN
            return {"error_code": "config_authorization_error", "message": str(exc)}

        return {
            "environment": environment.value,
            "previous_version": payload.get("expected_version"),
            "new_version": result.mutation.config_version["version"],
            "audit_event_id": result.mutation.audit_event["id"],
            "applies_on_next_loop": result.applies_on_next_loop,
        }

    @router.post("/api/kill-switch")
    async def activate_kill_switch(
        request: Request,
        context: DashboardRequestContext = Depends(require_dashboard_access),
        _: None = Depends(require_mutation_context),
    ) -> JSONResponse:
        """Activate the kill switch and expose cancel progress.

        REQ: REQ-UI-008, REQ-EXE-003, REQ-EXE-014, REQ-OBS-004
        """

        payload = await request.json()
        environment = _parse_environment(payload.get("environment"), context.environment)
        result = services.kill_switch.process_activation_request(
            access=context.access,
            actor=context.actor,
            environment=environment,
        )
        if not result.accepted:
            raise HTTPException(
                status_code=result.status_code,
                detail={
                    "error_code": "kill_switch_denied",
                    "message": result.reason or "kill switch denied",
                },
            )
        _persist_live_disabled(context, environment)
        body = {
            "active": result.state.active,
            "activated_by": result.state.activated_by,
            "activated_at": result.state.activated_at.isoformat()
            if result.state.activated_at
            else None,
            "reason": payload.get("reason"),
            "live_disabled": True,
            "cancel_summary": {
                "total_open_orders": 0,
                "attempted_cancels": 0,
                "terminal_cancels": 0,
                "failed_cancels": 0,
                "manual_review_orders": 0,
            },
            "open_order_states": [],
            "degraded_venues": [],
            "manual_review_required": False,
            "last_updated_at": _now(),
        }
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body)

    @router.get("/api/wallets/status")
    def wallets_status(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return wallet status without private material.

        REQ: REQ-WAL-005, REQ-UI-009
        """

        return {
            "environment": context.environment.value,
            "credentials": services.runtime_status.credential_rows(context.environment),
        }

    @router.get("/api/orders")
    def orders(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return a paginated order-event view.

        REQ: REQ-EXE-016
        """

        return {
            "environment": context.environment.value,
            "items": services.runtime_status.order_events(),
            "next_cursor": None,
        }

    @router.get("/api/models/{provider}/summary")
    def model_summary(
        provider: ModelProvider,
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return provider-specific dashboard summary data.

        REQ: REQ-UI-010
        """

        config_snapshot = _current_config(context.environment)
        return {
            "environment": context.environment.value,
            **services.runtime_status.model_summary(
                provider=provider,
                environment=context.environment,
                config_payload=config_snapshot["settings"],
            ),
        }

    @router.get("/api/comparison")
    def comparison(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return comparison metric view.

        REQ: REQ-UI-011
        """

        return {
            "environment": context.environment.value,
            "metrics": [],
            "degraded_sections": [],
        }

    @router.get("/api/notifications/settings")
    def notification_settings(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return notification settings.

        REQ: REQ-NOT-006
        """

        return {
            "environment": context.environment.value,
            **services.runtime_status.notification_summary(
                _current_config(context.environment)["settings"],
            ),
        }

    @router.get("/api/operations/summary")
    def operations_summary(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return operations dashboard state.

        REQ: REQ-UI-008, REQ-EXE-016, REQ-OBS-005
        """

        operations = services.runtime_status.operations_summary(context.environment)
        operations["killSwitch"] = (
            "active" if services.kill_switch.state(context.environment).active else "inactive"
        )
        return operations

    @router.get("/api/operations/runs")
    def operations_runs(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return recent manual and scheduled loop runs with stage details.

        REQ: REQ-UI-008, REQ-DAT-008, REQ-OBS-005
        """

        return {
            "environment": context.environment.value,
            "items": services.runtime_status.pipeline_runs(context.environment),
        }

    @router.post("/api/operations/manual-run")
    async def manual_run(
        request: Request,
        context: DashboardRequestContext = Depends(require_dashboard_access),
        _: None = Depends(require_mutation_context),
    ) -> JSONResponse:
        """Accept an operator-triggered manual loop request.

        REQ: REQ-UI-008, REQ-DAT-008, REQ-OBS-004, REQ-OBS-005
        """

        payload = await request.json()
        environment = _parse_environment(payload.get("environment"), context.environment)
        config_snapshot = _current_config(environment)
        result = services.runtime_status.trigger_manual_run(
            username=context.actor.username,
            ip_address=context.actor.ip_address,
            environment=environment,
            config_payload=config_snapshot["settings"],
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)

    @router.get("/api/market-data/latest")
    def market_data_latest(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return the latest dashboard-visible market-data pull.

        REQ: REQ-DAT-001, REQ-DAT-008, REQ-OBS-005
        """

        config_snapshot = _current_config(context.environment)
        return services.runtime_status.market_data_pull(
            environment=context.environment,
            config_payload=config_snapshot["settings"],
        )

    @router.get("/api/economics/summary")
    def economics_summary(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return profitability, token spend, and infrastructure cost view.

        REQ: REQ-UI-004, REQ-UI-010, REQ-CMP-002, REQ-OBS-005
        """

        config_snapshot = _current_config(context.environment)
        preferences = services.runtime_status.user_preferences(
            username=context.actor.username,
            environment=context.environment,
        )
        return services.runtime_status.economics_summary(
            environment=context.environment,
            config_payload=config_snapshot["settings"],
            preferences=preferences["settings"],
        )

    @router.get("/api/economics/history")
    def economics_history(
        month: str | None = None,
        limit: int = 31,
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return stored profitability snapshots for a month.

        REQ: REQ-UI-010, REQ-OBS-005
        """

        return services.runtime_status.economics_history(
            environment=context.environment,
            month_key=month,
            limit=limit,
        )

    @router.get("/api/audit-events")
    def audit_events(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return recent dashboard audit events.

        REQ: REQ-OBS-005
        """

        return {"environment": context.environment.value, "items": _audit_events()}

    def _current_config(environment: Environment) -> dict[str, Any]:
        reload_result = services.config.config_for_next_loop(environment)
        settings_payload = reload_result.snapshot.payload or services.runtime_status.runtime_config_payload()
        return {
            "environment": environment.value,
            "version": reload_result.snapshot.version,
            "settings": settings_payload,
            "degraded": reload_result.degraded,
        }

    def _persist_live_disabled(
        context: DashboardRequestContext,
        environment: Environment,
    ) -> None:
        services.config.save_config_patches(
            actor=context.actor,
            access=context.access,
            environment=environment,
            expected_version=services.config.current_version(environment),
            version=_next_config_version(environment),
            patches=[ConfigPatchOperation("replace", "live_enabled", False)],
        )

    def _next_config_version(environment: Environment) -> str:
        rows = [
            row
            for row in services.registry.state.rows("shared.config_versions")
            if row["environment"] == environment.value
        ]
        return f"v{len(rows) + 1}"

    def _audit_events() -> list[dict[str, Any]]:
        rows = services.registry.state.rows("shared.audit_events")[-20:]
        return [
            {
                "event_id": row["id"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "action": row["action"],
                "environment": row["environment"],
                "created_at": row["created_at"].isoformat(),
                "success": row["success"],
                "summary": row["metadata"].get("path") or row["action"],
            }
            for row in rows
        ]

    return router


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    marker = "Bearer "
    if not authorization.startswith(marker):
        return None
    return authorization.removeprefix(marker).strip() or None


def _parse_environment(raw: Any, default: Environment) -> Environment:
    if raw is None or raw == "":
        return default
    try:
        return Environment(str(raw))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "invalid_environment",
                "message": f"unsupported environment: {raw}",
            },
        ) from exc


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client is None:
        return "unknown"
    return request.client.host


def _now() -> str:
    return datetime.now(UTC).isoformat()
