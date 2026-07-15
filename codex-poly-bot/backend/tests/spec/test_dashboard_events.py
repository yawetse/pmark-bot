"""Spec tests for event-driven dashboard delivery."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.api import dashboard as dashboard_api
from app.db import migration_plan
from app.domain import Environment
from app.main import AppSettings, create_app
from app.services.dashboard_event_service import DashboardChange, DashboardEventBroker


def test_req_db_010_01_migrations_publish_coalescible_dashboard_invalidations() -> None:
    """TST-REQ-DB-010-01: Validates REQ-DB-010."""

    sql = "\n".join(migration_plan().sql)

    assert "pg_notify(" in sql
    assert "'codex_dashboard_events'" in sql
    assert "shared.config_versions" in sql
    assert "shared.job_runs" in sql
    assert "shared.venue_portfolio_snapshots" in sql
    assert "shared.venue_confirmed_fills" in sql
    assert "shared.scanner_candidates" not in sql.split("notify_dashboard_change", 1)[-1]
    assert "shared.stock_bars" not in sql.split("notify_dashboard_change", 1)[-1]
    assert "NULLIF(row_data ->> 'username', '__shared__')" in sql


def test_req_db_010_02_event_broker_scopes_and_coalesces_subscribers() -> None:
    """TST-REQ-DB-010-02: Validates REQ-DB-010."""

    async def scenario() -> None:
        broker = DashboardEventBroker()
        async with (
            broker.subscribe(environment="production", username="yaw") as yaw,
            broker.subscribe(environment="production", username="alex") as alex,
            broker.subscribe(environment="development", username="yaw") as development,
        ):
            broker.publish(DashboardChange(environment="production", username="yaw"))
            assert await asyncio.wait_for(yaw.get(), timeout=0.2) == DashboardChange(
                environment="production",
                username="yaw",
            )
            for subscription in (alex, development):
                try:
                    await asyncio.wait_for(subscription.get(), timeout=0.02)
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("a scoped dashboard event reached the wrong subscriber")

            broker.publish(DashboardChange(environment="production"))
            broker.publish(DashboardChange(environment="production"))
            assert await asyncio.wait_for(yaw.get(), timeout=0.2) == DashboardChange(
                environment="production"
            )
            assert await asyncio.wait_for(alex.get(), timeout=0.2) == DashboardChange(
                environment="production"
            )
            assert yaw.empty()
            assert alex.empty()

    asyncio.run(scenario())


def test_req_ui_015_02_event_broker_without_postgres_uses_recovery_path() -> None:
    """TST-REQ-UI-015-02: Validates REQ-UI-015."""

    broker = DashboardEventBroker()

    assert broker.source_ready is False
    assert asyncio.run(broker.wait_until_ready(timeout=0.01)) is False


def test_req_ui_015_01_websocket_refreshes_only_after_matching_change(monkeypatch) -> None:
    """TST-REQ-UI-015-01: Validates REQ-UI-015."""

    settings = AppSettings(
        allowed_usernames=("yaw", "alex"),
        signing_secret="test-secret",
        environment=Environment.DEVELOPMENT,
    )
    app = create_app(settings)
    token = app.state.services.auth.create_session_token(username="yaw")
    worker_calls = 0
    original_worker_status = app.state.services.runtime_status.worker_status

    def tracked_worker_status():
        nonlocal worker_calls
        worker_calls += 1
        return original_worker_status()

    monkeypatch.setattr(app.state.services.runtime_status, "worker_status", tracked_worker_status)
    monkeypatch.setattr(dashboard_api, "DASHBOARD_WEBSOCKET_HEARTBEAT_SECONDS", 0.05)

    async def event_source_ready(*, timeout: float) -> bool:
        return True

    monkeypatch.setattr(
        app.state.services.dashboard_events,
        "wait_until_ready",
        event_source_ready,
    )

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/dashboard/events?token={token}&environment=development"
        ) as websocket:
            initial = websocket.receive_json()
            assert initial["type"] == "dashboard_snapshot"
            assert "portfolio" in initial["data"]
            assert worker_calls == 1

            heartbeat = websocket.receive_json()
            assert heartbeat["type"] == "heartbeat"
            assert worker_calls == 1

            app.state.services.dashboard_events.publish(
                DashboardChange(environment="development", username="alex")
            )
            next_heartbeat = websocket.receive_json()
            assert next_heartbeat["type"] == "heartbeat"
            assert worker_calls == 1

            app.state.services.dashboard_events.publish(
                DashboardChange(environment="development", username="yaw")
            )
            changed = websocket.receive_json()
            assert changed["type"] == "dashboard_snapshot"
            assert "portfolio" in changed["data"]
            assert worker_calls == 2

            websocket.send_text("close")
