"""Dashboard API router implementations.

REQ: REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-005,
REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-009, REQ-UI-010,
REQ-UI-011, REQ-WAL-005, REQ-EXE-003, REQ-EXE-014, REQ-EXE-016,
REQ-OBS-004, REQ-OBS-005, REQ-OBS-006
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse

from app.db import PersistenceUnavailableError, normalize_config_username
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

        config_snapshot = _current_config(context.environment, context.actor.username)
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

        return _current_config(context.environment, context.actor.username)

    @router.post("/api/config")
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
                version=payload.get("version") or _next_config_version(environment, context.actor.username),
                patches=patches,
                username=context.actor.username,
            )
        except ConfigConflictError as exc:
            response.status_code = status.HTTP_409_CONFLICT
            return {
                "error_code": "config_version_conflict",
                "message": str(exc),
                "current_version": services.config.current_version(environment, username=context.actor.username),
            }
        except ConfigValidationError as exc:
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            return {"error_code": "config_validation_error", "message": str(exc)}
        except ConfigAuthorizationError as exc:
            response.status_code = status.HTTP_403_FORBIDDEN
            return {"error_code": "config_authorization_error", "message": str(exc)}
        except PersistenceUnavailableError:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "error_code": "config_persistence_unavailable",
                "message": "Config persistence is unavailable, so settings were not saved.",
            }

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

        config_snapshot = _current_config(context.environment, context.actor.username)
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
                _current_config(context.environment, context.actor.username)["settings"],
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

    @router.get("/api/operations/tick-schedule")
    def operations_tick_schedule(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return the last tick time and next expected tick time."""

        config_snapshot = _current_config(context.environment, context.actor.username)
        return services.runtime_status.tick_schedule(
            environment=context.environment,
            config_payload=config_snapshot["settings"],
        )

    @router.get("/api/operations/tick-summary")
    def tick_summary(
        window_minutes: int = 24 * 60,
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return a cached daily or custom-window tick summary.

        REQ: REQ-UI-004, REQ-UI-008, REQ-OBS-005
        """

        return services.runtime_status.tick_summary(
            context.environment,
            window_minutes=window_minutes,
        )

    @router.post("/api/operations/tick-summary")
    async def refresh_tick_summary(
        request: Request,
        context: DashboardRequestContext = Depends(require_dashboard_access),
        _: None = Depends(require_mutation_context),
    ) -> dict[str, Any]:
        """Force a tick summary refresh on operator request.

        REQ: REQ-UI-004, REQ-UI-008, REQ-OBS-004, REQ-OBS-005
        """

        payload = await request.json()
        return services.runtime_status.tick_summary(
            context.environment,
            window_minutes=int(payload.get("window_minutes", 24 * 60)),
            force_refresh=True,
        )

    @router.get("/api/data/explorer")
    def data_explorer(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return read-only datasets available to the dashboard data explorer."""

        return services.runtime_status.data_explorer(context.environment)

    @router.get("/api/data/query")
    def data_query_get(
        query: str = "select * from market_data_pulls limit 25",
        limit: int = 100,
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Run a safe read-only data explorer query."""

        try:
            return services.runtime_status.query_data(
                environment=context.environment,
                query=query,
                default_limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error_code": "invalid_data_query", "message": str(exc)},
            ) from exc

    @router.post("/api/data/query")
    async def data_query_post(
        request: Request,
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Run a safe read-only data explorer query from a workbench body."""

        payload = await request.json()
        try:
            return services.runtime_status.query_data(
                environment=context.environment,
                query=str(payload.get("query") or "select * from market_data_pulls limit 25"),
                default_limit=int(payload.get("limit", 100)),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error_code": "invalid_data_query", "message": str(exc)},
            ) from exc

    @router.post("/api/data/query/generate")
    async def data_query_generate(
        request: Request,
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Generate a safe read-only query from natural language."""

        payload = await request.json()
        return services.runtime_status.generate_data_query(
            environment=context.environment,
            prompt=str(payload.get("prompt") or ""),
        )

    @router.get("/api/dashboard/realtime-snapshot")
    def dashboard_realtime_snapshot(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return the same tick-focused payload sent over WebSocket."""

        return _realtime_snapshot(context)

    @router.websocket("/api/dashboard/events")
    async def dashboard_events(
        websocket: WebSocket,
        token: str | None = None,
        environment: str | None = None,
    ) -> None:
        """Stream tick-focused dashboard snapshots over WebSocket."""

        context = _websocket_context(websocket, token, environment)
        if not context.access.authorized:
            await websocket.close(code=4403 if context.access.authenticated else 4401)
            return
        await websocket.accept()
        refresh_seconds = 5
        try:
            while True:
                await websocket.send_json(
                    {
                        "type": "dashboard_snapshot",
                        "data": _realtime_snapshot(context),
                    }
                )
                try:
                    message = await asyncio.wait_for(websocket.receive_text(), timeout=refresh_seconds)
                except TimeoutError:
                    continue
                if message.strip().lower() == "close":
                    await websocket.close(code=1000)
                    return
        except WebSocketDisconnect:
            return

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

    @router.get("/api/operations/runs/{run_id}")
    def operations_run_detail(
        run_id: str,
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return one loop run with step-linked records.

        REQ: REQ-UI-008, REQ-DAT-008, REQ-OBS-005
        """

        payload = services.runtime_status.pipeline_run_detail(context.environment, run_id)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error_code": "pipeline_run_not_found",
                    "message": "pipeline run was not found for this environment",
                },
            )
        return payload

    @router.get("/api/scenario/analyze")
    def scenario_analyze_get(
        run_id: str | None = None,
        step_key: str | None = None,
        prompt: str | None = None,
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return a scenario walkthrough for the latest or selected tick."""

        config_snapshot = _current_config(context.environment, context.actor.username)
        return services.runtime_status.scenario_analysis(
            environment=context.environment,
            config_payload=config_snapshot["settings"],
            run_id=run_id,
            step_key=step_key,
            prompt=prompt,
        )

    @router.post("/api/scenario/analyze")
    async def scenario_analyze_post(
        request: Request,
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return a scenario walkthrough with optional config test values."""

        payload = await request.json()
        config_snapshot = _current_config(context.environment, context.actor.username)
        return services.runtime_status.scenario_analysis(
            environment=context.environment,
            config_payload=config_snapshot["settings"],
            run_id=payload.get("runId"),
            step_key=payload.get("stepKey"),
            prompt=payload.get("prompt"),
            config_overrides=payload.get("configOverrides") or [],
        )

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
        mode = str(payload.get("mode") or payload.get("run_mode") or "full_dry_run")
        config_snapshot = _current_config(environment, context.actor.username)
        result = services.runtime_status.trigger_manual_run(
            username=context.actor.username,
            ip_address=context.actor.ip_address,
            environment=environment,
            config_payload=config_snapshot["settings"],
            run_mode=mode,
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)

    @router.get("/api/market-data/latest")
    def market_data_latest(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return the latest dashboard-visible market-data pull.

        REQ: REQ-DAT-001, REQ-DAT-008, REQ-OBS-005
        """

        config_snapshot = _current_config(context.environment, context.actor.username)
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

        config_snapshot = _current_config(context.environment, context.actor.username)
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

    @router.post("/api/economics/ai-usage-import")
    async def ai_usage_import(
        request: Request,
        context: DashboardRequestContext = Depends(require_dashboard_access),
        _: None = Depends(require_mutation_context),
    ) -> JSONResponse:
        """Trigger provider-side token usage import.

        REQ: REQ-LLM-002, REQ-UI-010, REQ-OBS-005
        """

        payload = await request.json()
        environment = _parse_environment(payload.get("environment"), context.environment)
        provider = _parse_model_provider(payload.get("provider"))
        now = datetime.now(UTC)
        period_start = _parse_api_datetime(payload.get("periodStart")) or now - timedelta(days=1)
        period_end = _parse_api_datetime(payload.get("periodEnd")) or now
        result = services.runtime_status.trigger_ai_usage_import(
            username=context.actor.username,
            ip_address=context.actor.ip_address,
            environment=environment,
            provider=provider,
            period_start=period_start,
            period_end=period_end,
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)

    @router.get("/api/audit-events")
    def audit_events(
        context: DashboardRequestContext = Depends(require_dashboard_access),
    ) -> dict[str, Any]:
        """Return recent dashboard audit events.

        REQ: REQ-OBS-005
        """

        return {"environment": context.environment.value, "items": _audit_events()}

    def _current_config(environment: Environment, username: str | None = None) -> dict[str, Any]:
        reload_result = services.config.config_for_next_loop(environment, username=username)
        settings_payload = reload_result.snapshot.payload or services.runtime_status.runtime_config_payload()
        return {
            "environment": environment.value,
            "username": username,
            "config_owner": normalize_config_username(username),
            "version": reload_result.snapshot.version,
            "settings": settings_payload,
            "degraded": reload_result.degraded,
        }

    def _realtime_snapshot(context: DashboardRequestContext) -> dict[str, Any]:
        config_snapshot = _current_config(context.environment, context.actor.username)
        settings_payload = config_snapshot["settings"]
        operations = services.runtime_status.operations_summary(context.environment)
        operations["killSwitch"] = (
            "active" if services.kill_switch.state(context.environment).active else "inactive"
        )
        return {
            "environment": context.environment.value,
            "generatedAt": _now(),
            "operations": operations,
            "marketData": services.runtime_status.market_data_pull(
                environment=context.environment,
                config_payload=settings_payload,
            ),
            "tickSchedule": services.runtime_status.tick_schedule(
                environment=context.environment,
                config_payload=settings_payload,
            ),
            "loop": services.runtime_status.loop_observability(
                environment=context.environment,
                config_payload=settings_payload,
                config_degraded=config_snapshot["degraded"],
                kill_switch_active=services.kill_switch.state(context.environment).active,
            ),
        }

    def _websocket_context(
        websocket: WebSocket,
        token: str | None,
        raw_environment: str | None,
    ) -> DashboardRequestContext:
        environment = _parse_environment(raw_environment, settings.environment)
        ip_address = _websocket_client_ip(websocket)
        access = services.auth.authorize_request(
            token,
            environment=environment,
            ip_address=ip_address,
        )
        return DashboardRequestContext(
            access=access,
            actor=ActorContext(username=access.username or "unknown", ip_address=ip_address),
            environment=environment,
        )

    def _persist_live_disabled(
        context: DashboardRequestContext,
        environment: Environment,
    ) -> None:
        services.config.save_config_patches(
            actor=context.actor,
            access=context.access,
            environment=environment,
            expected_version=services.config.current_version(environment, username=context.actor.username),
            version=_next_config_version(environment, context.actor.username),
            patches=[ConfigPatchOperation("replace", "live_enabled", False)],
            username=context.actor.username,
        )

    def _next_config_version(environment: Environment, username: str | None = None) -> str:
        owner = normalize_config_username(username)
        rows = [
            row
            for row in services.registry.state.rows("shared.config_versions")
            if row["environment"] == environment.value
            and normalize_config_username(row.get("username")) == owner
        ]
        versions = {str(row["version"]) for row in rows}
        numeric_versions = [
            int(version[1:])
            for version in versions
            if version.startswith("v") and version[1:].isdigit()
        ]
        next_number = max(numeric_versions, default=len(rows)) + 1
        while f"v{next_number}" in versions:
            next_number += 1
        return f"v{next_number}"

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


def _parse_model_provider(raw: Any) -> ModelProvider:
    value = str(raw or ModelProvider.OPENAI.value).strip().lower()
    try:
        return ModelProvider(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "invalid_model_provider",
                "message": f"unsupported model provider: {raw}",
            },
        ) from exc


def _parse_api_datetime(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "invalid_datetime",
                "message": f"invalid ISO datetime: {raw}",
            },
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client is None:
        return "unknown"
    return request.client.host


def _websocket_client_ip(websocket: WebSocket) -> str:
    forwarded_for = websocket.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if websocket.client is None:
        return "unknown"
    return websocket.client.host


def _now() -> str:
    return datetime.now(UTC).isoformat()
