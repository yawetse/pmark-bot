"""Persistence failures must close streams without leaking internal error details."""

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db import PersistenceUnavailableError
from app.domain import Environment
from app.main import AppSettings, create_app
from app.services.dashboard_event_service import DashboardChange


@pytest.mark.parametrize("after_initial_snapshot", (False, True))
def test_websocket_persistence_failure_closes_retryably_without_healthy_fallback(
    monkeypatch, caplog, after_initial_snapshot,
):
    app = create_app(AppSettings(allowed_usernames=("yaw",), signing_secret="test-secret",
                                 environment=Environment.DEVELOPMENT))
    services = app.state.services
    token = services.auth.create_session_token(username="yaw")

    async def ready(*, timeout):
        return True

    monkeypatch.setattr(services.dashboard_events, "wait_until_ready", ready)
    original = services.kill_switch.state
    fail = not after_initial_snapshot

    def state(environment):
        if fail:
            raise PersistenceUnavailableError("private-diagnostic-marker")
        return original(environment)

    monkeypatch.setattr(services.kill_switch, "state", state)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/dashboard/events?token={token}&environment=development"
        ) as websocket:
            if after_initial_snapshot:
                assert websocket.receive_json()["type"] == "dashboard_snapshot"
                fail = True
                services.dashboard_events.publish(DashboardChange(environment="development"))
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_json()
            assert closed.value.code == 1013
            assert closed.value.reason == "Dashboard data is temporarily unavailable."
    assert "private-diagnostic-marker" not in caplog.text
    assert token not in caplog.text


def test_unaccepted_websocket_persistence_failure_is_closed_without_http_response(caplog):
    app = create_app(AppSettings(signing_secret="test-secret"))

    @app.websocket("/test-persistence-failure")
    async def failing_stream(websocket: WebSocket):
        raise PersistenceUnavailableError("private-diagnostic-marker")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/test-persistence-failure"):
                pass
    assert closed.value.code == 1013
    assert "private-diagnostic-marker" not in caplog.text


def test_persistence_handler_does_not_close_an_already_closed_websocket():
    app = create_app(AppSettings(signing_secret="test-secret"))

    @app.websocket("/test-closed-stream")
    async def failing_stream(websocket: WebSocket):
        await websocket.accept()
        await websocket.close(code=1000)
        raise PersistenceUnavailableError("private-diagnostic-marker")

    with TestClient(app) as client:
        with client.websocket_connect("/test-closed-stream") as websocket:
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_json()
            assert closed.value.code == 1000
