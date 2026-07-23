"""Red-phase tests for Dashboard and GitHub OAuth."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.bootstrap import PROJECT_ROOT
from app.db import DatabaseState, PersistenceUnavailableError, RepositoryRegistry
from app.domain import Environment, InstrumentType, ModelProvider, Venue
from app.main import AppSettings, build_dashboard_api_services, _scheduler_config_username
from app.services import (
    ActorContext,
    AuditService,
    AuthService,
    ConfigAuthorizationError,
    ConfigChange,
    ConfigPatchOperation,
    ConfigService,
    ConfigValidationError,
    CredentialStatus,
    KillSwitchService,
    ComparisonGroup,
    PerformanceRecord,
    build_comparison_dashboard_view,
    build_dashboard_shell,
    build_dashboard_status,
    build_model_provider_summary,
    default_config_payload,
    render_wallet_dashboard_status,
)


def test_req_ui_001_01_backend_frontend_services_running_dashboard_loads_next_js() -> None:
    """TST-REQ-UI-001-01: Validates REQ-UI-001

    Given: backend and frontend services are running
    When: the dashboard loads
    Then: the Next.js UI retrieves data from FastAPI services
    """
    result = build_dashboard_shell(backend_available=True, frontend_available=True)

    assert result.status_code == 200
    assert result.data_source == "fastapi"
    assert result.degraded_sections == ()

def test_req_ui_001_02_fastapi_unavailable_dashboard_loads_status_views_ui_shows() -> None:
    """TST-REQ-UI-001-02: Validates REQ-UI-001

    Given: FastAPI is unavailable
    When: the dashboard loads status views
    Then: the UI shows degraded API state without exposing internals
    """
    result = build_dashboard_shell(
        backend_available=False,
        frontend_available=True,
        backend_error="Traceback: database password leaked",
    )

    assert result.status_code == 503
    assert result.degraded_sections == ("api",)
    assert result.public_message == "dashboard API unavailable"
    assert "Traceback" not in result.public_message

def test_req_ui_002_01_unauthenticated_user_dashboard_opened_github_oauth_login_required() -> None:
    """TST-REQ-UI-002-01: Validates REQ-UI-002

    Given: an unauthenticated user
    When: the dashboard is opened
    Then: GitHub OAuth login is required
    """
    service = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")

    result = service.authorize_request(None)

    assert not result.authenticated
    assert not result.authorized
    assert result.status_code == 401
    assert result.reason == "authentication required"

def test_req_ui_002_02_invalid_oauth_callback_state_value_login_completes_access() -> None:
    """TST-REQ-UI-002-02: Validates REQ-UI-002

    Given: an invalid OAuth callback or state value
    When: login completes
    Then: access is denied and the event is logged
    """
    service = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")

    result = service.complete_oauth_login(
        username="yaw",
        state="bad-state",
        expected_state="good-state",
        environment=Environment.DEVELOPMENT,
        ip_address="203.0.113.10",
    )
    audit_row = service.registry.state.rows("shared.audit_events")[0]

    assert not result.authorized
    assert result.status_code == 401
    assert result.reason == "invalid oauth state"
    assert audit_row["event_type"] == "authorization_denied"
    assert audit_row["action"] == "oauth.callback"

def test_req_ui_003_01_authenticated_github_username_on_allowlist_dashboard_access_checked() -> None:
    """TST-REQ-UI-003-01: Validates REQ-UI-003

    Given: an authenticated GitHub username on the allowlist
    When: dashboard access is checked
    Then: access is granted
    """
    service = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    token = service.create_session_token(username="yaw")

    result = service.authorize_request(token)

    assert result.authenticated
    assert result.authorized
    assert result.status_code == 200
    assert result.username == "yaw"

def test_req_ui_003_02_authenticated_github_username_not_on_allowlist_dashboard_access() -> None:
    """TST-REQ-UI-003-02: Validates REQ-UI-003

    Given: an authenticated GitHub username not on the allowlist
    When: dashboard access is checked
    Then: access is denied
    """
    service = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    token = service.create_session_token(username="not-allowed-user")

    result = service.authorize_request(
        token,
        environment=Environment.PRODUCTION,
        ip_address="198.51.100.42",
    )
    audit_row = service.registry.state.rows("shared.audit_events")[0]

    assert result.authenticated
    assert not result.authorized
    assert result.status_code == 403
    assert result.reason == "user not in allowlist"
    assert audit_row["actor"] == "not-allowed-user"
    assert audit_row["metadata"]["applied"] is False

def test_req_ui_004_01_authorized_user_status_pages_load_venue_model_wallet() -> None:
    """TST-REQ-UI-004-01: Validates REQ-UI-004

    Given: an authorized user
    When: status pages load
    Then: venue, model, wallet, ingestion, loop, position, order, and notification status are visible
    """
    result = build_dashboard_status(
        {
            "venue": {"polymarket_us": "enabled"},
            "model": {"openai": "ok", "claude": "ok"},
            "wallet": {"openai": "present"},
            "ingestion": {"polymarket_us": "fresh"},
            "loop": {"trading": "idle"},
            "position": {"open": 1},
            "order": {"recent": 2},
            "notification": {"ses": "ok"},
        }
    )

    assert result.visible_sections == (
        "venue",
        "model",
        "wallet",
        "ingestion",
        "loop",
        "position",
        "order",
        "notification",
    )
    assert result.degraded_sections == ()

def test_req_ui_004_02_status_source_unavailable_status_pages_load_dashboard_marks() -> None:
    """TST-REQ-UI-004-02: Validates REQ-UI-004

    Given: a status source is unavailable
    When: status pages load
    Then: the dashboard marks that source degraded rather than showing stale success
    """
    result = build_dashboard_status(
        {
            "venue": {"polymarket_us": "enabled"},
            "model": None,
            "wallet": {"openai": "present"},
            "ingestion": {"polymarket_us": "fresh"},
            "loop": {"trading": "idle"},
            "position": {"open": 1},
            "order": {"recent": 2},
            "notification": None,
        }
    )

    assert "model" in result.degraded_sections
    assert "notification" in result.degraded_sections
    assert result.sections["model"]["status"] == "degraded"

def test_req_ui_005_01_authorized_user_changes_supported_config_fields_dashboard_saves() -> None:
    """TST-REQ-UI-005-01: Validates REQ-UI-005

    Given: an authorized user changes supported config fields
    When: the dashboard saves them
    Then: venue flags, dry-run/live, loop, strategy, budget, risk, slippage, and notification settings persist
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    access = auth.authorize_request(auth.create_session_token(username="yaw"))
    service = ConfigService(auth.registry)

    result = service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=access,
        environment=Environment.DEVELOPMENT,
        expected_version=None,
        version="v1",
        patches=[
            ConfigPatchOperation("replace", "venues.polymarket_us.enabled", True),
            ConfigPatchOperation("replace", "trading_loop_interval_seconds", 60),
            ConfigPatchOperation("replace", "strategies.arbitrage.enabled", False),
            ConfigPatchOperation("replace", "llm.openai.budget_usd", "25.00"),
            ConfigPatchOperation("replace", "risk.polymarket.max_position_usd", "30.00"),
            ConfigPatchOperation("replace", "risk.polymarket.market_order_slippage_threshold", "0.03"),
            ConfigPatchOperation("replace", "notifications.cooldown_seconds", 900),
        ],
    )
    payload = result.mutation.config_version["payload"]

    assert payload["venues"]["polymarket_us"]["enabled"] is True
    assert payload["trading_loop_interval_seconds"] == 60
    assert payload["strategies"]["arbitrage"]["enabled"] is False
    assert payload["llm"]["openai"]["budget_usd"] == "25.00"
    assert payload["risk"]["polymarket"]["max_position_usd"] == "30.00"
    assert payload["risk"]["polymarket"]["market_order_slippage_threshold"] == "0.03"
    assert payload["notifications"]["cooldown_seconds"] == 900

