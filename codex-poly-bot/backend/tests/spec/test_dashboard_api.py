"""Spec tests for FastAPI dashboard API routers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.adapters.aws import AwsBillingCost
from app.domain import Environment, ModelProvider
from app.main import AppSettings, create_app
from app.services.market_data_provider import MarketDataProviderResult


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
    monkeypatch.setenv("ALPACA_SYMBOL_UNIVERSE", "spy, qqq, spy, nvda")

    app = create_app()
    settings = app.state.settings

    assert settings.environment == Environment.DEVELOPMENT
    assert settings.allowed_usernames == ("yawetse", "operator")
    assert settings.signing_secret == "deploy-token-secret"
    assert settings.csrf_token == "deploy-csrf"
    assert settings.trusted_origins == ("https://dashboard.example.com",)
    assert settings.alpaca_symbol_presets == ()
    assert settings.alpaca_symbol_universe == ("SPY", "QQQ", "NVDA")
    assert app.state.services.runtime_status.runtime_config_payload()["alpaca"]["symbol_universe"] == [
        "SPY",
        "QQQ",
        "NVDA",
    ]


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

    Given: deployed runtime flags and provider credentials
    When: the dashboard summary is requested
    Then: worker, notification, wallet, and account status are rendered from runtime state
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
    monkeypatch.setenv("POLYMARKET_KEY_ID", "pm-key-id")
    monkeypatch.setenv("POLYMARKET_SECRET_KEY", "pm-signing-key")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "pm-wallet-key")
    monkeypatch.setenv("ALPACA_KEY_ID", "alpaca-key-id")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "alpaca-signing-key")
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
    assert status_by_label["Wallet"]["value"] == "1 missing"
    assert status_by_label["Ingestion"]["state"] == "ok"
    assert status_by_label["Notification"]["state"] == "ok"
    assert status_by_label["Trading loop"]["value"] == "Live gated"
    credentials = {item["id"]: item for item in payload["wallet"]["credentials"]}
    assert credentials["polymarket_us-openai-wallet"]["status"] == "present"
    assert credentials["openai-api"]["status"] == "present"
    assert credentials["anthropic-api"]["status"] == "present"
    assert credentials["alpaca-claude-account"]["status"] == "reviewing"
    assert payload["notifications"]["recipientCount"] == 1
    assert "pm-wallet-key" not in str(payload)


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
    monkeypatch.setenv("ALPACA_KEY_ID", "alpaca-key-id")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "alpaca-signing-key")
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
    assert loop["schedule"]["intervalSeconds"] == 60
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
        "Selected venue",
        "Alpaca symbols",
        "Market candidates",
    }
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


def test_req_ui_004_05_dashboard_preferences_persist_theme_timezone_and_costs() -> None:
    """TST-REQ-UI-004-05: Validates REQ-UI-004 and REQ-OBS-004

    Given: an authorized dashboard user saves display preferences
    When: preferences are saved and reloaded
    Then: theme, time zone, and AWS monthly cost assumptions persist per user
    """

    client, token = _client()

    saved = client.put(
        "/api/preferences",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3000",
            "X-CSRF-Token": "csrf-token",
        },
        json={
            "settings": {
                "theme": "dark",
                "timeZone": "America/New_York",
                "awsMonthlyInfraCostUsd": "74.25",
            }
        },
    )
    loaded = client.get(
        "/api/preferences",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )
    audit_rows = client.app.state.services.registry.state.rows("shared.audit_events")

    assert saved.status_code == 200
    assert loaded.status_code == 200
    assert loaded.json()["settings"] == {
        "theme": "dark",
        "timeZone": "America/New_York",
        "awsMonthlyInfraCostUsd": "74.25",
    }
    assert audit_rows[-1]["event_type"] == "dashboard_preferences_change"


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

    response = client.post(
        "/api/operations/manual-run",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "http://localhost:3000",
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
    pipeline_rows = client.app.state.services.registry.state.rows("shared.pipeline_runs")
    pipeline_step_rows = client.app.state.services.registry.state.rows("shared.pipeline_steps")

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["pipelineRun"]["trigger"] == "manual"
    assert [step["label"] for step in payload["pipelineRun"]["steps"]] == [
        "Data Fetch",
        "Scanner",
        "Reasoning / Brain",
        "Execution",
        "Exit",
    ]
    assert payload["pipelineRun"]["steps"][0]["metrics"]["candidateCount"] == 2
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
    assert pipeline_rows[0]["id"] == payload["runId"]
    assert len(pipeline_step_rows) == 5
    assert any(row["job_name"] == "manual-trading-loop" for row in job_rows)
    assert audit_rows[-1]["event_type"] == "manual_loop_trigger"
    assert set(audit_rows[-1]["metadata"]["venues"]) == {"polymarket_us", "alpaca"}


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

    result = app.state.services.runtime_status.trigger_scheduled_run(
        environment=Environment.DEVELOPMENT,
        config_payload=app.state.services.runtime_status.runtime_config_payload(),
    )
    job_rows = app.state.services.registry.state.rows("shared.job_runs")
    pull_rows = app.state.services.registry.state.rows("shared.dashboard_market_data_pulls")
    pipeline_rows = app.state.services.registry.state.rows("shared.pipeline_runs")
    pipeline_step_rows = app.state.services.registry.state.rows("shared.pipeline_steps")

    assert result["status"] == "partial"
    assert result["pipelineRun"]["status"] == "partial"
    assert result["pipelineRun"]["steps"][0]["status"] == "partial"
    assert result["pipelineRun"]["steps"][0]["recordIds"] == [
        pull["id"] for pull in result["marketDataPulls"]
    ]
    assert result["marketDataPull"]["status"] == "partial"
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
            "Origin": "http://localhost:3000",
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
            "Origin": "http://localhost:3000",
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
            "Origin": "http://localhost:3000",
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
