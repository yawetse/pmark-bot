"""Offline startup timing diagnostics without application or credential data."""

from __future__ import annotations

from contextlib import contextmanager
import logging
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.main import AppSettings, create_app


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records
            if record.name == "uvicorn.error.startup"]


def test_req_obs_006_startup_timing_preserves_failure_without_logging_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """TST-REQ-OBS-006-STARTUP-01: time failed stages without sensitive data."""
    ticks = iter((10.0, 10.25))
    monkeypatch.setattr(main_module, "perf_counter", lambda: next(ticks))
    failure = ValueError("private-credential-and-payload-sentinel")
    with caplog.at_level(logging.INFO, logger="uvicorn.error.startup"):
        with pytest.raises(ValueError) as raised:
            with main_module._startup_stage("settings"):
                raise failure
    assert raised.value is failure
    assert _messages(caplog) == [
        "startup_stage stage=settings event=begin",
        "startup_stage stage=settings event=end outcome=failed elapsed_ms=250.000",
    ]
    assert all(record.exc_info is None for record in caplog.records
               if record.name == "uvicorn.error.startup")


def test_req_obs_006_startup_database_diagnostics_preserve_operation_order(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """TST-REQ-OBS-006-STARTUP-02: observe existing migration transaction unchanged."""
    operations: list[str] = []
    connection = object()

    @contextmanager
    def begin():
        operations.append("transaction_begin")
        yield connection
        operations.append("transaction_end")

    factory = SimpleNamespace(kw={"bind": SimpleNamespace(begin=begin)})

    def session_factory(database_url):
        assert database_url == "postgresql://private-database-sentinel"
        operations.append("session_factory")
        return factory

    def migrate(current):
        assert current is connection
        operations.append("migrations")

    def state(current):
        assert current is factory
        operations.append("persistent_state")
        return object()

    monkeypatch.setattr(main_module, "create_session_factory", session_factory)
    monkeypatch.setattr(main_module, "run_migrations", migrate)
    monkeypatch.setattr(main_module, "PersistentDatabaseState", state)
    monkeypatch.setattr(main_module, "RepositoryRegistry", lambda current: current)
    with caplog.at_level(logging.INFO, logger="uvicorn.error.startup"):
        main_module._repository_registry_from_settings(
            AppSettings(database_url="postgresql://private-database-sentinel")
        )
    assert operations == ["session_factory", "transaction_begin", "migrations",
                          "transaction_end", "persistent_state"]
    messages = _messages(caplog)
    assert len(messages) == 4
    assert "private-database-sentinel" not in "\n".join(messages)
    assert [message.split(" event=")[0] for message in messages] == [
        "startup_stage stage=database_session_factory",
        "startup_stage stage=database_session_factory",
        "startup_stage stage=database_migrations",
        "startup_stage stage=database_migrations",
    ]


def test_req_obs_006_factory_diagnostics_keep_health_and_log_only_safe_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TST-REQ-OBS-006-STARTUP-03: inspect real offline bootstrap and health contract."""
    settings = AppSettings(
        signing_secret="private-signing-sentinel",
        csrf_token="private-csrf-sentinel",
        runtime_env={"OPENAI_API_KEY": "private-provider-sentinel"},
    )
    with caplog.at_level(logging.INFO, logger="uvicorn.error.startup"):
        app = create_app(settings)
        with TestClient(app) as client:
            response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert app.state.settings is settings
    assert not app.state.settings.live_enabled
    assert not app.state.settings.background_worker_enabled
    assert app.state.worker_heartbeat_task is None
    messages = _messages(caplog)
    assert len(messages) == 12
    assert [message.split(" event=")[0] for message in messages] == [
        "startup_stage stage=settings", "startup_stage stage=settings",
        "startup_stage stage=services", "startup_stage stage=repository",
        "startup_stage stage=repository", "startup_stage stage=services",
        "startup_stage stage=startup_heartbeat", "startup_stage stage=startup_heartbeat",
        "startup_stage stage=observability", "startup_stage stage=observability",
        "startup_stage stage=dashboard_events", "startup_stage stage=dashboard_events",
    ]
    assert all("private-" not in message for message in messages)
    assert all(record.args and all(isinstance(value, (str, float)) for value in record.args)
               for record in caplog.records if record.name == "uvicorn.error.startup")
