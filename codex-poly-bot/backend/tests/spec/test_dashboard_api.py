"""Spec tests for FastAPI dashboard API routers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.adapters.aws import AwsBillingCost, CostExplorerBillingAdapter, InMemorySesEmailAdapter
from app.db import PersistenceUnavailableError
from app.domain import Environment, ModelProvider, Venue
from app.main import AppSettings, create_app
from app.services.market_data_provider import MarketDataProviderResult
from app.services.runtime_status_service import (
    DASHBOARD_DATA_EXPLORER_ROW_LIMIT,
    DASHBOARD_EXECUTION_INTENT_ROW_LIMIT,
    DASHBOARD_EXIT_INTENT_ROW_LIMIT,
    DASHBOARD_PIPELINE_RECORD_ROW_LIMIT,
    DASHBOARD_PIPELINE_RUN_ROW_LIMIT,
    DASHBOARD_PIPELINE_STEP_ROW_LIMIT,
    DASHBOARD_REASONING_OUTPUT_ROW_LIMIT,
    DASHBOARD_STRATEGY_OUTPUT_ROW_LIMIT,
    DASHBOARD_STRATEGY_VOTE_ROW_LIMIT,
    DATA_EXPLORER_DATASETS,
    _config_for_manual_mode,
)
from app.services.stock_universe_refresh_service import (
    StaticStockUniverseSource,
    StockUniverseRefreshService,
)


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


def test_req_obs_005_worker_status_treats_completed_scheduler_statuses_as_current() -> None:
    """TST-REQ-OBS-005-07: Validates REQ-OBS-005

    Given: the scheduled worker records a completed market-data outcome
    When: the dashboard evaluates scheduler liveness
    Then: fresh non-failure outcomes keep the worker gate open
    """
    settings = AppSettings(environment=Environment.DEVELOPMENT)
    app = create_app(settings)
    now = datetime.now(UTC)
    app.state.services.registry.state.rows("shared.job_runs").clear()
    app.state.services.registry.state.insert(
        "shared.job_runs",
        {
            "id": "scheduled-partial",
            "job_name": app.state.services.runtime_status.WORKER_JOB_NAME,
            "status": "partial",
            "heartbeat_at": now,
            "metadata": {"message": "scheduled provider market data ingestion"},
            "created_at": now,
        },
    )

    worker = app.state.services.runtime_status.worker_status()

    assert worker["state"] == "ok"
    assert worker["value"] == "Scheduler heartbeat current"
    assert worker["heartbeatStatus"] == "partial"


def test_req_obs_005_worker_status_blocks_stale_scheduler_heartbeats() -> None:
    """TST-REQ-OBS-005-08: Validates REQ-OBS-005

    Given: the scheduled worker has not recorded a recent heartbeat
    When: the dashboard evaluates scheduler liveness
    Then: stale rows still block the live trading loop
    """
    settings = AppSettings(environment=Environment.DEVELOPMENT)
    app = create_app(settings)
    stale = datetime.now(UTC) - timedelta(seconds=181)
    app.state.services.registry.state.rows("shared.job_runs").clear()
    app.state.services.registry.state.insert(
        "shared.job_runs",
        {
            "id": "scheduled-stale",
            "job_name": app.state.services.runtime_status.WORKER_JOB_NAME,
            "status": "pulled",
            "heartbeat_at": stale,
            "metadata": {"message": "scheduled provider market data ingestion"},
            "created_at": stale,
        },
    )

    worker = app.state.services.runtime_status.worker_status()

    assert worker["state"] == "blocked"
    assert worker["value"] == "Worker heartbeat stale"
    assert worker["heartbeatStatus"] == "pulled"


def test_req_obs_005_worker_status_exposes_bounded_scheduler_failure_detail() -> None:
    """TST-REQ-OBS-005-09: Validates REQ-OBS-005

    Given: the scheduled worker records a safe bounded failure detail
    When: the dashboard evaluates scheduler liveness
    Then: the ingestion status identifies the failed operation
    """
    settings = AppSettings(environment=Environment.DEVELOPMENT)
    app = create_app(settings)
    now = datetime.now(UTC)
    app.state.services.registry.state.rows("shared.job_runs").clear()
    app.state.services.registry.state.insert(
        "shared.job_runs",
        {
            "id": "scheduled-failure",
            "job_name": app.state.services.runtime_status.WORKER_JOB_NAME,
            "status": "failed",
            "heartbeat_at": now,
            "metadata": {
                "message": (
                    "scheduler tick failed: PersistenceUnavailableError: "
                    "Postgres persistence is unavailable for shared.reasoning_runs"
                )
            },
            "created_at": now,
        },
    )

    worker = app.state.services.runtime_status.worker_status()

    assert worker["state"] == "blocked"
    assert worker["value"] == (
        "scheduler tick failed: PersistenceUnavailableError: "
        "Postgres persistence is unavailable for shared.reasoning_runs"
    )
    assert worker["heartbeatStatus"] == "failed"


class FakeAwsBillingAdapter:
    def dashboard_costs(self, *, environment: Environment) -> AwsBillingCost:
        return AwsBillingCost(
            daily_cost_usd=Decimal("2.50"),
            month_to_date_cost_usd=Decimal("42.00"),
            daily_start=date(2026, 6, 24),
            daily_end=date(2026, 6, 25),
            month_start=date(2026, 6, 1),
            month_end=date(2026, 6, 25),
            estimated=True,
            source="aws cost explorer",
            scope="tagged",
            message="Cost Explorer returned test cost.",
        )


class FakeMarketDataFetcher:
    def __init__(self, results: dict[str, MarketDataProviderResult]) -> None:
        self.results = results
        self.calls: list[dict[str, str]] = []

    def fetch(
        self,
        *,
        venue: str,
        config_payload: dict,
        pulled_at: datetime,
    ) -> MarketDataProviderResult:
        self.calls.append(
            {
                "venue": venue,
                "default_selected_venue": str(config_payload.get("default_selected_venue")),
                "pulled_at": pulled_at.isoformat(),
            }
        )
        return self.results[venue]


def test_req_ui_008_08_dashboard_read_paths_use_bounded_store_reads(monkeypatch) -> None:
    """TST-REQ-UI-008-08: Validates REQ-UI-008, REQ-DAT-008, and REQ-OBS-005

    Given: dashboard data is read from the persistent store
    When: Run, Markets, and What-if summary data is loaded
    Then: the dashboard reads recent environment-scoped windows instead of full tables
    """

    settings = AppSettings(environment=Environment.DEVELOPMENT)
    app = create_app(settings)
    state = app.state.services.registry.state
    original_rows = state.rows
    calls: list[tuple[str, dict]] = []

    def observed_rows(table_name: str, *args, **kwargs):
        calls.append((table_name, kwargs))
        return original_rows(table_name, *args, **kwargs)

    monkeypatch.setattr(state, "rows", observed_rows)
    service = app.state.services.runtime_status
    config_payload = service.runtime_config_payload()
    calls.clear()

    explorer = service.data_explorer(Environment.DEVELOPMENT)
    assert explorer["datasets"]
    assert calls == []

    service.query_data(
        environment=Environment.DEVELOPMENT,
        query="select * from market_data_pulls limit 25",
    )
    service.market_data_pull(
        environment=Environment.DEVELOPMENT,
        config_payload=config_payload,
    )
    service.pipeline_runs(Environment.DEVELOPMENT, limit=20)

    environment_filter = {"environment": Environment.DEVELOPMENT.value}
    assert any(
        table_name == service.MARKET_DATA_PULLS_TABLE
        and kwargs.get("limit") == 25
        and kwargs.get("newest_first") is True
        and kwargs.get("filters") == environment_filter
        for table_name, kwargs in calls
    )
    assert all(
        kwargs.get("limit") != DASHBOARD_DATA_EXPLORER_ROW_LIMIT
        for table_name, kwargs in calls
        if table_name in {metadata["table"] for metadata in DATA_EXPLORER_DATASETS.values()}
    )
    assert any(
        table_name == service.MARKET_DATA_PULLS_TABLE
        and kwargs.get("limit") == 1
        and kwargs.get("newest_first") is True
        and kwargs.get("filters", {}).get("environment") == Environment.DEVELOPMENT.value
        and kwargs.get("filters", {}).get("venue")
        for table_name, kwargs in calls
    )
    assert any(
        table_name == service.PIPELINE_RUNS_TABLE
        and kwargs.get("limit") == 20
        and kwargs.get("newest_first") is True
        and kwargs.get("filters") == environment_filter
        for table_name, kwargs in calls
    )
    assert any(
        table_name == service.PIPELINE_STEPS_TABLE
        and kwargs.get("limit") == 200
        and kwargs.get("newest_first") is True
        and kwargs.get("filters") == environment_filter
        for table_name, kwargs in calls
    )


def test_req_ui_008_11_activity_reads_compact_run_metadata_only(monkeypatch) -> None:
    """Activity must not load step JSON or detailed operations tables."""

    settings = AppSettings(environment=Environment.DEVELOPMENT)
    app = create_app(settings)
    service = app.state.services.runtime_status
    state = app.state.services.registry.state
    original_rows = state.rows
    calls: list[tuple[str, dict]] = []

    def observed_rows(table_name: str, *args, **kwargs):
        calls.append((table_name, kwargs))
        return original_rows(table_name, *args, **kwargs)

    monkeypatch.setattr(state, "rows", observed_rows)

    summary = service.operations_summary(
        Environment.DEVELOPMENT,
        include_runs=True,
    )

    assert summary["pipelineRuns"] == []
    assert any(
        table_name == service.PIPELINE_RUNS_TABLE
        and kwargs.get("limit") == 10
        and kwargs.get("newest_first") is True
        and kwargs.get("filters") == {
            "environment": Environment.DEVELOPMENT.value,
        }
        for table_name, kwargs in calls
    )
    assert not any(
        table_name == service.PIPELINE_STEPS_TABLE
        for table_name, _ in calls
    )
    assert not any(
        table_name == service.SCANNER_RUNS_TABLE
        for table_name, _ in calls
    )
    detailed_tables = {
        service.REASONING_RUNS_TABLE,
        service.REASONING_OUTPUTS_TABLE,
        service.STRATEGY_CONSENSUS_RUNS_TABLE,
        service.STRATEGY_VOTES_TABLE,
        service.STRATEGY_CONSENSUS_OUTPUTS_TABLE,
        service.EXECUTION_RUNS_TABLE,
        service.ORDER_INTENTS_TABLE,
        service.EXIT_RUNS_TABLE,
        service.EXIT_INTENTS_TABLE,
    }
    assert not any(table_name in detailed_tables for table_name, _ in calls)


def test_req_ui_008_10_operations_details_read_only_the_latest_run(monkeypatch) -> None:
    """Detailed activity must not load full historical stage tables."""

    settings = AppSettings(environment=Environment.DEVELOPMENT)
    app = create_app(settings)
    service = app.state.services.runtime_status
    state = app.state.services.registry.state
    now = datetime.now(UTC)
    environment = Environment.DEVELOPMENT.value
    run_rows = {
        service.SCANNER_RUNS_TABLE: {
            "id": "scanner-latest",
            "pipeline_run_id": "pipeline-latest",
            "trigger": "scheduled",
            "status": "completed",
            "config": {},
            "source_pull_ids": [],
            "accepted_count": 0,
            "rejected_count": 0,
        },
        service.REASONING_RUNS_TABLE: {
            "id": "reasoning-latest",
            "pipeline_run_id": "pipeline-latest",
            "scanner_run_id": "scanner-latest",
            "trigger": "scheduled",
            "status": "completed",
            "config": {},
            "provider_count": 0,
            "prompt_count": 0,
            "scored_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
        },
        service.STRATEGY_CONSENSUS_RUNS_TABLE: {
            "id": "strategy-latest",
            "pipeline_run_id": "pipeline-latest",
            "reasoning_run_id": "reasoning-latest",
            "trigger": "scheduled",
            "status": "completed",
            "config": {},
            "vote_count": 0,
            "approved_count": 0,
            "refused_count": 0,
        },
        service.EXECUTION_RUNS_TABLE: {
            "id": "execution-latest",
            "pipeline_run_id": "pipeline-latest",
            "strategy_consensus_run_id": "strategy-latest",
            "trigger": "scheduled",
            "status": "completed",
            "config": {},
            "intent_count": 0,
            "simulated_count": 0,
            "submitted_count": 0,
            "refused_count": 0,
        },
        service.EXIT_RUNS_TABLE: {
            "id": "exit-latest",
            "pipeline_run_id": "pipeline-latest",
            "trigger": "scheduled",
            "status": "completed",
            "config": {},
            "open_position_count": 0,
            "triggered_count": 0,
            "simulated_count": 0,
            "submitted_count": 0,
            "refused_count": 0,
        },
    }
    for table_name, values in run_rows.items():
        state.insert(
            table_name,
            {
                **values,
                "environment": environment,
                "started_at": now,
                "completed_at": now,
                "created_at": now,
            },
        )

    original_rows = state.rows
    calls: list[tuple[str, dict]] = []

    def observed_rows(table_name: str, *args, **kwargs):
        calls.append((table_name, kwargs))
        return original_rows(table_name, *args, **kwargs)

    monkeypatch.setattr(state, "rows", observed_rows)

    service.scanner_summary(Environment.DEVELOPMENT)
    service.reasoning_summary(Environment.DEVELOPMENT)
    service.strategy_consensus_summary(Environment.DEVELOPMENT)
    service.execution_summary(Environment.DEVELOPMENT)
    service.exit_summary(Environment.DEVELOPMENT)

    expected_calls = {
        service.REASONING_OUTPUTS_TABLE: (
            DASHBOARD_REASONING_OUTPUT_ROW_LIMIT,
            "reasoning_run_id",
            "reasoning-latest",
        ),
        service.STRATEGY_VOTES_TABLE: (
            DASHBOARD_STRATEGY_VOTE_ROW_LIMIT,
            "consensus_run_id",
            "strategy-latest",
        ),
        service.STRATEGY_CONSENSUS_OUTPUTS_TABLE: (
            DASHBOARD_STRATEGY_OUTPUT_ROW_LIMIT,
            "consensus_run_id",
            "strategy-latest",
        ),
        service.ORDER_INTENTS_TABLE: (
            DASHBOARD_EXECUTION_INTENT_ROW_LIMIT,
            "execution_run_id",
            "execution-latest",
        ),
        service.EXIT_INTENTS_TABLE: (
            DASHBOARD_EXIT_INTENT_ROW_LIMIT,
            "exit_run_id",
            "exit-latest",
        ),
    }
    for table_name, (limit, run_key, run_id) in expected_calls.items():
        assert any(
            called_table == table_name
            and kwargs.get("limit") == limit
            and kwargs.get("newest_first") is True
            and kwargs.get("filters") == {
                "environment": environment,
                run_key: run_id,
            }
            for called_table, kwargs in calls
        )
    for table_name in run_rows:
        assert any(
            called_table == table_name
            and kwargs.get("limit") == 1
            and kwargs.get("newest_first") is True
            and kwargs.get("filters") == {"environment": environment}
            for called_table, kwargs in calls
        )
    assert not any(
        called_table == service.SCANNER_CANDIDATES_TABLE
        for called_table, _ in calls
    )


def test_req_ui_008_09_pipeline_detail_records_use_indexed_store_reads(monkeypatch) -> None:
    """TST-REQ-UI-008-09: Validates REQ-UI-008 and REQ-OBS-005

    Given: a selected pipeline run has step record IDs
    When: scenario detail loads the records for that run
    Then: record lookup hydrates all step IDs once with indexed, environment-scoped reads
    """

    settings = AppSettings(environment=Environment.DEVELOPMENT)
    app = create_app(settings)
    service = app.state.services.runtime_status
    state = app.state.services.registry.state
    now = datetime.now(UTC)
    state.insert(
        service.PIPELINE_RUNS_TABLE,
        {
            "id": "run-1",
            "environment": Environment.DEVELOPMENT.value,
            "trigger": "scheduled",
            "status": "accepted",
            "started_at": now,
            "completed_at": now,
            "metadata": {},
            "created_at": now,
        },
    )
    state.insert(
        service.PIPELINE_STEPS_TABLE,
        {
            "id": "step-1",
            "run_id": "run-1",
            "environment": Environment.DEVELOPMENT.value,
            "step_key": "data_fetch",
            "step_order": 1,
            "label": "Data Fetch",
            "status": "accepted",
            "started_at": now,
            "completed_at": now,
            "message": None,
            "metrics": {},
            "record_ids": ["pull-1"],
            "created_at": now,
        },
    )
    state.insert(
        service.PIPELINE_STEPS_TABLE,
        {
            "id": "step-2",
            "run_id": "run-1",
            "environment": Environment.DEVELOPMENT.value,
            "step_key": "scanner",
            "step_order": 2,
            "label": "Scanner",
            "status": "accepted",
            "started_at": now,
            "completed_at": now,
            "message": None,
            "metrics": {},
            "record_ids": ["scanner-1"],
            "created_at": now,
        },
    )
    state.insert(
        service.MARKET_DATA_PULLS_TABLE,
        {
            "id": "pull-1",
            "environment": Environment.DEVELOPMENT.value,
            "venue": "polymarket_us",
            "status": "pulled",
            "trigger": "scheduled",
            "source": "test",
            "candidates": [],
            "message": "Pulled test data.",
            "error_code": None,
            "run_id": "run-1",
            "created_at": now,
        },
    )
    state.insert(
        service.SCANNER_RUNS_TABLE,
        {
            "id": "scanner-1",
            "environment": Environment.DEVELOPMENT.value,
            "pipeline_run_id": "run-1",
            "trigger": "scheduled",
            "status": "accepted",
            "config": {},
            "input_count": 1,
            "accepted_count": 1,
            "rejected_count": 0,
            "started_at": now,
            "completed_at": now,
            "created_at": now,
        },
    )
    original_rows = state.rows
    calls: list[tuple[str, dict]] = []

    def observed_rows(table_name: str, *args, **kwargs):
        calls.append((table_name, kwargs))
        return original_rows(table_name, *args, **kwargs)

    monkeypatch.setattr(state, "rows", observed_rows)

    detail = service.pipeline_run_detail(Environment.DEVELOPMENT, "run-1")

    assert detail is not None
    assert detail["records"][0]["recordCount"] == 1
    assert detail["records"][0]["items"][0]["id"] == "pull-1"
    assert detail["records"][1]["items"][0]["id"] == "scanner-1"
    record_calls = [
        (table_name, kwargs)
        for table_name, kwargs in calls
        if kwargs.get("ids") is not None
    ]
    assert len(record_calls) == len({table_name for table_name, _ in record_calls})
    assert any(
        table_name == service.MARKET_DATA_PULLS_TABLE
        and kwargs.get("limit") == DASHBOARD_PIPELINE_RECORD_ROW_LIMIT
        and kwargs.get("newest_first") is True
        and kwargs.get("filters") == {"environment": Environment.DEVELOPMENT.value}
        and kwargs.get("ids") == {"pull-1", "scanner-1"}
        for table_name, kwargs in calls
    )

    calls.clear()
    scanned_detail = service.pipeline_run_detail(
        Environment.DEVELOPMENT,
        "run-1",
        activity_stage="scanned",
    )

    assert scanned_detail is not None
    assert scanned_detail["records"][0]["items"][0]["id"] == "pull-1"
    assert scanned_detail["records"][1]["items"] == []
    scoped_record_calls = [
        (table_name, kwargs)
        for table_name, kwargs in calls
        if kwargs.get("ids") is not None
    ]
    assert [table_name for table_name, _ in scoped_record_calls] == [
        service.MARKET_DATA_PULLS_TABLE
    ]
    assert scoped_record_calls[0][1]["ids"] == {"pull-1"}


def test_req_ui_008_10_default_scenario_skips_record_hydration(monkeypatch) -> None:
    """TST-REQ-UI-008-10: Validates REQ-UI-008 and REQ-OBS-005

    Given: the What-if page loads without a selected run or prompt
    When: scenario analysis builds the default summary
    Then: it does not hydrate full step-linked records across all record tables
    """

    settings = AppSettings(environment=Environment.DEVELOPMENT)
    app = create_app(settings)
    service = app.state.services.runtime_status

    monkeypatch.setattr(
        service,
        "pipeline_runs",
        lambda environment, limit=10: [
            {
                "id": "run-1",
                "trigger": "scheduled",
                "status": "pulled",
                "startedAt": datetime.now(UTC).isoformat(),
                "completedAt": datetime.now(UTC).isoformat(),
                "steps": [
                    {
                        "key": "data_fetch",
                        "label": "Data Fetch",
                        "status": "pulled",
                        "message": "Fetched market data.",
                        "metrics": {"candidateCount": 30},
                        "inputs": {},
                        "outputs": {},
                        "decisions": {},
                        "recordIds": ["pull-1"],
                    }
                ],
            }
        ],
    )

    def fail_if_loaded(environment: Environment, run_id: str) -> None:
        raise AssertionError("default scenario load should not hydrate detail records")

    monkeypatch.setattr(service, "pipeline_run_detail", fail_if_loaded)

    payload = service.scenario_analysis(
        environment=Environment.DEVELOPMENT,
        config_payload=service.runtime_config_payload(),
    )

    assert payload["run"]["id"] == "run-1"
    assert payload["records"] == []
    assert payload["steps"][0]["recordCount"] == 0


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


def test_req_ui_017_overview_returns_one_bounded_initial_payload() -> None:
    """TST-REQ-UI-017-06: Validates REQ-UI-017 and REQ-OBS-005

    Given: an authenticated consumer opens the overview
    When: its bounded overview endpoint is requested
    Then: the five initial panels are returned from one config snapshot
    """
    client, token = _client()

    response = client.get(
        "/api/dashboard/overview",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["environment"] == "development"
    assert set(payload) == {
        "environment",
        "generatedAt",
        "config",
        "operations",
        "marketData",
        "tickSchedule",
        "notifications",
    }
    assert payload["operations"]["killSwitch"] == "inactive"


def test_req_ui_009_readiness_omits_expensive_dashboard_sections() -> None:
    """TST-REQ-UI-009-03: Validates REQ-UI-009 and REQ-OBS-005

    Given: an authenticated operator opens system health
    When: the readiness endpoint is requested
    Then: it returns readiness fields without model, economics, or history reads
    """
    client, token = _client()

    response = client.get(
        "/api/dashboard/readiness",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"]["health"] == "ok"
    assert "credentials" in payload["wallet"]
    assert "notifications" in payload
    assert "economics" not in payload
    assert "models" not in payload
    assert "operations" not in payload


def test_req_obs_006_postgres_startup_failure_is_not_hidden(monkeypatch) -> None:
    """TST-REQ-OBS-006-02: Validates REQ-OBS-006

    Given: a deployed runtime has a configured database that cannot be reached
    When: the repository registry initializes
    Then: startup fails so the task can retry instead of serving a false healthy state
    """

    def unavailable_session_factory(database_url: str):
        del database_url
        raise RuntimeError("connection timeout expired")

    monkeypatch.setattr(main_module, "create_session_factory", unavailable_session_factory)

    with pytest.raises(PersistenceUnavailableError, match="Postgres persistence is unavailable"):
        main_module._repository_registry_from_settings(
            AppSettings(database_url="postgresql+psycopg://configured-database")
        )


def test_req_obs_006_persistence_failure_returns_safe_503() -> None:
    """TST-REQ-OBS-006-03: Validates REQ-OBS-006

    Given: persistence becomes unavailable after the backend starts
    When: an authenticated dashboard read needs stored data
    Then: the API reports a safe retryable 503 response
    """

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        environment=Environment.DEVELOPMENT,
    )
    app = create_app(settings)
    token = app.state.services.auth.create_session_token(username="yaw")
    app.state.services.registry.state.available = False

    response = TestClient(app).get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json() == {
        "detail": {
            "error_code": "persistence_unavailable",
            "message": "Dashboard data is temporarily unavailable.",
        }
    }


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
    monkeypatch.setenv("ALPACA_SYMBOL_UNIVERSE", "spy, qqq, spy, nvda")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://polygon-rpc.example")
    monkeypatch.setenv("POLYGON_ORDER_FILLED_MAX_BLOCK_RANGE", "750")
    monkeypatch.setenv("POLYGON_ORDER_FILLED_MAX_WINDOWS", "3")
    monkeypatch.setenv("POLYGON_ORDER_FILLED_IMPORT_CADENCE_MINUTES", "45")
    monkeypatch.setenv("POLYGON_ORDER_FILLED_RETRY_SPLIT", "false")

    app = create_app()
    settings = app.state.settings

    assert settings.environment == Environment.DEVELOPMENT
    assert settings.allowed_usernames == ("yawetse", "operator")
    assert settings.signing_secret == "deploy-token-secret"
    assert settings.csrf_token == "deploy-csrf"
    assert settings.trusted_origins == ("https://dashboard.example.com",)
    assert settings.alpaca_symbol_presets == ()
    assert settings.alpaca_symbol_universe == ("SPY", "QQQ", "NVDA")
    payload = app.state.services.runtime_status.runtime_config_payload()
    assert payload["alpaca"]["symbol_universe"] == [
        "SPY",
        "QQQ",
        "NVDA",
    ]
    assert payload["historical_import"]["polymarket"] == {
        "source": "clean_room_polygon_order_filled",
        "polygon_rpc_configured": True,
        "max_block_range": 750,
        "max_windows": 3,
        "import_cadence_minutes": 45,
        "retry_policy": {
            "split_oversized_windows": False,
            "rate_limits_record_checkpoint": True,
        },
    }


def test_req_ui_001_05_live_runtime_wires_venue_submitters_when_credentials_present() -> None:
    """TST-REQ-UI-001-05: Validates REQ-UI-001 and REQ-EXE-017

    Given: live runtime flags and venue credentials
    When: dashboard services are created
    Then: the lifecycle service receives live submitter adapters
    """
    settings = AppSettings(
        environment=Environment.PRODUCTION,
        runtime_env={
            "TRADING_ACCOUNT_MODE": "live",
            "ALPACA_OPENAI_KEY_ID": "alpaca-openai-key",
            "ALPACA_OPENAI_SECRET_KEY": "alpaca-openai-secret",
            "ALPACA_CLAUDE_KEY_ID": "alpaca-claude-key",
            "ALPACA_CLAUDE_SECRET_KEY": "alpaca-claude-secret",
            "POLYMARKET_OPENAI_KEY_ID": "pm-openai-key",
            "POLYMARKET_OPENAI_SECRET_KEY": "pm-openai-secret",
            "POLYMARKET_CLAUDE_KEY_ID": "pm-claude-key",
            "POLYMARKET_CLAUDE_SECRET_KEY": "pm-claude-secret",
        },
        live_enabled=True,
        trading_account_mode="live",
        default_selected_venue=Venue.POLYMARKET_US,
        polymarket_us_enabled=True,
        alpaca_enabled=True,
        alpaca_account_status="active",
    )

    app = create_app(settings)
    lifecycle = app.state.services.runtime_status.lifecycle

    assert lifecycle.alpaca_submitter is not None
    assert lifecycle.alpaca_exit_submitter is lifecycle.alpaca_submitter
    assert lifecycle.polymarket_submitter is not None
    assert lifecycle.polymarket_position_closer is lifecycle.polymarket_submitter
    assert set(lifecycle.alpaca_submitters) == {ModelProvider.OPENAI, ModelProvider.CLAUDE}
    assert set(lifecycle.polymarket_submitters) == {ModelProvider.OPENAI, ModelProvider.CLAUDE}


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
    Then: status, config, wallet, order, model, comparison, loop, notification, and audit sections are returned without secrets
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
        "loop",
        "notifications",
        "audit",
    }.issubset(payload)
    assert "secret" not in str(payload).lower()
    assert "private" not in str(payload).lower()


def test_req_ui_004_04_dashboard_summary_reflects_runtime_readiness(monkeypatch) -> None:
    """TST-REQ-UI-004-04: Validates REQ-UI-004, REQ-UI-009, and REQ-OBS-005

    Given: deployed live-capable runtime flags and provider credentials without a saved config
    When: the dashboard summary is requested
    Then: readiness is rendered while trading remains in the fail-closed dry-run state
    """

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DASHBOARD_ALLOWED_USERS", "yaw")
    monkeypatch.setenv("BACKEND_TOKEN_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("LIVE_ENABLED", "true")
    monkeypatch.setenv("TRADING_ACCOUNT_MODE", "live")
    monkeypatch.setenv("DEFAULT_SELECTED_VENUE", "polymarket_us")
    monkeypatch.setenv("POLYMARKET_US_ENABLED", "true")
    monkeypatch.setenv("ALPACA_ENABLED", "true")
    monkeypatch.setenv("ALPACA_ACCOUNT_STATUS", "reviewing")
    monkeypatch.setenv("POLYMARKET_OPENAI_KEY_ID", "pm-openai-key-id")
    monkeypatch.setenv("POLYMARKET_OPENAI_SECRET_KEY", "pm-openai-signing-key")
    monkeypatch.setenv("POLYMARKET_OPENAI_PRIVATE_KEY", "pm-openai-wallet-key")
    monkeypatch.setenv("POLYMARKET_CLAUDE_KEY_ID", "pm-claude-key-id")
    monkeypatch.setenv("POLYMARKET_CLAUDE_SECRET_KEY", "pm-claude-signing-key")
    monkeypatch.setenv("POLYMARKET_CLAUDE_PRIVATE_KEY", "pm-claude-wallet-key")
    monkeypatch.setenv("ALPACA_OPENAI_KEY_ID", "alpaca-openai-key-id")
    monkeypatch.setenv("ALPACA_OPENAI_SECRET_KEY", "alpaca-openai-signing-key")
    monkeypatch.setenv("ALPACA_CLAUDE_KEY_ID", "alpaca-claude-key-id")
    monkeypatch.setenv("ALPACA_CLAUDE_SECRET_KEY", "alpaca-claude-signing-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("SES_IDENTITY_EMAIL", "alerts@example.com")
    monkeypatch.setenv("NOTIFICATION_RECIPIENTS", "operator:alerts@example.com")

    app = create_app(AppSettings.from_env())
    token = app.state.services.auth.create_session_token(username="yaw")
    response = TestClient(app).get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "production"},
    )
    payload = response.json()

    assert response.status_code == 200
    status_by_label = {item["label"]: item for item in payload["status"]["items"]}
    assert status_by_label["Venue"]["value"] == "polymarket_us enabled"
    assert status_by_label["Wallet"]["value"] == "2 missing"
    assert status_by_label["Ingestion"]["state"] == "ok"
    assert status_by_label["Notification"]["state"] == "ok"
    assert status_by_label["Trading loop"]["value"] == "Dry run"
    credentials = {item["id"]: item for item in payload["wallet"]["credentials"]}
    assert credentials["polymarket_us-openai-wallet"]["status"] == "present"
    assert credentials["polymarket_us-claude-wallet"]["status"] == "present"
    assert credentials["openai-api"]["status"] == "present"
    assert credentials["anthropic-api"]["status"] == "present"
    assert credentials["alpaca-claude-account"]["status"] == "reviewing"
    assert credentials["alpaca-openai-account"]["status"] == "reviewing"
    assert payload["notifications"]["recipientCount"] == 1
    assert "pm-openai-wallet-key" not in str(payload)


def test_req_obs_005_03_dashboard_summary_visualizes_loop_observability(monkeypatch) -> None:
    """TST-REQ-OBS-005-03: Validates REQ-OBS-005 and REQ-UI-004

    Given: an authenticated operator asks for dashboard state
    When: the summary endpoint returns loop observability
    Then: schedule, data, prompts, logic, calculations, and gates are visible without secrets
    """

    monkeypatch.setenv("DASHBOARD_ALLOWED_USERS", "yaw")
    monkeypatch.setenv("BACKEND_TOKEN_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("LIVE_ENABLED", "true")
    monkeypatch.setenv("DEFAULT_SELECTED_VENUE", "alpaca")
    monkeypatch.setenv("ALPACA_ENABLED", "true")
    monkeypatch.setenv("ALPACA_OPENAI_KEY_ID", "alpaca-openai-key-id")
    monkeypatch.setenv("ALPACA_OPENAI_SECRET_KEY", "alpaca-openai-signing-key")
    monkeypatch.setenv("ALPACA_CLAUDE_KEY_ID", "alpaca-claude-key-id")
    monkeypatch.setenv("ALPACA_CLAUDE_SECRET_KEY", "alpaca-claude-signing-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    app = create_app(AppSettings.from_env())
    token = app.state.services.auth.create_session_token(username="yaw")
    response = TestClient(app).get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    payload = response.json()
    loop = payload["loop"]

    assert response.status_code == 200
    assert loop["schedule"]["intervalSeconds"] == 900
    assert loop["schedule"]["nextRunAt"]
    assert loop["currentPhase"]["label"] == "Waiting for next scheduler tick"
    assert {stage["id"] for stage in loop["stages"]} >= {
        "scheduler",
        "market-data",
        "scoring",
        "risk",
        "execution",
    }
    assert {item["label"] for item in loop["dataInputs"]} >= {
        "Active venues",
        "Alpaca symbols",
        "Market candidates",
    }
    active_venue_input = next(item for item in loop["dataInputs"] if item["label"] == "Active venues")
    assert active_venue_input["value"] == "alpaca"
    assert active_venue_input["detail"] == "Default venue is alpaca. Enabled venues are scanned and scored."
    assert {prompt["label"] for prompt in loop["prompts"]} >= {
        "Scoring system prompt",
        "Prompt version",
        "Latest prompt run",
    }
    assert {logic["label"] for logic in loop["logic"]} >= {
        "Candidate filters",
        "Enabled strategies",
        "Live order gates",
    }
    assert {calculation["label"] for calculation in loop["calculations"]} >= {
        "Loop cadence",
        "Kelly capped notional",
        "Alpaca allocation cap",
    }
    assert {gate["label"] for gate in loop["gates"]} >= {
        "Worker heartbeat",
        "Live flag",
        "Credentials",
        "Market data",
        "Scoring",
        "Risk",
    }
    assert "alpaca-signing-key" not in str(loop)


def test_req_obs_005_04_operations_summary_defers_heavy_history_by_default(monkeypatch) -> None:
    """TST-REQ-OBS-005-04: Validates REQ-OBS-005 and REQ-UI-008

    Given: an authenticated operator opens the live operations dashboard
    When: the default summary endpoint is requested
    Then: high-volume historical import sections are deferred unless explicitly requested
    """

    client, token = _client()
    runtime_status = client.app.state.services.runtime_status

    def fail_if_loaded(*_: object, **__: object) -> dict[str, object] | list[object]:
        raise AssertionError("high-volume details should not load in the default operations summary")

    monkeypatch.setattr(runtime_status, "order_events", fail_if_loaded)
    monkeypatch.setattr(runtime_status, "pipeline_runs", fail_if_loaded)
    monkeypatch.setattr(runtime_status, "scanner_summary", fail_if_loaded)
    monkeypatch.setattr(runtime_status, "reasoning_summary", fail_if_loaded)
    monkeypatch.setattr(runtime_status, "strategy_consensus_summary", fail_if_loaded)
    monkeypatch.setattr(runtime_status, "execution_summary", fail_if_loaded)
    monkeypatch.setattr(runtime_status, "exit_summary", fail_if_loaded)
    monkeypatch.setattr(runtime_status, "historical_import_summary", fail_if_loaded)
    monkeypatch.setattr(runtime_status, "broker_history_summary", fail_if_loaded)

    response = client.get(
        "/api/operations/summary",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["orderEvents"] == []
    assert payload["pipelineRuns"] == []
    assert payload["scanner"]["status"] == "idle"
    assert payload["scanner"]["detailsDeferred"] is True
    assert payload["reasoning"]["status"] == "deferred"
    assert payload["strategyConsensus"]["status"] == "deferred"
    assert payload["execution"]["status"] == "deferred"
    assert payload["exit"]["status"] == "deferred"
    assert payload["historicalImport"]["status"] == "deferred"
    assert payload["brokerHistory"]["status"] == "deferred"


def test_req_ui_004_06_default_summary_reports_scanner_aggregates_without_details(
    monkeypatch,
) -> None:
    """TST-REQ-UI-004-06: Validates REQ-UI-004 and REQ-OBS-005.

    Given: a persisted scanner run has accepted and rejected candidates
    When: the default dashboard summary defers candidate detail rows
    Then: persisted totals and grouped venue-specific rejection reasons remain accurate
    """

    client, token = _client()
    runtime_status = client.app.state.services.runtime_status
    shared = client.app.state.services.registry.shared()
    observed = datetime(2026, 7, 13, 15, 35, tzinfo=UTC)
    run = shared.record_scanner_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-reporting",
        trigger="scheduled",
        status="completed",
        config={"alpaca": {"max_spread": "0.75"}},
        source_pull_ids=["pull-polymarket", "pull-alpaca"],
        accepted_count=1,
        rejected_count=2,
        started_at=observed,
        completed_at=observed,
    )
    shared.record_scanner_candidate(
        environment=Environment.DEVELOPMENT,
        scanner_run_id=run["id"],
        venue=Venue.POLYMARKET_US.value,
        instrument_id="market-1:yes",
        display_name="Will rates fall? - Yes",
        status="accepted",
        strategy_names=["order_book_depth"],
        metrics={},
        source_payload={"id": "market-1"},
        created_at=observed,
    )
    for symbol in ("AAA", "BBB"):
        shared.record_scanner_candidate(
            environment=Environment.DEVELOPMENT,
            scanner_run_id=run["id"],
            venue=Venue.ALPACA.value,
            instrument_id=f"alpaca:{symbol}",
            display_name=symbol,
            symbol=symbol,
            status="rejected",
            refusal_reason="spread too wide",
            strategy_names=[],
            metrics={},
            source_payload={"symbol": symbol},
            created_at=observed,
        )
    state = client.app.state.services.registry.state
    state.insert(
        "shared.pipeline_steps",
        {
            "id": "pipeline-reporting-scanner",
            "run_id": "pipeline-reporting",
            "environment": "development",
            "step_key": "scanner",
            "step_order": 2,
            "label": "Find candidates",
            "status": "completed",
            "started_at": observed,
            "completed_at": observed,
            "message": "Scanner accepted 1 and rejected 2 candidates.",
            "metrics": {
                "candidateCount": 3,
                "acceptedCount": 1,
                "rejectedCount": 2,
                "rejectionBreakdown": [
                    {"venue": "alpaca", "reason": "spread too wide", "count": 2}
                ],
            },
            "record_ids": [run["id"]],
            "created_at": observed,
        },
    )
    state.fail_on_read_tables.add("shared.scanner_candidates")

    def fail_if_loaded(*_: object, **__: object) -> dict[str, object]:
        raise AssertionError("scanner candidate details should remain deferred")

    monkeypatch.setattr(runtime_status, "scanner_summary", fail_if_loaded)
    response = client.get(
        "/api/operations/summary",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    scanner = response.json()["scanner"]

    assert response.status_code == 200
    assert scanner["status"] == "completed"
    assert scanner["candidateCount"] == 3
    assert scanner["acceptedCount"] == 1
    assert scanner["rejectedCount"] == 2
    assert scanner["rejectionBreakdown"] == [
        {"venue": "alpaca", "reason": "spread too wide", "count": 2}
    ]
    assert scanner["candidates"] == []
    assert scanner["latestRun"]["candidateCount"] == 3
    assert scanner["detailsDeferred"] is True
    assert "accepted 1 and rejected 2 candidates" in scanner["message"]


def test_req_exe_016_11_orders_endpoint_reads_durable_environment_history() -> None:
    """TST-REQ-EXE-016-11: Validates REQ-EXE-016

    Given: durable order intents exist across environments and states
    When: an authenticated user requests development order history
    Then: the endpoint returns only development records newest first with execution details
    """

    client, token = _client()
    state = client.app.state.services.registry.state
    older = datetime(2026, 7, 12, 14, 0, tzinfo=UTC)
    newer = older + timedelta(minutes=1)
    rows = [
        {
            "id": "intent-submitted",
            "execution_run_id": "execution-1",
            "pipeline_run_id": "pipeline-1",
            "strategy_consensus_output_id": "consensus-1",
            "environment": "development",
            "venue": "polymarket_us",
            "instrument_id": "polymarket_us:market-1",
            "model_provider": "openai",
            "side": "sell",
            "order_type": "market",
            "status": "submitted",
            "notional_usd": Decimal("12.50"),
            "size_multiplier": Decimal("0.50"),
            "idempotency_key": "private-idempotency-value",
            "refusal_reason": None,
            "venue_order_id": "venue-order-1",
            "risk_payload": {"private": "risk-details"},
            "source_payload": {"private": "source-details"},
            "created_at": older,
            "updated_at": older,
        },
        {
            "id": "intent-refused",
            "execution_run_id": "execution-2",
            "pipeline_run_id": "pipeline-2",
            "strategy_consensus_output_id": "consensus-2",
            "environment": "development",
            "venue": "alpaca",
            "instrument_id": "SPY",
            "model_provider": "claude",
            "side": "buy",
            "order_type": "limit",
            "status": "refused",
            "notional_usd": Decimal("25.00"),
            "size_multiplier": Decimal("1.00"),
            "idempotency_key": "second-private-idempotency-value",
            "refusal_reason": "SLIPPAGE_LIMIT",
            "venue_order_id": None,
            "risk_payload": {},
            "source_payload": {},
            "created_at": newer,
            "updated_at": newer,
        },
        {
            "id": "intent-simulated",
            "execution_run_id": "execution-4",
            "pipeline_run_id": "pipeline-4",
            "strategy_consensus_output_id": "consensus-4",
            "environment": "development",
            "venue": "alpaca",
            "instrument_id": "IWM",
            "model_provider": "openai",
            "side": "buy",
            "order_type": "market",
            "status": "simulated",
            "notional_usd": Decimal("10.00"),
            "size_multiplier": Decimal("0.40"),
            "idempotency_key": "simulated-private-idempotency-value",
            "refusal_reason": None,
            "venue_order_id": None,
            "risk_payload": {},
            "source_payload": {},
            "created_at": older,
            "updated_at": older,
        },
        {
            "id": "intent-production",
            "execution_run_id": "execution-3",
            "pipeline_run_id": "pipeline-3",
            "strategy_consensus_output_id": "consensus-3",
            "environment": "production",
            "venue": "alpaca",
            "instrument_id": "QQQ",
            "model_provider": "openai",
            "side": "buy",
            "order_type": "market",
            "status": "filled",
            "notional_usd": Decimal("20.00"),
            "size_multiplier": Decimal("0.80"),
            "idempotency_key": "production-private-idempotency-value",
            "refusal_reason": None,
            "venue_order_id": "production-order-1",
            "risk_payload": {},
            "source_payload": {},
            "created_at": newer,
            "updated_at": newer,
        },
    ]
    for row in rows:
        state.insert("shared.order_intents", row)

    response = client.get(
        "/api/orders",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["environment"] == "development"
    assert payload["next_cursor"] is None
    assert [item["id"] for item in payload["items"]] == [
        "intent-refused",
        "intent-submitted",
        "intent-simulated",
    ]
    assert payload["items"][0] == {
        "id": "intent-refused",
        "state": "refused",
        "venue": "alpaca",
        "provider": "claude",
        "side": "buy",
        "instrumentId": "SPY",
        "orderType": "limit",
        "notionalUsd": "25.00000000",
        "venueOrderId": None,
        "message": "SLIPPAGE_LIMIT",
        "createdAt": newer.isoformat(),
        "updatedAt": newer.isoformat(),
    }
    assert payload["items"][1]["message"] == "Submitted to venue; fill not yet confirmed."
    assert "private-idempotency-value" not in str(payload)
    assert "risk-details" not in str(payload)
    assert "source-details" not in str(payload)

    first_page = client.get(
        "/api/orders?limit=1",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    ).json()
    state.insert(
        "shared.order_intents",
        {
            **rows[0],
            "id": "intent-newest",
            "execution_run_id": "execution-newest",
            "pipeline_run_id": "pipeline-newest",
            "idempotency_key": "newest-private-idempotency-value",
            "created_at": newer + timedelta(minutes=1),
            "updated_at": newer + timedelta(minutes=1),
        },
    )
    second_page_response = client.get(
        "/api/orders",
        params={"limit": 1, "cursor": first_page["next_cursor"]},
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    second_page = second_page_response.json()
    third_page_response = client.get(
        "/api/orders",
        params={"limit": 1, "cursor": second_page["next_cursor"]},
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    third_page = third_page_response.json()

    assert second_page_response.status_code == 200
    assert third_page_response.status_code == 200
    assert [item["id"] for item in first_page["items"]] == ["intent-refused"]
    assert first_page["next_cursor"]
    assert [item["id"] for item in second_page["items"]] == ["intent-submitted"]
    assert [item["id"] for item in third_page["items"]] == ["intent-simulated"]
    assert third_page["next_cursor"] is None

    invalid_cursor = client.get(
        "/api/orders?cursor=not-a-cursor",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["detail"]["error_code"] == "invalid_order_history_cursor"


def test_req_exe_016_12_orders_endpoint_reports_persistence_failure() -> None:
    """TST-REQ-EXE-016-12: Validates REQ-EXE-016

    Given: durable order history cannot be read
    When: an authenticated user requests order history
    Then: the endpoint reports a service failure instead of an empty history
    """

    client, token = _client()
    client.app.state.services.registry.state.fail_on_read_tables.add("shared.order_intents")

    response = client.get(
        "/api/orders",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "order_history_unavailable"


def test_req_ui_004_05_dashboard_preferences_persist_theme_timezone_and_costs() -> None:
    """TST-REQ-UI-004-05: Validates REQ-UI-004 and REQ-OBS-004

    Given: multiple authorized dashboard users save display preferences
    When: preferences are saved and reloaded
    Then: theme, time zone, and AWS cost assumptions load from the database per user
    """

    settings = AppSettings(
        allowed_usernames=("yaw", "alex"),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
    )
    app = create_app(settings)
    client = TestClient(app)
    yaw_token = app.state.services.auth.create_session_token(username="yaw")
    alex_token = app.state.services.auth.create_session_token(username="alex")

    yaw_saved = client.put(
        "/api/preferences",
        headers={
            "Authorization": f"Bearer {yaw_token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "settings": {
                "theme": "dark",
                "timeZone": "America/New_York",
                "awsMonthlyInfraCostUsd": "60.00",
            }
        },
    )
    alex_saved = client.put(
        "/api/preferences",
        headers={
            "Authorization": f"Bearer {alex_token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "settings": {
                "theme": "light",
                "timeZone": "America/Chicago",
                "awsMonthlyInfraCostUsd": "15.00",
            }
        },
    )
    yaw_loaded = client.get(
        "/api/preferences",
        headers={"Authorization": f"Bearer {yaw_token}", "X-Environment": "development"},
    )
    alex_loaded = client.get(
        "/api/preferences",
        headers={"Authorization": f"Bearer {alex_token}", "X-Environment": "development"},
    )
    yaw_summary = client.get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {yaw_token}", "X-Environment": "development"},
    )
    alex_summary = client.get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {alex_token}", "X-Environment": "development"},
    )
    audit_rows = client.app.state.services.registry.state.rows("shared.audit_events")

    assert yaw_saved.status_code == 200
    assert alex_saved.status_code == 200
    assert yaw_loaded.status_code == 200
    assert alex_loaded.status_code == 200
    assert yaw_summary.status_code == 200
    assert alex_summary.status_code == 200
    assert yaw_loaded.json()["settings"] == {
        "theme": "dark",
        "timeZone": "America/New_York",
        "awsMonthlyInfraCostUsd": "60.00",
    }
    assert alex_loaded.json()["settings"] == {
        "theme": "light",
        "timeZone": "America/Chicago",
        "awsMonthlyInfraCostUsd": "15.00",
    }
    assert yaw_summary.json()["preferences"]["username"] == "yaw"
    assert yaw_summary.json()["preferences"]["settings"]["awsMonthlyInfraCostUsd"] == "60.00"
    assert yaw_summary.json()["economics"]["aws"]["dailyInfraCostEstimateUsd"] == "2.00"
    assert alex_summary.json()["preferences"]["username"] == "alex"
    assert alex_summary.json()["preferences"]["settings"]["awsMonthlyInfraCostUsd"] == "15.00"
    assert alex_summary.json()["economics"]["aws"]["dailyInfraCostEstimateUsd"] == "0.50"
    assert {row["actor"] for row in audit_rows[-2:]} == {"yaw", "alex"}
    assert all(row["event_type"] == "dashboard_preferences_change" for row in audit_rows[-2:])


def test_req_ui_008_04_manual_run_records_heartbeat_audit_and_market_pull() -> None:
    """TST-REQ-UI-008-04: Validates REQ-UI-008, REQ-DAT-008, and REQ-OBS-004

    Given: an authorized dashboard user triggers a manual run
    When: the manual-run endpoint is called
    Then: the API accepts the request, records a heartbeat, and exposes the latest market-data pull
    """

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
        polymarket_us_enabled=True,
        alpaca_enabled=True,
        alpaca_symbol_universe=("AMD",),
    )
    app = create_app(settings)
    app.state.services.runtime_status.market_data_fetcher = FakeMarketDataFetcher(
        {
            "polymarket_us": MarketDataProviderResult(
                venue="polymarket_us",
                status="pulled",
                source="polymarket gamma and clob api",
                message="Fetched 1 Polymarket priced candidate.",
                candidates=[
                    {
                        "id": "polymarket_us:market-1:yes-token",
                        "venue": "polymarket_us",
                        "market": "Will rates fall? - Yes",
                        "marketSlug": "will-rates-fall",
                        "price": "0.45",
                        "liquidity": "250",
                        "spread": "0.02",
                        "state": "priced",
                        "pulledAt": datetime.now(UTC).isoformat(),
                    }
                ],
            ),
            "alpaca": MarketDataProviderResult(
                venue="alpaca",
                status="pulled",
                source="alpaca market data api",
                message="Fetched 1 Alpaca priced candidate.",
                candidates=[
                    {
                        "id": "alpaca:AMD",
                        "venue": "alpaca",
                        "symbol": "AMD",
                        "price": "200.01",
                        "liquidity": "3",
                        "spread": "0.02",
                        "state": "priced",
                        "pulledAt": datetime.now(UTC).isoformat(),
                    }
                ],
            ),
        }
    )
    token = app.state.services.auth.create_session_token(username="yaw")
    client = TestClient(app)

    response = client.post(
        "/api/operations/manual-run",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={"environment": "development"},
    )
    latest_pull = client.get(
        "/api/market-data/latest",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    job_rows = client.app.state.services.registry.state.rows("shared.job_runs")
    audit_rows = client.app.state.services.registry.state.rows("shared.audit_events")
    pull_rows = client.app.state.services.registry.state.rows("shared.dashboard_market_data_pulls")
    scanner_rows = client.app.state.services.registry.state.rows("shared.scanner_runs")
    scanner_candidate_rows = client.app.state.services.registry.state.rows("shared.scanner_candidates")
    reasoning_rows = client.app.state.services.registry.state.rows("shared.reasoning_runs")
    strategy_rows = client.app.state.services.registry.state.rows("shared.strategy_consensus_runs")
    pipeline_rows = client.app.state.services.registry.state.rows("shared.pipeline_runs")
    pipeline_step_rows = client.app.state.services.registry.state.rows("shared.pipeline_steps")

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["requestedMode"] == "full_dry_run"
    assert payload["pipelineRun"]["trigger"] == "manual"
    assert payload["pipelineRun"]["metadata"]["requestedMode"] == "full_dry_run"
    assert [step["label"] for step in payload["pipelineRun"]["steps"]] == [
        "Data Fetch",
        "Scanner",
        "Reasoning / Brain",
        "Execution",
        "Exit",
    ]
    assert payload["pipelineRun"]["metadata"]["endResult"]["status"] == "accepted"
    assert payload["pipelineRun"]["steps"][0]["metrics"]["candidateCount"] == 2
    assert payload["pipelineRun"]["steps"][0]["inputs"]["venues"] == [
        "polymarket_us",
        "alpaca",
    ]
    assert payload["pipelineRun"]["steps"][0]["outputs"]["candidateCount"] == 2
    assert payload["pipelineRun"]["steps"][0]["decisions"]["accepted"] is True
    assert payload["pipelineRun"]["steps"][1]["metrics"]["acceptedCount"] == 0
    assert payload["pipelineRun"]["steps"][1]["metrics"]["rejectedCount"] == 2
    scanner_breakdown = payload["pipelineRun"]["steps"][1]["metrics"]["rejectionBreakdown"]
    assert {"venue": "alpaca", "reason": "insufficient historical bars", "count": 1} in scanner_breakdown
    assert {"venue": "polymarket_us", "reason": "liquidity below minimum", "count": 1} in scanner_breakdown
    scanner_candidates = payload["pipelineRun"]["steps"][1]["decisions"]["candidates"]
    assert {candidate["venue"] for candidate in scanner_candidates} == {"polymarket_us", "alpaca"}
    assert "alpaca: insufficient historical bars (1)" in payload["pipelineRun"]["steps"][1]["message"]
    assert "trace" not in payload["pipelineRun"]["steps"][0]["metrics"]
    assert payload["scannerRun"]["candidateCount"] == 2
    assert payload["scannerRun"]["rejectedCount"] == 2
    assert payload["reasoningRun"]["status"] == "no_candidates"
    assert payload["strategyRun"]["status"] == "no_scores"
    assert payload["pipelineRun"]["steps"][2]["metrics"]["promptCount"] == 0
    assert payload["pipelineRun"]["steps"][3]["metrics"]["voteCount"] == 0
    assert payload["pipelineRun"]["steps"][3]["metrics"]["orderIntentCount"] == 0
    assert payload["marketDataPull"]["trigger"] == "manual"
    assert payload["marketDataPull"]["status"] == "pulled"
    assert {pull["venue"] for pull in payload["marketDataPulls"]} == {
        "polymarket_us",
        "alpaca",
    }
    assert {pull["status"] for pull in payload["marketDataPulls"]} == {"pulled"}
    assert {pull["venue"] for pull in payload["marketDataPull"]["venues"]} == {
        "polymarket_us",
        "alpaca",
    }
    assert payload["marketDataPull"]["candidateCount"] == 2
    assert latest_pull.status_code == 200
    assert latest_pull.json()["id"] == payload["marketDataPull"]["id"]
    assert {pull["venue"] for pull in latest_pull.json()["venues"]} == {
        "polymarket_us",
        "alpaca",
    }
    assert {row["source"] for row in pull_rows} == {
        "polymarket gamma and clob api",
        "alpaca market data api",
    }
    assert scanner_rows[0]["pipeline_run_id"] == payload["runId"]
    assert scanner_rows[0]["rejected_count"] == 2
    assert {row["status"] for row in scanner_candidate_rows} == {"rejected"}
    polymarket_scanner_row = next(
        row for row in scanner_candidate_rows if row["venue"] == "polymarket_us"
    )
    assert polymarket_scanner_row["source_payload"]["marketSlug"] == "will-rates-fall"
    assert reasoning_rows[0]["pipeline_run_id"] == payload["runId"]
    assert reasoning_rows[0]["status"] == "no_candidates"
    assert strategy_rows[0]["pipeline_run_id"] == payload["runId"]
    assert strategy_rows[0]["status"] == "no_scores"
    assert pipeline_rows[0]["id"] == payload["runId"]
    assert pipeline_rows[0]["metadata"]["endResult"]["orderIntentCount"] == 0
    assert len(pipeline_step_rows) == 5
    assert pipeline_step_rows[0]["metrics"]["trace"]["inputs"]["venues"] == [
        "polymarket_us",
        "alpaca",
    ]
    assert pipeline_step_rows[0]["metrics"]["trace"]["outputs"]["candidateCount"] == 2
    assert any(row["job_name"] == "manual-trading-loop" for row in job_rows)
    assert audit_rows[-1]["event_type"] == "manual_loop_trigger"
    assert audit_rows[-1]["metadata"]["requested_mode"] == "full_dry_run"
    assert set(audit_rows[-1]["metadata"]["venues"]) == {"polymarket_us", "alpaca"}
    detail = client.get(
        f"/api/operations/runs/{payload['runId']}",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    detail_payload = detail.json()
    assert detail.status_code == 200
    assert detail_payload["run"]["id"] == payload["runId"]
    assert detail_payload["records"][0]["stepKey"] == "data_fetch"
    assert detail_payload["records"][0]["recordCount"] == 2
    assert {item["table"] for item in detail_payload["records"][0]["items"]} == {
        "shared.dashboard_market_data_pulls"
    }
    operations = client.get(
        "/api/operations/summary?include_details=true",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    operations_again = client.get(
        "/api/operations/summary",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    assert operations.status_code == 200
    assert "tickSummary" not in operations.json()
    assert {"venue": "alpaca", "reason": "insufficient historical bars", "count": 1} in operations.json()["scanner"]["rejectionBreakdown"]
    assert "alpaca: insufficient historical bars (1)" in operations.json()["scanner"]["message"]
    assert operations_again.status_code == 200
    assert "tickSummary" not in operations_again.json()
    tick_summary = client.get(
        "/api/operations/tick-summary?window_minutes=1440",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    tick_summary_again = client.get(
        "/api/operations/tick-summary?window_minutes=1440",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    tick_summary_rows = client.app.state.services.registry.state.rows("shared.tick_summaries")
    assert tick_summary.status_code == 200
    tick_summary_payload = tick_summary.json()
    assert tick_summary_payload["runCount"] == 1
    assert tick_summary_payload["latestRunId"] == payload["runId"]
    assert tick_summary_payload["status"] == "unavailable"
    assert tick_summary_payload["warnings"] == [
        "OpenAI tick summary is not configured; set OPENAI_API_KEY to enable it."
    ]
    assert tick_summary_again.status_code == 200
    assert len(tick_summary_rows) == 1


def test_req_ui_008_07_dashboard_exposes_tick_schedule_data_scenario_and_realtime() -> None:
    """TST-REQ-UI-008-07: Validates REQ-UI-008, REQ-DAT-008, and REQ-OBS-005

    Given: an authorized dashboard user has recorded a manual tick
    When: tick timing, data explorer, scenario, and realtime endpoints are called
    Then: the dashboard can inspect the run without unsafe write access or refresh-only state
    """

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
        polymarket_us_enabled=True,
    )
    app = create_app(settings)
    app.state.services.runtime_status.market_data_fetcher = FakeMarketDataFetcher(
        {
            "polymarket_us": MarketDataProviderResult(
                venue="polymarket_us",
                status="pulled",
                source="polymarket gamma and clob api",
                message="Fetched 1 Polymarket priced candidate.",
                candidates=[
                    {
                        "id": "polymarket_us:market-2:yes-token",
                        "venue": "polymarket_us",
                        "market": "Will inflation fall? - Yes",
                        "price": "0.47",
                        "liquidity": "250",
                        "spread": "0.02",
                        "state": "priced",
                        "pulledAt": datetime.now(UTC).isoformat(),
                    }
                ],
            )
        }
    )
    token = app.state.services.auth.create_session_token(username="yaw")
    client = TestClient(app)
    auth_headers = {"Authorization": f"Bearer {token}", "X-Environment": "development"}
    mutation_headers = {
        **auth_headers,
        "Origin": "http://localhost:3100",
        "X-CSRF-Token": "csrf-token",
    }

    manual = client.post(
        "/api/operations/manual-run",
        headers=mutation_headers,
        json={"environment": "development", "mode": "scanner_only"},
    )
    run_id = manual.json()["runId"]
    schedule = client.get("/api/operations/tick-schedule", headers=auth_headers)
    explorer = client.get("/api/data/explorer", headers=auth_headers)
    data_query = client.post(
        "/api/data/query",
        headers=auth_headers,
        json={
            "query": "select id, venue, candidate_count from market_data_pulls where venue = 'polymarket_us' limit 5"
        },
    )
    joined_query = client.post(
        "/api/data/query",
        headers=auth_headers,
        json={
            "query": (
                "select p.id, p.status, m.venue, m.candidate_count "
                "from pipeline_runs p join market_data_pulls m on p.id = m.run_id "
                "where m.venue = 'polymarket_us' limit 5"
            )
        },
    )
    generated_query = client.post(
        "/api/data/query/generate",
        headers=auth_headers,
        json={"prompt": "show me market data by tick run"},
    )
    rejected_query = client.post(
        "/api/data/query",
        headers=auth_headers,
        json={"query": "delete from market_data_pulls"},
    )
    scenario = client.post(
        "/api/scenario/analyze",
        headers=auth_headers,
        json={
            "runId": run_id,
            "stepKey": "scanner",
            "prompt": "Why did this stop before trading?",
            "configOverrides": [
                {"path": "scanner.polymarket.max_spread", "value": "0.08"},
                {"path": "scanner.polymarket.max_hours_to_resolution", "value": "336"},
            ],
        },
    )
    realtime = client.get("/api/dashboard/realtime-snapshot", headers=auth_headers)

    assert manual.status_code == 202
    assert schedule.status_code == 200
    assert schedule.json()["lastTickRunId"] == run_id
    assert schedule.json()["lastTickSource"] == "pipeline_run"
    assert schedule.json()["nextTickAt"]
    assert explorer.status_code == 200
    assert "market_data_pulls" in {dataset["id"] for dataset in explorer.json()["datasets"]}
    assert data_query.status_code == 200
    assert data_query.json()["dataset"]["id"] == "market_data_pulls"
    assert data_query.json()["rows"][0]["candidate_count"] == 1
    assert joined_query.status_code == 200
    assert joined_query.json()["dataset"]["label"] == "Joined datasets"
    assert joined_query.json()["rows"][0]["m.venue"] == "polymarket_us"
    assert generated_query.status_code == 200
    assert " join " in generated_query.json()["query"].lower()
    assert "market_data_pulls" in generated_query.json()["query"]
    assert generated_query.json()["model"] == "local-data-query-helper"
    assert rejected_query.status_code == 422
    assert scenario.status_code == 200
    assert scenario.json()["run"]["id"] == run_id
    assert scenario.json()["selectedStepKey"] == "scanner"
    assert scenario.json()["answer"]["title"] == "Scenario help"
    assert scenario.json()["configTests"][0]["path"] == "scanner.polymarket.max_spread"
    assert len(scenario.json()["configTests"]) == 2
    assert scenario.json()["recommendedConfigSet"]["title"] == "Scanner copilot plan"
    assert scenario.json()["recommendedConfigSet"]["runMode"] == "scanner_only"
    assert any(
        patch["path"] == "scanner.polymarket.min_liquidity"
        for patch in scenario.json()["recommendedConfigSet"]["patches"]
    )
    assert realtime.status_code == 200
    assert realtime.json()["tickSchedule"]["lastTickRunId"] == run_id
    assert realtime.json()["operations"]["pipelineRuns"] == []
    assert (
        realtime.json()["operations"]["scanner"]["status"]
        == manual.json()["scannerRun"]["status"]
    )
    assert realtime.json()["operations"]["scanner"]["candidateCount"] == 1
    assert realtime.json()["operations"]["scanner"]["detailsDeferred"] is True


def test_req_ui_014_02_dashboard_reads_latest_venue_rows_and_reuses_snapshot_state(
    monkeypatch,
) -> None:
    """TST-REQ-UI-014-02: Validates REQ-UI-014."""

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        environment=Environment.DEVELOPMENT,
        polymarket_us_enabled=True,
        alpaca_enabled=True,
    )
    app = create_app(settings)
    runtime = app.state.services.runtime_status
    state = app.state.services.registry.state
    now = datetime.now(UTC)
    for venue in (Venue.POLYMARKET_US.value, Venue.ALPACA.value):
        for age_minutes in (2, 1):
            state.insert(
                "shared.dashboard_market_data_pulls",
                {
                    "id": f"{venue}-{age_minutes}",
                    "environment": Environment.DEVELOPMENT.value,
                    "venue": venue,
                    "status": "pulled",
                    "trigger": "scheduled",
                    "source": "fixture",
                    "candidates": [{"id": f"{venue}-candidate-{age_minutes}"}],
                    "message": "fixture pull",
                    "error_code": None,
                    "run_id": f"run-{age_minutes}",
                    "created_at": now - timedelta(minutes=age_minutes),
                },
            )

    original_rows = state.rows
    original_count = state.count
    market_reads: list[dict] = []
    pipeline_reads: list[dict] = []
    audit_row_reads = 0
    count_reads: list[tuple[str, dict]] = []

    def tracked_rows(table_name: str, **kwargs):
        nonlocal audit_row_reads
        if table_name == "shared.dashboard_market_data_pulls":
            market_reads.append(kwargs)
        if table_name == "shared.pipeline_runs":
            pipeline_reads.append(kwargs)
        if table_name == "shared.audit_events":
            audit_row_reads += 1
        return original_rows(table_name, **kwargs)

    def tracked_count(table_name: str, **kwargs):
        count_reads.append((table_name, kwargs))
        return original_count(table_name, **kwargs)

    monkeypatch.setattr(state, "rows", tracked_rows)
    monkeypatch.setattr(state, "count", tracked_count)
    config_payload = {
        "default_selected_venue": Venue.POLYMARKET_US.value,
        "venues": {
            Venue.POLYMARKET_US.value: {"enabled": True},
            Venue.ALPACA.value: {"enabled": True},
        },
    }

    market_data = runtime.market_data_pull(
        environment=Environment.DEVELOPMENT,
        config_payload=config_payload,
    )

    assert market_data["candidateCount"] == 2
    assert len(market_reads) == 2
    assert all(read["limit"] == 1 for read in market_reads)
    assert {read["filters"]["venue"] for read in market_reads} == {
        Venue.POLYMARKET_US.value,
        Venue.ALPACA.value,
    }

    worker_calls = 0
    schedule_calls = 0
    original_worker_status = runtime.worker_status
    original_tick_schedule = runtime.tick_schedule

    def tracked_worker_status():
        nonlocal worker_calls
        worker_calls += 1
        return original_worker_status()

    def tracked_tick_schedule(**kwargs):
        nonlocal schedule_calls
        schedule_calls += 1
        return original_tick_schedule(**kwargs)

    monkeypatch.setattr(runtime, "worker_status", tracked_worker_status)
    monkeypatch.setattr(runtime, "tick_schedule", tracked_tick_schedule)
    token = app.state.services.auth.create_session_token(username="yaw")
    response = TestClient(app).get(
        "/api/dashboard/realtime-snapshot",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Environment": Environment.DEVELOPMENT.value,
        },
    )

    assert response.status_code == 200
    assert worker_calls == 1
    assert schedule_calls == 1
    assert audit_row_reads == 0
    assert (
        "shared.audit_events",
        {"filters": {"environment": Environment.DEVELOPMENT.value}},
    ) in count_reads
    assert any(
        read.get("limit") == 1
        and read.get("newest_first") is True
        and read.get("filters") == {"environment": Environment.DEVELOPMENT.value}
        for read in pipeline_reads
    )


def test_req_ui_008_05_manual_run_modes_stop_at_requested_pipeline_stage() -> None:
    """TST-REQ-UI-008-05: Validates REQ-UI-008, REQ-DAT-008, and REQ-OBS-005

    Given: provider-backed market data is available
    When: an operator requests data-only and scanner-only manual modes
    Then: the pipeline records skipped downstream stages without forcing live execution
    """

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
        polymarket_us_enabled=False,
        alpaca_enabled=True,
    )
    app = create_app(settings)
    app.state.services.runtime_status.market_data_fetcher = FakeMarketDataFetcher(
        {
            "alpaca": MarketDataProviderResult(
                venue="alpaca",
                status="pulled",
                source="alpaca market data api",
                message="Fetched 1 Alpaca priced candidate.",
                candidates=[
                    {
                        "id": "alpaca:SPY",
                        "venue": "alpaca",
                        "symbol": "SPY",
                        "price": "500.01",
                        "liquidity": "3",
                        "spread": "0.02",
                        "state": "priced",
                        "pulledAt": datetime.now(UTC).isoformat(),
                    }
                ],
            ),
        }
    )
    token = app.state.services.auth.create_session_token(username="yaw")
    client = TestClient(app)
    headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "http://localhost:3100",
        "X-CSRF-Token": "csrf-token",
    }

    data_import = client.post(
        "/api/operations/manual-run",
        headers=headers,
        json={"environment": "development", "mode": "data_import"},
    )
    scanner_only = client.post(
        "/api/operations/manual-run",
        headers=headers,
        json={"environment": "development", "mode": "scanner_only"},
    )

    data_payload = data_import.json()
    scanner_payload = scanner_only.json()
    assert data_import.status_code == 202
    assert data_payload["requestedMode"] == "data_import"
    assert data_payload["scannerRun"]["status"] == "skipped"
    assert data_payload["reasoningRun"]["status"] == "skipped"
    assert data_payload["executionRun"]["status"] == "skipped"
    assert data_payload["pipelineRun"]["steps"][0]["status"] == "completed"
    assert data_payload["pipelineRun"]["steps"][1]["status"] == "skipped"
    assert scanner_only.status_code == 202
    assert scanner_payload["requestedMode"] == "scanner_only"
    assert scanner_payload["scannerRun"]["status"] in {"completed", "no_candidates_passed"}
    assert scanner_payload["reasoningRun"]["status"] == "skipped"
    assert scanner_payload["strategyRun"]["status"] == "skipped"
    assert scanner_payload["executionRun"]["status"] == "skipped"
    assert scanner_payload["pipelineRun"]["metadata"]["requestedMode"] == "scanner_only"


def test_req_ui_008_08_non_live_manual_runs_cap_provider_scope() -> None:
    """TST-REQ-UI-008-08: Validates REQ-UI-008 and REQ-DAT-008

    Given: production config has a large provider universe
    When: a non-live manual run mode prepares the next config
    Then: provider fetch scope is bounded without changing full-live-gated mode
    """

    config = {
        "live_enabled": True,
        "scanner": {"polymarket": {"market_data_limit": 500}},
        "alpaca": {
            "symbol_presets": [],
            "custom_symbols": [f"TST{i}" for i in range(40)],
            "symbol_universe": [f"TST{i}" for i in range(40)],
        },
    }

    bounded = _config_for_manual_mode(config, "full_dry_run")
    live_gated = _config_for_manual_mode(config, "full_live_gated")

    assert bounded["live_enabled"] is False
    assert bounded["scanner"]["polymarket"]["market_data_limit"] == 10
    assert bounded["alpaca"]["symbol_presets"] == []
    assert len(bounded["alpaca"]["custom_symbols"]) == 20
    assert bounded["alpaca"]["custom_symbols"][0] == "TST0"
    assert bounded["alpaca"]["custom_symbols"][-1] == "TST19"
    assert live_gated["live_enabled"] is True
    assert live_gated["scanner"]["polymarket"]["market_data_limit"] == 500
    assert len(live_gated["alpaca"]["custom_symbols"]) == 40


def test_req_ui_004_12_daily_tick_summary_endpoint_supports_cached_and_forced_runs() -> None:
    """TST-REQ-UI-004-12: Validates REQ-UI-004, REQ-UI-008, and REQ-OBS-005

    Given: an authenticated dashboard user opens the consumer dashboard
    When: daily tick summary endpoints are requested
    Then: the dashboard receives a one-day summary and can force a refresh on demand
    """
    client, token = _client()
    headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "http://localhost:3100",
        "X-CSRF-Token": "csrf-token",
    }

    cached = client.get(
        "/api/operations/tick-summary?window_minutes=1440",
        headers={"Authorization": f"Bearer {token}"},
    )
    forced = client.post(
        "/api/operations/tick-summary",
        headers=headers,
        json={"window_minutes": 1440},
    )

    assert cached.status_code == 200
    assert cached.json()["windowMinutes"] == 1440
    assert forced.status_code == 200
    assert forced.json()["windowMinutes"] == 1440
    assert "summaryMarkdown" in forced.json()


def test_req_dat_009_11_operations_summary_exposes_historical_import_status() -> None:
    """TST-REQ-DAT-009-11: Validates REQ-DAT-009 and REQ-UI-004

    Given: historical Polymarket import rows and checkpoints exist
    When: the operations summary endpoint is requested
    Then: the dashboard receives counts, checkpoint state, and freshness metadata
    """
    client, token = _client()
    shared = client.app.state.services.registry.shared()
    observed = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    market = shared.record_polymarket_gamma_market(
        environment=Environment.DEVELOPMENT,
        market_id="market-1",
        question="Will BTC close above 100k?",
        condition_id="0xcondition",
        active=False,
        closed=True,
        tokens=[{"token_id": "yes-token", "outcome": "YES"}],
        raw_payload={"id": "market-1"},
        fetched_at=observed,
    )
    fill = shared.record_polymarket_chain_fill_event(
        environment=Environment.DEVELOPMENT,
        exchange_contract="0xe111180000d2663c0091e4f400237545b87b996b",
        block_number=100,
        log_index=2,
        transaction_hash="0xtx",
        raw_event={"event": "OrderFilled"},
        maker_address="0x1111111111111111111111111111111111111111",
        taker_address="0x2222222222222222222222222222222222222222",
        asset_id="yes-token",
        block_timestamp=observed,
    )
    shared.record_polymarket_trade(
        environment=Environment.DEVELOPMENT,
        market_id="market-1",
        asset_id="yes-token",
        wallet_address="0x1111111111111111111111111111111111111111",
        side="buy",
        price=Decimal("0.42"),
        size=Decimal("10"),
        notional_usd=Decimal("4.20"),
        realized_pnl_usd=Decimal("1.00"),
        transaction_hash="0xtx",
        block_number=100,
        raw_event_id=fill["id"],
        market_record_id=market["id"],
        traded_at=observed,
    )
    stat = shared.record_polymarket_wallet_performance_stat(
        environment=Environment.DEVELOPMENT,
        wallet_address="0x1111111111111111111111111111111111111111",
        trade_count=125,
        win_rate=Decimal("0.74"),
        total_realized_pnl_usd=Decimal("220"),
        source="polymarket_trades",
        calculated_at=observed,
    )
    shared.record_polymarket_target_wallet_snapshot(
        environment=Environment.DEVELOPMENT,
        min_trade_count=100,
        min_win_rate=Decimal("0.70"),
        wallets=[{"walletAddress": stat["wallet_address"]}],
        source_stat_ids=[stat["id"]],
        created_at=observed,
    )
    shared.upsert_historical_import_checkpoint(
        environment=Environment.DEVELOPMENT,
        source="polygon_order_filled",
        cursor_type="block_number",
        cursor_value="100",
        status="complete",
        metadata={"windows": 1},
        last_success_at=observed,
        updated_at=observed,
    )

    response = client.get(
        "/api/operations/summary?include_history=true",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    historical = response.json()["historicalImport"]

    assert response.status_code == 200
    assert historical["status"] == "complete"
    assert historical["counts"]["gammaMarkets"] == 1
    assert historical["counts"]["chainFills"] == 1
    assert historical["counts"]["trades"] == 1
    assert historical["counts"]["walletStats"] == 1
    assert historical["counts"]["targetWalletSnapshots"] == 1
    assert historical["checkpoints"][0]["source"] == "polygon_order_filled"
    assert historical["checkpoints"][0]["cursorValue"] == "100"
    assert historical["lastUpdatedAt"] == observed.isoformat()


def test_req_alp_017_06_operations_summary_exposes_broker_history_status() -> None:
    """TST-REQ-ALP-017-06: Validates REQ-ALP-017, REQ-DAT-008, and REQ-UI-004

    Given: Alpaca broker history rows and checkpoints exist
    When: the operations summary endpoint is requested
    Then: the dashboard receives broker counts separate from Polymarket import status
    """
    client, token = _client()
    shared = client.app.state.services.registry.shared()
    observed = datetime(2026, 6, 25, 16, 0, tzinfo=UTC)
    shared.record_alpaca_historical_order(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        order_id="order-1",
        symbol="SPY",
        side="buy",
        status="filled",
        raw_payload={"id": "order-1"},
        submitted_at=observed,
    )
    fill = shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        activity_id="fill-1",
        order_id="order-1",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("500"),
        filled_at=observed,
        raw_payload={"id": "fill-1"},
    )
    position = shared.record_alpaca_historical_position(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        symbol="SPY",
        quantity=Decimal("1"),
        average_entry_price=Decimal("500"),
        market_value=Decimal("505"),
        unrealized_pnl_usd=Decimal("5"),
        raw_payload={"symbol": "SPY"},
        observed_at=observed,
    )
    shared.record_alpaca_broker_account_snapshot(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        account_status="ACTIVE",
        buying_power=Decimal("1000"),
        raw_payload={"id": "acct-1"},
        observed_at=observed,
    )
    shared.record_stock_bar(
        environment=Environment.DEVELOPMENT,
        symbol="SPY",
        timeframe="1Day",
        bar_start_at=observed,
        open_price=Decimal("500"),
        high_price=Decimal("506"),
        low_price=Decimal("499"),
        close_price=Decimal("505"),
        volume=Decimal("1000000"),
        source="alpaca market data api",
        raw_payload={"t": observed.isoformat()},
    )
    shared.record_alpaca_symbol_pnl_snapshot(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        symbol="SPY",
        open_quantity=Decimal("1"),
        realized_pnl_usd=Decimal("0"),
        unrealized_pnl_usd=Decimal("5"),
        total_pnl_usd=Decimal("5"),
        cost_basis=Decimal("500"),
        market_value=Decimal("505"),
        fill_ids=[fill["id"]],
        position_id=position["id"],
        calculated_at=observed,
    )
    shared.upsert_historical_import_checkpoint(
        environment=Environment.DEVELOPMENT,
        source="alpaca_broker_history:paper",
        cursor_type="timestamp",
        cursor_value=observed.isoformat(),
        status="stored",
        metadata={"fills": 1},
        last_success_at=observed,
        updated_at=observed,
    )

    response = client.get(
        "/api/operations/summary?include_history=true",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    payload = response.json()
    broker = payload["brokerHistory"]

    assert response.status_code == 200
    assert payload["historicalImport"]["status"] == "idle"
    assert broker["status"] == "stored"
    assert broker["counts"]["orders"] == 1
    assert broker["counts"]["fills"] == 1
    assert broker["counts"]["positions"] == 1
    assert broker["counts"]["accountSnapshots"] == 1
    assert broker["counts"]["bars"] == 1
    assert broker["counts"]["pnlSnapshots"] == 1
    assert broker["checkpoints"][0]["source"] == "alpaca_broker_history:paper"
    assert broker["lastUpdatedAt"] == observed.isoformat()


def test_req_ui_010_03_model_summary_reads_provider_schema_rows() -> None:
    """TST-REQ-UI-010-03: Validates REQ-UI-010

    Given: provider schema rows exist for a model
    When: the model summary endpoint is requested
    Then: positions, decisions, orders, budget, and P&L come from backend data
    """

    client, token = _client()
    state = client.app.state.services.registry.state
    now = datetime.now(UTC)
    state.insert(
        "openai.positions",
        {
            "position_id": "pos-1",
            "state": "open",
            "realized_pnl": Decimal("3.25"),
            "unrealized_pnl": Decimal("1.75"),
            "updated_at": now,
        },
    )
    state.insert(
        "openai.trade_decisions",
        {
            "id": "decision-1",
            "environment": "development",
            "model_provider": ModelProvider.OPENAI.value,
            "venue": "alpaca",
            "instrument_identifier": "QQQ",
            "instrument_type": "etf",
            "signal_inputs": {},
            "decision": "buy",
            "order_type": "limit",
            "size": Decimal("2"),
            "created_at": now,
        },
    )
    state.insert(
        "openai.order_events",
        {
            "id": "event-1",
            "order_id": "order-1",
            "event_type": "submitted",
            "venue": "alpaca",
            "model_provider": ModelProvider.OPENAI.value,
            "message": "dry-run submitted",
            "created_at": now,
        },
    )
    state.insert(
        "shared.ai_usage_events",
        {
            "id": "usage-1",
            "environment": "development",
            "provider": ModelProvider.OPENAI.value,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "cost_usd": Decimal("0.15"),
            "created_at": now,
        },
    )

    response = client.get(
        "/api/models/openai/summary",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["positions"][0]["positionId"] == "pos-1"
    assert payload["decisions"][0]["instrument"] == "QQQ"
    assert payload["orders"][0]["id"] == "order-1"
    assert payload["budget"]["used_usd"] == "0.15"
    assert payload["pnl"] == "5.00"


def test_req_dat_008_03_scheduled_run_records_provider_statuses_separately() -> None:
    """TST-REQ-DAT-008-03: Validates REQ-DAT-008 and REQ-OBS-005

    Given: scheduled provider ingestion has one venue rate-limited and one venue pulled
    When: the scheduled run records dashboard market data
    Then: per-venue statuses are preserved and the summary is marked partial
    """

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
        polymarket_us_enabled=True,
        alpaca_enabled=True,
    )
    app = create_app(settings)
    app.state.services.runtime_status.market_data_fetcher = FakeMarketDataFetcher(
        {
            "polymarket_us": MarketDataProviderResult(
                venue="polymarket_us",
                status="rate_limited",
                source="polymarket gamma and clob api",
                message="polymarket active markets was rate limited by the provider.",
                candidates=[],
                error_code="provider_rate_limited",
            ),
            "alpaca": MarketDataProviderResult(
                venue="alpaca",
                status="pulled",
                source="alpaca market data api",
                message="Fetched 1 Alpaca priced candidate.",
                candidates=[
                    {
                        "id": "alpaca:SPY",
                        "venue": "alpaca",
                        "symbol": "SPY",
                        "price": "500.01",
                        "liquidity": "3",
                        "spread": "0.02",
                        "state": "priced",
                        "pulledAt": datetime.now(UTC).isoformat(),
                    }
                ],
            ),
        }
    )
    app.state.services.runtime_status.stock_universe_refresher = StockUniverseRefreshService(
        app.state.services.registry,
        source=StaticStockUniverseSource({"sp500": ["AAPL"], "nasdaq100": ["MSFT"]}),
    )

    config_payload = app.state.services.runtime_status.runtime_config_payload()
    config_payload["default_selected_venue"] = Venue.ALPACA.value
    result = app.state.services.runtime_status.trigger_scheduled_run(
        environment=Environment.DEVELOPMENT,
        config_payload=config_payload,
    )
    job_rows = app.state.services.registry.state.rows("shared.job_runs")
    pull_rows = app.state.services.registry.state.rows("shared.dashboard_market_data_pulls")
    pipeline_rows = app.state.services.registry.state.rows("shared.pipeline_runs")
    pipeline_step_rows = app.state.services.registry.state.rows("shared.pipeline_steps")

    assert result["status"] == "partial"
    assert result["stockUniverseRefresh"]["status"] == "refreshed"
    assert result["pipelineRun"]["status"] == "partial"
    assert result["pipelineRun"]["steps"][0]["status"] == "partial"
    assert result["pipelineRun"]["steps"][0]["recordIds"] == [
        pull["id"] for pull in result["marketDataPulls"]
    ]
    assert result["marketDataPull"]["status"] == "partial"
    assert app.state.services.runtime_status.worker_status()["state"] == "ok"
    assert {pull["status"] for pull in result["marketDataPull"]["venues"]} == {
        "rate_limited",
        "pulled",
    }
    assert result["marketDataPull"]["candidateCount"] == 1
    assert pull_rows[0]["error_code"] == "provider_rate_limited"
    assert pipeline_rows[0]["trigger"] == "scheduled"
    assert len(pipeline_step_rows) == 5
    assert job_rows[-1]["job_name"] == "market-data-ingestion"
    assert job_rows[-1]["status"] == "partial"
    assert [call["venue"] for call in app.state.services.runtime_status.market_data_fetcher.calls] == [
        Venue.POLYMARKET_US.value,
        Venue.ALPACA.value,
    ]
    assert job_rows[-1]["heartbeat_at"] == pipeline_rows[0]["completed_at"]
    assert pipeline_rows[0]["completed_at"] >= pipeline_rows[0]["started_at"]


def test_req_kal_007_03_scheduled_execution_rereads_kill_switch_and_config() -> None:
    """TST-REQ-KAL-007-03: scheduled stages reread current persisted controls."""

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
    )
    app = create_app(settings)
    runtime = app.state.services.runtime_status
    runtime.market_data_fetcher = FakeMarketDataFetcher(
        {
            Venue.POLYMARKET_US.value: MarketDataProviderResult(
                venue=Venue.POLYMARKET_US.value,
                status="empty",
                source="test",
                message="No candidates.",
                candidates=[],
            )
        }
    )
    captured: dict[str, object] = {}
    context_reads = 0
    original_run_execution = runtime.lifecycle.run_execution

    def capture_execution(**kwargs):
        captured["kill_switch_active"] = kwargs["kill_switch_active"]
        captured["config_payload"] = kwargs["config_payload"]
        return original_run_execution(**kwargs)

    runtime.lifecycle.run_execution = capture_execution
    initial_config = runtime.runtime_config_payload()
    fresh_config = runtime.runtime_config_payload()
    fresh_config["venues"][Venue.KALSHI.value]["enabled"] = False
    fresh_config["risk"][Venue.KALSHI.value]["max_position_usd"] = "0.00"

    def current_context():
        nonlocal context_reads
        context_reads += 1
        return fresh_config, True

    result = runtime.trigger_scheduled_run(
        environment=Environment.DEVELOPMENT,
        config_payload=initial_config,
        kill_switch_active=False,
        runtime_context_reader=current_context,
    )

    assert context_reads == 3
    assert result["reasoningRun"]["status"] == "skipped"
    assert result["strategyRun"]["status"] == "skipped"
    assert captured["kill_switch_active"] is True
    assert captured["config_payload"] is fresh_config


def test_req_ui_010_02_dashboard_summary_shows_token_cost_and_profitability() -> None:
    """TST-REQ-UI-010-02: Validates REQ-UI-010, REQ-CMP-002, and REQ-OBS-005

    Given: persisted AI usage, position P&L, AWS fallback preferences, and market data
    When: dashboard summary is requested
    Then: token spend, AI cost, fallback AWS cost, market pull, and net profitability are returned
    """

    client, token = _client()
    state = client.app.state.services.registry.state
    now = datetime.now(UTC)
    state.insert(
        "shared.ai_usage_events",
        {
            "id": "usage-1",
            "environment": "development",
            "provider": "openai",
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "cost_usd": Decimal("0.45"),
            "created_at": now,
        },
    )
    state.insert(
        "openai.positions",
        {
            "position_id": "pos-1",
            "state": "closed",
            "realized_pnl": Decimal("12.50"),
            "unrealized_pnl": Decimal("1.25"),
            "updated_at": now,
        },
    )
    state.insert(
        "shared.dashboard_market_data_pulls",
        {
            "id": "pull-1",
            "environment": "development",
            "venue": "polymarket_us",
            "status": "pulled",
            "trigger": "scheduled",
            "source": "test snapshot",
            "candidates": [
                {
                    "id": "will-fed-cut",
                    "venue": "polymarket_us",
                    "market": "Will the Fed cut rates?",
                    "price": "0.42",
                    "liquidity": "1000",
                    "spread": "0.03",
                    "state": "candidate",
                    "pulledAt": now.isoformat(),
                }
            ],
            "message": "One candidate captured.",
            "error_code": None,
            "run_id": "run-1",
            "created_at": now,
        },
    )
    client.put(
        "/api/preferences",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "settings": {
                "theme": "light",
                "timeZone": "system",
                "awsMonthlyInfraCostUsd": "30.00",
            }
        },
    )

    response = client.get(
        "/api/dashboard/summary",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["marketData"]["candidateCount"] == 1
    assert payload["economics"]["ai"]["totalTokens"] == 1500
    assert payload["economics"]["ai"]["totalCostUsd"] == "0.45"
    assert payload["economics"]["aws"]["dailyInfraCostEstimateUsd"] == "1.00"
    assert payload["economics"]["aws"]["source"] == "user preference fallback"
    assert payload["economics"]["aws"]["scope"] == "fallback"
    assert payload["economics"]["trading"]["totalPnlUsd"] == "13.75"
    assert payload["economics"]["profitability"]["netAfterRecordedCostsUsd"] == "12.30"
    assert payload["economics"]["history"]["stored"] is True
    assert payload["economics"]["history"]["snapshots"][0]["aiTotalTokens"] == 1500
    snapshot_rows = state.rows("shared.economics_snapshots")
    assert len(snapshot_rows) == 1
    assert snapshot_rows[0]["ai_cost_usd"] == Decimal("0.45")
    assert snapshot_rows[0]["aws_daily_cost_usd"] == Decimal("1.00")
    assert snapshot_rows[0]["net_after_costs_usd"] == Decimal("12.30")


def test_req_ui_010_03_dashboard_summary_uses_real_aws_billing_when_available() -> None:
    """TST-REQ-UI-010-03: Validates REQ-UI-010 and REQ-OBS-005

    Given: Cost Explorer billing is attached and a saved fallback exists
    When: dashboard economics are requested
    Then: real AWS billing cost replaces the saved fallback in profitability math
    """

    client, token = _client()
    client.app.state.services.runtime_status.billing_adapter = FakeAwsBillingAdapter()
    state = client.app.state.services.registry.state
    now = datetime.now(UTC)
    state.insert(
        "shared.ai_usage_events",
        {
            "id": "usage-real-aws",
            "environment": "development",
            "provider": "openai",
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "cost_usd": Decimal("0.45"),
            "created_at": now,
        },
    )
    state.insert(
        "openai.positions",
        {
            "position_id": "pos-real-aws",
            "state": "closed",
            "realized_pnl": Decimal("12.50"),
            "unrealized_pnl": Decimal("1.25"),
            "updated_at": now,
        },
    )
    client.put(
        "/api/preferences",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "settings": {
                "theme": "light",
                "timeZone": "system",
                "awsMonthlyInfraCostUsd": "30.00",
            }
        },
    )

    response = client.get(
        "/api/economics/summary",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["aws"]["source"] == "aws cost explorer"
    assert payload["aws"]["scope"] == "tagged"
    assert payload["aws"]["dailyInfraCostEstimateUsd"] == "2.50"
    assert payload["aws"]["monthToDateCostUsd"] == "42.00"
    assert payload["aws"]["fallbackDailyCostUsd"] == "1.00"
    assert payload["profitability"]["netAfterRecordedCostsUsd"] == "10.80"
    snapshot_rows = state.rows("shared.economics_snapshots")
    assert snapshot_rows[0]["aws_source"] == "aws cost explorer"
    assert snapshot_rows[0]["aws_month_to_date_cost_usd"] == Decimal("42.00")

    history = client.get(
        f"/api/economics/history?month={snapshot_rows[0]['month_key']}",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    history_payload = history.json()

    assert history.status_code == 200
    assert history_payload["count"] == 1
    assert history_payload["snapshots"][0]["awsMonthToDateCostUsd"] == "42.00"
    assert history_payload["snapshots"][0]["netAfterRecordedCostsUsd"] == "10.80"


def test_req_ui_010_05_economics_summary_reuses_recent_snapshot() -> None:
    """TST-REQ-UI-010-05: Validates REQ-UI-010 and REQ-OBS-005

    Given: a recent economics snapshot exists from a dashboard refresh
    When: the dashboard requests economics again
    Then: the API reuses the recent snapshot instead of writing on every page load
    """

    client, token = _client()
    state = client.app.state.services.registry.state

    headers = {"Authorization": f"Bearer {token}", "X-Environment": "development"}
    first = client.get("/api/economics/summary", headers=headers)
    second = client.get("/api/economics/summary", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    snapshot_rows = state.rows("shared.economics_snapshots")
    assert len(snapshot_rows) == 1
    assert second.json()["history"]["stored"] is True
    assert second.json()["history"]["latestSnapshotId"] == snapshot_rows[0]["id"]


def test_req_ui_010_06_cost_explorer_dashboard_costs_are_cached() -> None:
    """TST-REQ-UI-010-06: Validates REQ-UI-010 and REQ-OBS-005

    Given: Cost Explorer returns a current tagged result
    When: dashboard costs are requested twice inside the cache window
    Then: the adapter reuses the first result and does not call Cost Explorer again
    """

    class FakeCostExplorerClient:
        def __init__(self) -> None:
            self.calls = 0

        def get_cost_and_usage(self, **_request: object) -> dict[str, object]:
            self.calls += 1
            return {
                "ResultsByTime": [
                    {
                        "Estimated": False,
                        "Total": {"UnblendedCost": {"Amount": "1.25"}},
                    }
                ]
            }

    client = FakeCostExplorerClient()
    adapter = CostExplorerBillingAdapter(client=client, cache_ttl_seconds=300)
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)

    first = adapter.dashboard_costs(environment=Environment.DEVELOPMENT, now=now)
    second = adapter.dashboard_costs(
        environment=Environment.DEVELOPMENT,
        now=now + timedelta(seconds=60),
    )

    assert first.daily_cost_usd == Decimal("1.25")
    assert second.month_to_date_cost_usd == Decimal("1.25")
    assert client.calls == 2


def test_req_ui_010_04_ai_usage_import_reports_provider_status_separately() -> None:
    """TST-REQ-UI-010-04: Validates REQ-LLM-002, REQ-UI-010, and REQ-OBS-005

    Given: no provider-side token import source is configured
    When: an operator triggers an AI usage import
    Then: the API records the import status and economics shows the provider import error state
    """

    client, token = _client()

    response = client.post(
        "/api/economics/ai-usage-import",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={"environment": "development", "provider": "openai"},
    )
    summary = client.get(
        "/api/economics/summary",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    import_rows = client.app.state.services.registry.shared().ai_usage_import_runs(
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
    )
    audit_rows = client.app.state.services.registry.state.rows("shared.audit_events")

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "unsupported"
    assert payload["errorCode"] == "provider_usage_import_unsupported"
    assert len(import_rows) == 1
    assert import_rows[0]["status"] == "unsupported"
    assert audit_rows[-1]["event_type"] == "ai_usage_import_trigger"
    assert summary.status_code == 200
    economics = summary.json()
    assert economics["ai"]["imports"]["count"] == 1
    assert economics["ai"]["imports"]["runs"][0]["status"] == "unsupported"
    assert economics["ai"]["errorState"]["status"] == "unsupported"
    assert economics["ai"]["providers"][0]["latestImportStatus"] == "unsupported"


def test_req_not_006_01_notification_status_requires_email_recipient(monkeypatch) -> None:
    """TST-REQ-NOT-006-01: Validates REQ-NOT-006

    Given: SES is configured with a domain identity but no recipient email
    When: notification status is rendered
    Then: the dashboard keeps notification delivery blocked
    """

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DASHBOARD_ALLOWED_USERS", "yaw")
    monkeypatch.setenv("BACKEND_TOKEN_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("SES_IDENTITY_EMAIL", "asyncdoc.net")
    monkeypatch.setenv("NOTIFICATION_RECIPIENTS", "operator:asyncdoc.net")

    app = create_app(AppSettings.from_env())
    token = app.state.services.auth.create_session_token(username="yaw")
    response = TestClient(app).get(
        "/api/notifications/settings",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "production"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "not_configured"
    assert payload["recipientCount"] == 0


def test_req_not_006_02_notification_test_sends_configured_email() -> None:
    """TST-REQ-NOT-006-02: Validates REQ-NOT-006 and REQ-OBS-004

    Given: an authenticated operator and configured notification recipients
    When: the operator requests a test notification
    Then: the API sends through the configured adapter and records the attempt
    """

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
        ses_identity_email="alerts@example.com",
        notification_recipients={"operator": "alerts@example.com"},
    )
    app = create_app(settings)
    adapter = InMemorySesEmailAdapter()
    app.state.services.runtime_status.lifecycle.notification_adapter = adapter
    client = TestClient(app)
    token = app.state.services.auth.create_session_token(username="yaw")

    response = client.post(
        "/api/notifications/test",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={"environment": "development", "message": "readiness check"},
    )
    payload = response.json()

    assert response.status_code == 202
    assert payload["sent"] is True
    assert payload["attemptRecorded"] is True
    assert payload["recipientCount"] == 1
    assert payload["messageId"] == "ses-message-1"
    assert adapter.sent_count == 1
    assert adapter.attempts[-1].recipients == ("alerts@example.com",)
    assert "readiness check" in adapter.attempts[-1].body
    records = app.state.services.runtime_status.notification_ledger.records
    assert records[-1].notification_type == "test_notification"
    assert records[-1].sent is True


def test_req_not_006_03_notification_test_reports_missing_adapter() -> None:
    """TST-REQ-NOT-006-03: Validates REQ-NOT-006 and REQ-OBS-004

    Given: notification recipients are configured but SES is unavailable
    When: the operator requests a test notification
    Then: the API returns a secret-safe delivery failure without claiming success
    """

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
        notification_recipients={"operator": "alerts@example.com"},
    )
    app = create_app(settings)
    app.state.services.runtime_status.lifecycle.notification_adapter = None
    client = TestClient(app)
    token = app.state.services.auth.create_session_token(username="yaw")

    response = client.post(
        "/api/notifications/test",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={"environment": "development"},
    )
    payload = response.json()

    assert response.status_code == 503
    assert payload["sent"] is False
    assert payload["attemptRecorded"] is False
    assert payload["skippedReason"] == "notification adapter not configured"
    records = app.state.services.runtime_status.notification_ledger.records
    assert records[-1].notification_type == "test_notification"
    assert records[-1].sent is False


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
            "Origin": "http://localhost:3100",
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


def test_req_ui_006_04_config_api_applies_active_stock_profile_as_one_version() -> None:
    """The active profile updates stock behavior without changing the live gate or account mode."""

    client, token = _client()
    headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "http://localhost:3100",
        "X-CSRF-Token": "csrf-token",
    }
    initial = client.put(
        "/api/config",
        headers=headers,
        json={
            "environment": "development",
            "version": "v1",
            "patches": [
                {"op": "replace", "path": "live_enabled", "value": True},
                {"op": "replace", "path": "alpaca.account_mode", "value": "live"},
                {"op": "replace", "path": "reasoning.alpaca.min_edge", "value": "0.09"},
            ],
        },
    )
    applied = client.post(
        "/api/config",
        headers=headers,
        json={
            "environment": "development",
            "expected_version": "v1",
            "version": "v2",
            "profile": "active_stock_day_trader",
        },
    )
    current = client.get("/api/config/current", headers={"Authorization": f"Bearer {token}"})

    assert initial.status_code == 200
    assert applied.status_code == 200
    assert applied.json()["new_version"] == "v2"
    settings = current.json()["settings"]
    assert settings["trading_profile"] == "active_stock_day_trader"
    assert settings["live_enabled"] is True
    assert settings["alpaca"]["account_mode"] == "live"
    assert settings["default_selected_venue"] == "alpaca"
    assert settings["venues"]["alpaca"]["enabled"] is True
    assert settings["reasoning"]["alpaca"]["min_edge"] == "0.015"
    assert settings["reasoning"]["max_prompts_per_provider_per_run"] == 4
    assert settings["scanner"]["alpaca"]["min_quote_liquidity"] == "0.5"
    assert settings["scanner"]["alpaca"]["max_spread"] == "1.00"
    assert settings["scanner"]["alpaca"]["strategies"]["momentum"]["min_change_pct"] == "0.005"
    assert settings["exit"]["alpaca"]["profit_target_pct"] == "0.02"
    assert settings["risk"]["alpaca"]["market_order_slippage_threshold"] == "0.005"
    assert settings["llm"]["openai"]["settings"]["budget_window_hours"] == 24
    audit_rows = client.app.state.services.registry.state.rows("shared.audit_events")
    assert audit_rows[-1]["metadata"]["path"] == "trading_profile"


def test_req_ui_005_04_config_api_persists_settings_per_user() -> None:
    """TST-REQ-UI-005-04: Validates REQ-UI-005

    Given: two authorized users in the same environment
    When: each user saves a different trading loop setting
    Then: each user reads back their own active config version from the database layer
    """
    settings = AppSettings(
        allowed_usernames=("yaw", "alex"),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.DEVELOPMENT,
    )
    app = create_app(settings)
    client = TestClient(app)
    yaw_token = app.state.services.auth.create_session_token(username="yaw")
    alex_token = app.state.services.auth.create_session_token(username="alex")

    def mutation_headers(token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        }

    yaw_save = client.put(
        "/api/config",
        headers=mutation_headers(yaw_token),
        json={
            "environment": "development",
            "version": "v1",
            "patches": [
                {"op": "replace", "path": "trading_loop_interval_seconds", "value": 60},
            ],
        },
    )
    alex_save = client.put(
        "/api/config",
        headers=mutation_headers(alex_token),
        json={
            "environment": "development",
            "version": "v1",
            "patches": [
                {"op": "replace", "path": "trading_loop_interval_seconds", "value": 120},
            ],
        },
    )
    yaw_current = client.get("/api/config/current", headers={"Authorization": f"Bearer {yaw_token}"})
    alex_current = client.get("/api/config/current", headers={"Authorization": f"Bearer {alex_token}"})
    rows = app.state.services.registry.state.rows("shared.config_versions")

    assert yaw_save.status_code == 200
    assert alex_save.status_code == 200
    assert yaw_current.json()["username"] == "yaw"
    assert yaw_current.json()["settings"]["trading_loop_interval_seconds"] == 60
    assert alex_current.json()["username"] == "alex"
    assert alex_current.json()["settings"]["trading_loop_interval_seconds"] == 120
    assert {(row["username"], row["version"]) for row in rows} == {("yaw", "v1"), ("alex", "v1")}
    assert all(row["active"] for row in rows)


def test_req_alp_014_03_config_api_saves_presets_and_additive_symbols() -> None:
    """TST-REQ-ALP-014-03: Validates REQ-ALP-014 and REQ-UI-005

    Given: the default Alpaca universe uses broad presets
    When: an operator adds a custom preset and one-off IPO symbol
    Then: the saved config keeps presets and resolves an additive universe
    """

    client, token = _client()
    response = client.put(
        "/api/config",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "environment": "development",
            "version": "v1",
            "patches": [
                {"op": "replace", "path": "alpaca.symbol_presets", "value": ["sp500", "nasdaq100", "new_ipos"]},
                {"op": "replace", "path": "alpaca.custom_symbols", "value": ["crcl"]},
                {"op": "replace", "path": "alpaca.custom_presets", "value": {"new_ipos": ["fig"]}},
            ],
        },
    )
    current = client.get("/api/config/current", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    alpaca = current.json()["settings"]["alpaca"]
    assert alpaca["symbol_presets"] == ["sp500", "nasdaq100", "new_ipos"]
    assert alpaca["custom_symbols"] == ["CRCL"]
    assert alpaca["custom_presets"] == {"new_ipos": ["FIG"]}
    assert "AAPL" in alpaca["symbol_universe"]
    assert "CRCL" in alpaca["symbol_universe"]
    assert "FIG" in alpaca["symbol_universe"]


def test_req_str_003_05_config_api_saves_scanner_thresholds() -> None:
    """TST-REQ-STR-003-05: Validates REQ-STR-003 and REQ-UI-005

    Given: scanner thresholds are editable config
    When: an operator saves Polymarket and stock scanner settings
    Then: the saved config is available to the next loop
    """
    client, token = _client()

    response = client.put(
        "/api/config",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "environment": "development",
            "version": "scanner-v1",
            "patches": [
                {"op": "replace", "path": "scanner.polymarket.min_depth", "value": "750"},
                {
                    "op": "replace",
                    "path": "scanner.alpaca.strategies.unusual_volume.min_ratio",
                    "value": "2.25",
                },
                {
                    "op": "replace",
                    "path": "scanner.alpaca.strategies.momentum.enabled",
                    "value": False,
                },
                {
                    "op": "replace",
                    "path": "reasoning.polymarket.min_edge",
                    "value": "0.08",
                },
                {
                    "op": "replace",
                    "path": "reasoning.alpaca.prompt_version",
                    "value": "stock-brain-v2",
                },
            ],
        },
    )
    current = client.get("/api/config/current", headers={"Authorization": f"Bearer {token}"})
    scanner = current.json()["settings"]["scanner"]
    reasoning = current.json()["settings"]["reasoning"]

    assert response.status_code == 200
    assert scanner["polymarket"]["min_depth"] == "750"
    assert scanner["alpaca"]["strategies"]["unusual_volume"]["min_ratio"] == "2.25"
    assert scanner["alpaca"]["strategies"]["momentum"]["enabled"] is False
    assert reasoning["polymarket"]["min_edge"] == "0.08"
    assert reasoning["alpaca"]["prompt_version"] == "stock-brain-v2"


def test_req_str_003_06_config_api_posts_recommendation_thresholds_for_production_bootstrap() -> None:
    """TST-REQ-STR-003-06: Validates REQ-STR-003 and REQ-UI-005

    Given: the production dashboard is still on the bootstrap config version
    When: an operator applies the balanced recommendation through the POST save path
    Then: the saved scanner and confidence settings are available to the next loop
    """

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        csrf_token="csrf-token",
        environment=Environment.PRODUCTION,
        trusted_origins=("https://codex-poly-bot.repetere.net",),
    )
    app = create_app(settings)
    token = app.state.services.auth.create_session_token(username="yaw")
    client = TestClient(app)

    response = client.post(
        "/api/config",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://codex-poly-bot.repetere.net",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "environment": "production",
            "expected_version": None,
            "patches": [
                {"op": "replace", "path": "scanner.polymarket.max_hours_to_resolution", "value": "210"},
                {"op": "replace", "path": "scanner.polymarket.max_spread", "value": "0.0625"},
                {"op": "replace", "path": "scanner.alpaca.max_spread", "value": "0.625"},
                {"op": "replace", "path": "scanner.alpaca.min_quote_liquidity", "value": "0.8"},
                {"op": "replace", "path": "reasoning.polymarket.min_confidence", "value": "0.72"},
                {"op": "replace", "path": "reasoning.alpaca.min_confidence", "value": "0.57"},
            ],
        },
    )
    current = client.get("/api/config/current", headers={"Authorization": f"Bearer {token}"})
    settings_payload = current.json()["settings"]

    assert response.status_code == 200
    assert response.json()["new_version"] == "v1"
    assert current.json()["version"] == "v1"
    assert settings_payload["scanner"]["polymarket"]["max_hours_to_resolution"] == "210"
    assert settings_payload["scanner"]["polymarket"]["max_spread"] == "0.0625"
    assert settings_payload["scanner"]["alpaca"]["max_spread"] == "0.625"
    assert settings_payload["scanner"]["alpaca"]["min_quote_liquidity"] == "0.8"
    assert settings_payload["reasoning"]["polymarket"]["min_confidence"] == "0.72"
    assert settings_payload["reasoning"]["alpaca"]["min_confidence"] == "0.57"


def test_req_str_003_07_config_api_returns_json_when_config_persistence_fails() -> None:
    """TST-REQ-STR-003-07: Validates REQ-STR-003 and REQ-UI-005

    Given: config version persistence is unavailable
    When: an operator applies a recommendation setting through the config API
    Then: the API returns a structured 503 response instead of an internal server error
    """

    client, token = _client()
    client.app.state.services.registry.state.fail_on_tables.add("shared.config_versions")

    response = client.post(
        "/api/config",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3100",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "environment": "development",
            "patches": [
                {"op": "replace", "path": "scanner.polymarket.max_spread", "value": "0.075"},
            ],
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "error_code": "config_persistence_unavailable",
        "message": "Config persistence is unavailable, so settings were not saved.",
    }


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
            "Origin": "http://localhost:3100",
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
