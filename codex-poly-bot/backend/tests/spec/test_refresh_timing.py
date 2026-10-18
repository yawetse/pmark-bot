"""Bounded, data-free portfolio timing diagnostic behavior."""

import asyncio
from datetime import UTC, datetime, timedelta
import logging
from time import sleep
from types import SimpleNamespace

import pytest

from app.domain import Environment
from app.main import AppSettings, _RefreshTimingDiagnostics, _portfolio_refresh_loop
from app.services.config_service import default_config_payload


def test_timing_diagnostics_requires_explicit_expiry_and_clamps_to_24_hours() -> None:
    assert not _RefreshTimingDiagnostics.from_settings(AppSettings()).active()
    assert not _RefreshTimingDiagnostics.from_settings(
        AppSettings(runtime_env={"PORTFOLIO_REFRESH_DIAGNOSTICS_UNTIL": "tomorrow"})
    ).active()
    now = datetime.now(UTC)
    diagnostics = _RefreshTimingDiagnostics.from_settings(
        AppSettings(
            runtime_env={
                "PORTFOLIO_REFRESH_DIAGNOSTICS_UNTIL": (
                    now + timedelta(days=7)
                ).isoformat()
            }
        )
    )
    assert diagnostics.active()
    assert diagnostics.deadline is not None
    assert diagnostics.deadline <= now + timedelta(hours=24, seconds=1)


def test_slow_timing_logs_are_rate_limited_and_contain_only_phase_metrics(
    monkeypatch, caplog
) -> None:
    diagnostics = _RefreshTimingDiagnostics(deadline=datetime.now(UTC) + timedelta(hours=1))
    monotonic = [1000.0]
    monkeypatch.setattr("app.main.perf_counter", lambda: monotonic[0])
    with caplog.at_level(logging.WARNING, logger="app.main"):
        diagnostics.record("portfolio_refresh", 89_999, "ok")
        diagnostics.record("portfolio_refresh", 90_000, "ok")
        diagnostics.record("funding_tick", 120_000, "failed")
        monotonic[0] += 901
        diagnostics.record("funding_tick", 100, "failed")
        diagnostics.emitted_logs = 96
        monotonic[0] += 901
        diagnostics.record("config_reload", 100_000, "ok")

    assert len(caplog.records) == 2
    assert "phase=portfolio_refresh outcome=ok elapsed_ms=90000" in caplog.text
    assert "phase=funding_tick outcome=failed elapsed_ms=100" in caplog.text
    assert "account" not in caplog.text.lower()


def test_inflight_refresh_reports_phase_without_provider_data(monkeypatch, caplog) -> None:
    monkeypatch.setattr("app.main._REFRESH_SLOW_SECONDS", 0.02)

    class Runtime:
        def refresh_venue_portfolio(self, environment):
            del environment
            sleep(0.06)

        def record_worker_heartbeat(self, **kwargs):
            return kwargs

    class Config:
        def config_for_next_loop(self, environment, username=None):
            del environment, username
            return SimpleNamespace(
                snapshot=SimpleNamespace(payload=default_config_payload(), version="v1")
            )

    class Funding:
        def run_tick(self, **kwargs):
            del kwargs
            return {"status": "completed"}

    async def stop_after_first_tick(_delay):
        raise StopAsyncIteration

    monkeypatch.setattr("app.main.asyncio.sleep", stop_after_first_tick)
    services = SimpleNamespace(
        runtime_status=Runtime(),
        config=Config(),
        funding=Funding(),
        kill_switch=SimpleNamespace(state=lambda environment: SimpleNamespace(active=False)),
    )
    settings = AppSettings(
        allowed_usernames=("yaw",),
        runtime_env={
            "PORTFOLIO_REFRESH_DIAGNOSTICS_UNTIL": (
                datetime.now(UTC) + timedelta(hours=1)
            ).isoformat()
        },
    )

    with caplog.at_level(logging.WARNING, logger="app.main"):
        with pytest.raises(StopAsyncIteration):
            asyncio.run(
                _portfolio_refresh_loop(
                    services=services,
                    settings=settings,
                    environment=Environment.DEVELOPMENT,
                    interval_seconds=60,
                )
            )

    assert caplog.text.count("portfolio_refresh_timing") == 1
    assert "phase=portfolio_refresh outcome=running" in caplog.text
    assert "account" not in caplog.text.lower()