def test_req_ui_005_02_invalid_unauthorized_config_changes_dashboard_saves_them_changes() -> None:
    """TST-REQ-UI-005-02: Validates REQ-UI-005

    Given: invalid or unauthorized config changes
    When: the dashboard saves them
    Then: the changes are rejected and existing config remains
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    unauthorized = auth.authorize_request(auth.create_session_token(username="not-allowed"))
    service = ConfigService(auth.registry)

    with pytest.raises(ConfigAuthorizationError):
        service.save_config_patches(
            actor=ActorContext(username="not-allowed", ip_address="198.51.100.42"),
            access=unauthorized,
            environment=Environment.DEVELOPMENT,
            expected_version=None,
            version="v1",
            patches=[ConfigPatchOperation("replace", "live_enabled", True)],
        )
    with pytest.raises(ConfigValidationError):
        service.save_config_patches(
            actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
            access=auth.authorize_request(auth.create_session_token(username="yaw")),
            environment=Environment.DEVELOPMENT,
            expected_version=None,
            version="v1",
            patches=[ConfigPatchOperation("replace", "unsupported.path", True)],
        )

    assert auth.registry.state.rows("shared.config_versions") == []

def test_req_ui_006_01_authorized_dashboard_config_change_saved_user_old_value() -> None:
    """TST-REQ-UI-006-01: Validates REQ-UI-006

    Given: an authorized dashboard config change
    When: it is saved
    Then: user, old value, new value, timestamp, environment, and IP address are audited
    """
    service = AuditService()

    result = service.record_config_change_and_version(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        environment=Environment.DEVELOPMENT,
        change=ConfigChange(
            path="risk.max_position",
            old_value="25.00",
            new_value="30.00",
        ),
        version="v2",
        payload={"risk": {"max_position": "30.00"}},
    )
    audit_row = result.audit_event

    assert audit_row["actor"] == "yaw"
    assert audit_row["environment"] == Environment.DEVELOPMENT.value
    assert audit_row["metadata"]["path"] == "risk.max_position"
    assert audit_row["metadata"]["old_value"] == "25.00"
    assert audit_row["metadata"]["new_value"] == "30.00"
    assert audit_row["metadata"]["ip_address"] == "203.0.113.10"
    assert audit_row["created_at"] is not None
    assert result.config_version["version"] == "v2"
    assert result.config_version["payload"]["risk"]["max_position"] == "30.00"

def test_req_ui_006_02_audit_persistence_fails_config_change_save_attempted_config() -> None:
    """TST-REQ-UI-006-02: Validates REQ-UI-006

    Given: audit persistence fails for a config change
    When: save is attempted
    Then: the config change is not applied silently
    """
    registry = RepositoryRegistry(DatabaseState(fail_on_tables={"shared.audit_events"}))
    service = AuditService(registry)

    with pytest.raises(PersistenceUnavailableError):
        service.record_config_change_and_version(
            actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
            environment=Environment.DEVELOPMENT,
            change=ConfigChange(
                path="risk.max_position",
                old_value="25.00",
                new_value="30.00",
            ),
            version="v2",
            payload={"risk": {"max_position": "30.00"}},
        )

    assert registry.state.rows("shared.config_versions") == []

def test_req_ui_007_01_dashboard_config_saved_next_trading_loop_starts_changed() -> None:
    """TST-REQ-UI-007-01: Validates REQ-UI-007

    Given: dashboard config is saved
    When: the next trading loop starts
    Then: the changed config is applied without restart
    """
    service = ConfigService()

    save_result = service.save_config_change(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        environment=Environment.DEVELOPMENT,
        change=ConfigChange(
            path="trading_loop_seconds",
            old_value=30,
            new_value=60,
        ),
        version="v1",
        payload={"trading_loop_seconds": 60},
    )
    reload_result = service.config_for_next_loop(Environment.DEVELOPMENT)

    assert save_result.applies_on_next_loop
    assert reload_result.snapshot.version == "v1"
    assert reload_result.snapshot.payload["trading_loop_seconds"] == 60
    assert not reload_result.degraded

def test_req_ui_007_03_user_config_saved_next_user_loop_does_not_replace_shared_config() -> None:
    """TST-REQ-UI-007-03: Validates REQ-UI-007

    Given: a shared runtime config and a user-specific dashboard config
    When: config is loaded for the next loop
    Then: the user sees their config and the shared loop keeps its baseline config
    """
    registry = RepositoryRegistry()
    service = ConfigService(registry)

    service.save_config_change(
        actor=ActorContext(username="system", ip_address="127.0.0.1"),
        environment=Environment.DEVELOPMENT,
        change=ConfigChange(
            path="trading_loop_seconds",
            old_value=30,
            new_value=60,
        ),
        version="shared-v1",
        payload={"trading_loop_seconds": 60},
    )
    service.save_config_change(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        environment=Environment.DEVELOPMENT,
        change=ConfigChange(
            path="trading_loop_seconds",
            old_value=60,
            new_value=120,
        ),
        version="yaw-v1",
        payload={"trading_loop_seconds": 120},
        username="yaw",
    )

    shared_reload = service.config_for_next_loop(Environment.DEVELOPMENT)
    user_reload = service.config_for_next_loop(Environment.DEVELOPMENT, username="yaw")
    rows = registry.state.rows("shared.config_versions")

    assert shared_reload.snapshot.version == "shared-v1"
    assert shared_reload.snapshot.payload["trading_loop_seconds"] == 60
    assert user_reload.snapshot.version == "yaw-v1"
    assert user_reload.snapshot.payload["trading_loop_seconds"] == 120
    assert {row["username"] for row in rows} == {"__shared__", "yaw"}
    assert all(row["active"] for row in rows)

def test_req_ui_007_04_first_user_config_save_preserves_safe_runtime_defaults() -> None:
    """TST-REQ-UI-007-04: Validates REQ-UI-007 and REQ-EXE-001

    Given: a user has no prior saved config row
    When: the dashboard saves a settings patch
    Then: runtime defaults are preserved while live trading remains explicitly gated
    """
    registry = RepositoryRegistry()
    runtime_defaults = default_config_payload()
    runtime_defaults["live_enabled"] = True
    runtime_defaults["venues"][Venue.POLYMARKET_US.value]["enabled"] = True
    runtime_defaults["alpaca"]["account_mode"] = "live"
    auth = AuthService(
        allowed_usernames={"yaw"},
        signing_secret="test-secret",
        registry=registry,
    )
    service = ConfigService(registry, default_payload_factory=lambda: runtime_defaults)
    access = auth.authorize_request(
        auth.create_session_token(username="yaw"),
        environment=Environment.PRODUCTION,
    )

    service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=access,
        environment=Environment.PRODUCTION,
        expected_version=None,
        version="v1",
        patches=[
            ConfigPatchOperation(
                "replace",
                "reasoning.polymarket.min_confidence",
                "0.69",
            )
        ],
        username="yaw",
    )
    snapshot = service.config_for_next_loop(Environment.PRODUCTION, username="yaw").snapshot

    assert snapshot.payload["live_enabled"] is False
    assert snapshot.payload["venues"][Venue.POLYMARKET_US.value]["enabled"] is True
    assert snapshot.payload["alpaca"]["account_mode"] == "live"
    assert snapshot.payload["reasoning"]["polymarket"]["min_confidence"] == "0.69"


def test_req_ui_007_06_unavailable_persistence_bootstrap_fails_closed() -> None:
    """TST-REQ-UI-007-06: Validates REQ-UI-007 and REQ-EXE-001

    Given: the deployed runtime is live-capable and config persistence is unavailable
    When: the first next-loop config reload falls back to bootstrap settings
    Then: live trading remains disabled until a saved config explicitly enables it
    """
    registry = RepositoryRegistry()
    runtime_defaults = default_config_payload()
    runtime_defaults["live_enabled"] = True
    service = ConfigService(registry, default_payload_factory=lambda: runtime_defaults)

    registry.state.fail_on_read_tables.add("shared.config_versions")
    result = service.config_for_next_loop(Environment.PRODUCTION, username="yaw")

    assert result.degraded
    assert result.snapshot.version == "bootstrap"
    assert result.snapshot.payload["live_enabled"] is False

def test_req_ui_007_05_multi_user_scheduler_uses_latest_database_config_owner() -> None:
    """TST-REQ-UI-007-05: Validates REQ-UI-007

    Given: multiple dashboard users are allowed and one user saved runtime config
    When: the background scheduler resolves the next-loop config owner
    Then: it loads the user-owned database config instead of shared defaults
    """
    registry = RepositoryRegistry()
    settings = AppSettings(
        allowed_usernames=("yaw", "operator"),
        signing_secret="test-secret",
        environment=Environment.PRODUCTION,
        runtime_config_username=None,
    )
    services = build_dashboard_api_services(settings, registry)

    services.config.save_config_change(
        actor=ActorContext(username="system", ip_address="127.0.0.1"),
        environment=Environment.PRODUCTION,
        change=ConfigChange(
            path="trading_loop_interval_seconds",
            old_value=30,
            new_value=60,
        ),
        version="shared-v1",
        payload={"trading_loop_interval_seconds": 60},
    )
    services.config.save_config_change(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        environment=Environment.PRODUCTION,
        change=ConfigChange(
            path="trading_loop_interval_seconds",
            old_value=60,
            new_value=90,
        ),
        version="yaw-v1",
        payload={"trading_loop_interval_seconds": 90},
        username="yaw",
    )

    owner = _scheduler_config_username(settings, services, Environment.PRODUCTION)
    reload_result = services.config.config_for_next_loop(Environment.PRODUCTION, username=owner)

    assert owner == "yaw"
    assert reload_result.snapshot.version == "yaw-v1"
    assert reload_result.snapshot.payload["trading_loop_interval_seconds"] == 90

def test_req_ui_007_02_config_reload_fails_on_next_loop_loop_starts() -> None:
    """TST-REQ-UI-007-02: Validates REQ-UI-007

    Given: config reload fails on the next loop
    When: the loop starts
    Then: prior valid config remains active and degraded status is surfaced
    """
    registry = RepositoryRegistry()
    service = ConfigService(registry)
    service.save_config_change(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        environment=Environment.DEVELOPMENT,
        change=ConfigChange(
            path="trading_loop_seconds",
            old_value=30,
            new_value=60,
        ),
        version="v1",
        payload={"trading_loop_seconds": 60},
    )
    prior = service.config_for_next_loop(Environment.DEVELOPMENT)

    registry.state.fail_on_read_tables.add("shared.config_versions")
    result = service.config_for_next_loop(Environment.DEVELOPMENT)
    health = registry.state.rows("shared.system_health")[0]

    assert result.degraded
    assert result.snapshot == prior.snapshot
    assert result.snapshot.payload["trading_loop_seconds"] == 60
    assert health["component"] == "config"
    assert health["status"] == "degraded"

def test_req_ui_008_01_authorized_user_activates_dashboard_kill_switch_request_processed() -> None:
    """TST-REQ-UI-008-01: Validates REQ-UI-008

    Given: an authorized user activates the dashboard kill switch
    When: the request is processed
    Then: the global kill switch state is set
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    token = auth.create_session_token(username="yaw")
    access = auth.authorize_request(token, environment=Environment.PRODUCTION)
    service = KillSwitchService(auth.registry)

    result = service.process_activation_request(
        access=access,
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        environment=Environment.PRODUCTION,
    )

    assert result.accepted
    assert result.state.active
    assert service.state(Environment.PRODUCTION).active
    assert result.audit_event is not None
    assert result.audit_event["action"] == "kill_switch.activate"

