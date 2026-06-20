"""Spec tests for FastAPI dashboard API routers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain import Environment
from app.main import AppSettings, create_app


def _client() -> tuple[TestClient, str]:
    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
    )
    app = create_app(settings)
    token = app.state.services.auth.create_session_token(username="yaw")
    return TestClient(app), token


def test_req_ui_001_03_fastapi_app_registers_dashboard_api_routes() -> None:
    """TST-REQ-UI-001-03: Validates REQ-UI-001

    Given: the backend app is created
    When: health and dashboard API routes are called
    Then: FastAPI exposes liveness and authenticated dashboard endpoints
    """
    client, token = _client()

    health = client.get("/health")
    dashboard = client.get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert dashboard.status_code == 200
    assert dashboard.json()["data_source"] == "fastapi"


def test_req_ui_001_04_app_settings_load_deployed_environment(monkeypatch) -> None:
    """TST-REQ-UI-001-04: Validates REQ-UI-001

    Given: deployed dashboard environment variables
    When: the FastAPI app loads default settings
    Then: auth, CSRF, origin, and environment settings come from the environment
    """
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DASHBOARD_ALLOWED_USERS", "yawetse,operator")
    monkeypatch.setenv("BACKEND_TOKEN_SIGNING_SECRET", "deploy-token-secret")
    monkeypatch.setenv("DASHBOARD_CSRF_TOKEN", "deploy-csrf")
    monkeypatch.setenv("NEXTAUTH_URL", "https://dashboard.example.com")

    app = create_app()
    settings = app.state.settings

    assert settings.environment == Environment.DEVELOPMENT
    assert settings.allowed_usernames == ("yawetse", "operator")
    assert settings.signing_secret == "deploy-token-secret"
    assert settings.csrf_token == "deploy-csrf"
    assert settings.trusted_origins == ("https://dashboard.example.com",)


def test_req_ui_003_03_dashboard_api_blocks_unauthenticated_and_unallowlisted_users() -> None:
    """TST-REQ-UI-003-03: Validates REQ-UI-003

    Given: unauthenticated and unallowlisted dashboard API callers
    When: protected endpoints are requested
    Then: the API returns 401 or 403 before returning protected data
    """
    client, _ = _client()
    denied_token = client.app.state.services.auth.create_session_token(username="denied")

    missing = client.get("/api/dashboard/summary")
    denied = client.get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {denied_token}"},
    )

    assert missing.status_code == 401
    assert denied.status_code == 403
    assert "config" not in missing.text
    assert "config" not in denied.text


def test_req_ui_004_03_authenticated_dashboard_api_returns_secret_safe_sections() -> None:
    """TST-REQ-UI-004-03: Validates REQ-UI-004

    Given: an authenticated allowlisted user
    When: dashboard summary data is requested
    Then: status, config, wallet, order, model, comparison, notification, and audit sections are returned without secrets
    """
    client, token = _client()

    response = client.get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert {
        "status",
        "config",
        "wallet",
        "orders",
        "models",
        "comparison",
        "notifications",
        "audit",
    }.issubset(payload)
    assert "secret" not in str(payload).lower()
    assert "private" not in str(payload).lower()


def test_req_ui_006_03_config_api_audits_authorized_mutations() -> None:
    """TST-REQ-UI-006-03: Validates REQ-UI-006

    Given: an authorized dashboard API caller changes config
    When: the config endpoint receives a valid patch
    Then: the API returns the new version and persists an audit event with actor metadata
    """
    client, token = _client()

    response = client.put(
        "/api/config",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3000",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "environment": "development",
            "version": "v1",
            "patches": [
                {
                    "op": "replace",
                    "path": "venues.polymarket_us.enabled",
                    "value": True,
                }
            ],
        },
    )
    audit_rows = client.app.state.services.registry.state.rows("shared.audit_events")

    assert response.status_code == 200
    assert response.json()["new_version"] == "v1"
    assert response.json()["applies_on_next_loop"] is True
    assert audit_rows[0]["actor"] == "yaw"
    assert audit_rows[0]["metadata"]["path"] == "venues.polymarket_us.enabled"


def test_req_ui_008_03_kill_switch_api_disables_live_and_returns_progress() -> None:
    """TST-REQ-UI-008-03: Validates REQ-UI-008

    Given: an authorized dashboard API caller activates the kill switch
    When: the kill switch endpoint is called
    Then: live trading is disabled and cancel progress is exposed in the response
    """
    client, token = _client()

    response = client.post(
        "/api/kill-switch",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3000",
            "X-CSRF-Token": "csrf-token",
        },
        json={"environment": "development", "reason": "operator stop"},
    )
    payload = response.json()

    assert response.status_code == 202
    assert payload["active"] is True
    assert payload["live_disabled"] is True
    assert payload["cancel_summary"]["total_open_orders"] == 0
    assert payload["manual_review_required"] is False