def test_req_ui_008_02_unauthorized_user_attempts_kill_switch_activation_request_processed() -> None:
    """TST-REQ-UI-008-02: Validates REQ-UI-008

    Given: an unauthorized user attempts kill switch activation
    When: the request is processed
    Then: the request is denied
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    token = auth.create_session_token(username="not-allowed-user")
    access = auth.authorize_request(
        token,
        environment=Environment.PRODUCTION,
        ip_address="198.51.100.42",
    )
    service = KillSwitchService(auth.registry)

    result = service.process_activation_request(
        access=access,
        actor=ActorContext(username="not-allowed-user", ip_address="198.51.100.42"),
        environment=Environment.PRODUCTION,
    )

    assert not result.accepted
    assert result.status_code == 403
    assert not result.state.active
    assert not service.state(Environment.PRODUCTION).active

def test_req_ui_009_01_wallet_metadata_contains_public_identifiers_private_secret_references() -> None:
    """TST-REQ-UI-009-01: Validates REQ-UI-009

    Given: wallet metadata contains public identifiers and private secret references
    When: dashboard wallet views render
    Then: only public identifiers and health are shown
    """
    payload = render_wallet_dashboard_status(
        CredentialStatus(
            credential_type="wallet",
            secret_ref="/codex-poly-bot/development/polymarket_us/openai/wallet",
            present=True,
            public_identifier="pm-dev-openai",
            secret_value="private-key-value",
        )
    )

    assert payload["public_identifier"] == "pm-dev-openai"
    assert payload["present"] is True
    assert "secret_value" not in payload
    assert "private-key-value" not in str(payload)

def test_req_ui_010_01_claude_openai_records_exist_dashboard_model_views_render() -> None:
    """TST-REQ-UI-010-01: Validates REQ-UI-010

    Given: Claude and OpenAI records exist
    When: dashboard model views render
    Then: positions, decisions, budgets, and P&L are separated by provider
    """
    summary = build_model_provider_summary(
        records=(
            {"model_provider": ModelProvider.CLAUDE, "position_id": "c-pos", "pnl": Decimal("7")},
            {"model_provider": ModelProvider.OPENAI, "position_id": "o-pos", "pnl": Decimal("3")},
        ),
        budgets={
            ModelProvider.CLAUDE: Decimal("20"),
            ModelProvider.OPENAI: Decimal("30"),
        },
        provider=ModelProvider.CLAUDE,
    )

    assert summary.model_provider == ModelProvider.CLAUDE
    assert summary.positions == ("c-pos",)
    assert summary.budget_usd == Decimal("20")
    assert summary.pnl == Decimal("7")

def test_req_ui_011_01_comparison_metrics_exist_polymarket_alpaca_dashboard_comparison_views() -> None:
    """TST-REQ-UI-011-01: Validates REQ-UI-011

    Given: comparison metrics exist for Polymarket and Alpaca
    When: dashboard comparison views render
    Then: P&L, win rate, drawdown, cost, exposure, trade count, and return-to-risk are shown
    """
    view = build_comparison_dashboard_view(
        (
            PerformanceRecord(
                group=ComparisonGroup(
                    ModelProvider.OPENAI,
                    Venue.POLYMARKET_US,
                    Environment.DEVELOPMENT,
                    InstrumentType.PREDICTION_MARKET,
                ),
                realized_pnl=Decimal("20"),
                unrealized_pnl=Decimal("5"),
                model_cost=Decimal("2"),
                open_exposure=Decimal("40"),
                wins=3,
                losses=1,
                max_drawdown=Decimal("-5"),
            ),
        )
    )

    metric_names = {metric.metric_name for metric in view.metrics}

    assert {
        "realized_pnl",
        "unrealized_pnl",
        "win_rate",
        "max_drawdown",
        "model_cost",
        "open_exposure",
        "trade_count",
        "return_to_risk",
    }.issubset(metric_names)
    assert view.degraded_sections == ()

def test_req_ui_011_02_one_model_venue_insufficient_comparison_data_comparison_views() -> None:
    """TST-REQ-UI-011-02: Validates REQ-UI-011

    Given: one model or venue has insufficient comparison data
    When: comparison views render
    Then: unavailable metrics are labeled without showing misleading zero values
    """
    view = build_comparison_dashboard_view(
        (),
        expected_groups=(
            ComparisonGroup(
                ModelProvider.CLAUDE,
                Venue.ALPACA,
                Environment.DEVELOPMENT,
                InstrumentType.ETF,
            ),
        ),
    )
    metric = view.metrics[0]

    assert metric.value is None
    assert metric.unavailable_reason == "no eligible data"
    assert "comparison" in view.degraded_sections


def test_req_ui_012_01_scanner_blockers_show_targeted_config_recommendation() -> None:
    """TST-REQ-UI-012-01: Validates REQ-UI-012

    Given: recent scanner rejections point to configurable thresholds
    When: dashboard control checks run
    Then: the dashboard exposes a targeted recommendation that can save through the audited config flow
    """
    component = (PROJECT_ROOT / "frontend/components/dashboard/consumer-dashboard.tsx").read_text()
    static_check = (PROJECT_ROOT / "frontend/scripts/check-dashboard-controls.mjs").read_text()

    assert "tradeUnblockRecommendation" in component
    assert "Allow more candidates" in component
    assert "Candidate settings saved" in component
    assert "saveConfigPatches" in component
    assert "model, risk, credential, or market-hours gates" in component
    assert "Allow more candidates" in static_check
