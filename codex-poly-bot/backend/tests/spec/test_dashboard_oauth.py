"""Red-phase tests for Dashboard and GitHub OAuth."""

from __future__ import annotations

from tests.spec.helpers import pending


def test_req_ui_001_01_backend_frontend_services_running_dashboard_loads_next_js() -> None:
    """TST-REQ-UI-001-01: Validates REQ-UI-001

    Given: backend and frontend services are running
    When: the dashboard loads
    Then: the Next.js UI retrieves data from FastAPI services
    """
    pending("TST-REQ-UI-001-01", "REQ-UI-001")

def test_req_ui_001_02_fastapi_unavailable_dashboard_loads_status_views_ui_shows() -> None:
    """TST-REQ-UI-001-02: Validates REQ-UI-001

    Given: FastAPI is unavailable
    When: the dashboard loads status views
    Then: the UI shows degraded API state without exposing internals
    """
    pending("TST-REQ-UI-001-02", "REQ-UI-001")

def test_req_ui_002_01_unauthenticated_user_dashboard_opened_github_oauth_login_required() -> None:
    """TST-REQ-UI-002-01: Validates REQ-UI-002

    Given: an unauthenticated user
    When: the dashboard is opened
    Then: GitHub OAuth login is required
    """
    pending("TST-REQ-UI-002-01", "REQ-UI-002")

def test_req_ui_002_02_invalid_oauth_callback_state_value_login_completes_access() -> None:
    """TST-REQ-UI-002-02: Validates REQ-UI-002

    Given: an invalid OAuth callback or state value
    When: login completes
    Then: access is denied and the event is logged
    """
    pending("TST-REQ-UI-002-02", "REQ-UI-002")

def test_req_ui_003_01_authenticated_github_username_on_allowlist_dashboard_access_checked() -> None:
    """TST-REQ-UI-003-01: Validates REQ-UI-003

    Given: an authenticated GitHub username on the allowlist
    When: dashboard access is checked
    Then: access is granted
    """
    pending("TST-REQ-UI-003-01", "REQ-UI-003")

def test_req_ui_003_02_authenticated_github_username_not_on_allowlist_dashboard_access() -> None:
    """TST-REQ-UI-003-02: Validates REQ-UI-003

    Given: an authenticated GitHub username not on the allowlist
    When: dashboard access is checked
    Then: access is denied
    """
    pending("TST-REQ-UI-003-02", "REQ-UI-003")

def test_req_ui_004_01_authorized_user_status_pages_load_venue_model_wallet() -> None:
    """TST-REQ-UI-004-01: Validates REQ-UI-004

    Given: an authorized user
    When: status pages load
    Then: venue, model, wallet, ingestion, loop, position, order, and notification status are visible
    """
    pending("TST-REQ-UI-004-01", "REQ-UI-004")

def test_req_ui_004_02_status_source_unavailable_status_pages_load_dashboard_marks() -> None:
    """TST-REQ-UI-004-02: Validates REQ-UI-004

    Given: a status source is unavailable
    When: status pages load
    Then: the dashboard marks that source degraded rather than showing stale success
    """
    pending("TST-REQ-UI-004-02", "REQ-UI-004")

def test_req_ui_005_01_authorized_user_changes_supported_config_fields_dashboard_saves() -> None:
    """TST-REQ-UI-005-01: Validates REQ-UI-005

    Given: an authorized user changes supported config fields
    When: the dashboard saves them
    Then: venue flags, dry-run/live, loop, strategy, budget, risk, slippage, and notification settings persist
    """
    pending("TST-REQ-UI-005-01", "REQ-UI-005")

def test_req_ui_005_02_invalid_unauthorized_config_changes_dashboard_saves_them_changes() -> None:
    """TST-REQ-UI-005-02: Validates REQ-UI-005

    Given: invalid or unauthorized config changes
    When: the dashboard saves them
    Then: the changes are rejected and existing config remains
    """
    pending("TST-REQ-UI-005-02", "REQ-UI-005")

def test_req_ui_006_01_authorized_dashboard_config_change_saved_user_old_value() -> None:
    """TST-REQ-UI-006-01: Validates REQ-UI-006

    Given: an authorized dashboard config change
    When: it is saved
    Then: user, old value, new value, timestamp, environment, and IP address are audited
    """
    pending("TST-REQ-UI-006-01", "REQ-UI-006")

def test_req_ui_006_02_audit_persistence_fails_config_change_save_attempted_config() -> None:
    """TST-REQ-UI-006-02: Validates REQ-UI-006

    Given: audit persistence fails for a config change
    When: save is attempted
    Then: the config change is not applied silently
    """
    pending("TST-REQ-UI-006-02", "REQ-UI-006")

def test_req_ui_007_01_dashboard_config_saved_next_trading_loop_starts_changed() -> None:
    """TST-REQ-UI-007-01: Validates REQ-UI-007

    Given: dashboard config is saved
    When: the next trading loop starts
    Then: the changed config is applied without restart
    """
    pending("TST-REQ-UI-007-01", "REQ-UI-007")

def test_req_ui_007_02_config_reload_fails_on_next_loop_loop_starts() -> None:
    """TST-REQ-UI-007-02: Validates REQ-UI-007

    Given: config reload fails on the next loop
    When: the loop starts
    Then: prior valid config remains active and degraded status is surfaced
    """
    pending("TST-REQ-UI-007-02", "REQ-UI-007")

def test_req_ui_008_01_authorized_user_activates_dashboard_kill_switch_request_processed() -> None:
    """TST-REQ-UI-008-01: Validates REQ-UI-008

    Given: an authorized user activates the dashboard kill switch
    When: the request is processed
    Then: the global kill switch state is set
    """
    pending("TST-REQ-UI-008-01", "REQ-UI-008")

def test_req_ui_008_02_unauthorized_user_attempts_kill_switch_activation_request_processed() -> None:
    """TST-REQ-UI-008-02: Validates REQ-UI-008

    Given: an unauthorized user attempts kill switch activation
    When: the request is processed
    Then: the request is denied
    """
    pending("TST-REQ-UI-008-02", "REQ-UI-008")

def test_req_ui_009_01_wallet_metadata_contains_public_identifiers_private_secret_references() -> None:
    """TST-REQ-UI-009-01: Validates REQ-UI-009

    Given: wallet metadata contains public identifiers and private secret references
    When: dashboard wallet views render
    Then: only public identifiers and health are shown
    """
    pending("TST-REQ-UI-009-01", "REQ-UI-009")

def test_req_ui_010_01_claude_openai_records_exist_dashboard_model_views_render() -> None:
    """TST-REQ-UI-010-01: Validates REQ-UI-010

    Given: Claude and OpenAI records exist
    When: dashboard model views render
    Then: positions, decisions, budgets, and P&L are separated by provider
    """
    pending("TST-REQ-UI-010-01", "REQ-UI-010")

def test_req_ui_011_01_comparison_metrics_exist_polymarket_alpaca_dashboard_comparison_views() -> None:
    """TST-REQ-UI-011-01: Validates REQ-UI-011

    Given: comparison metrics exist for Polymarket and Alpaca
    When: dashboard comparison views render
    Then: P&L, win rate, drawdown, cost, exposure, trade count, and return-to-risk are shown
    """
    pending("TST-REQ-UI-011-01", "REQ-UI-011")

def test_req_ui_011_02_one_model_venue_insufficient_comparison_data_comparison_views() -> None:
    """TST-REQ-UI-011-02: Validates REQ-UI-011

    Given: one model or venue has insufficient comparison data
    When: comparison views render
    Then: unavailable metrics are labeled without showing misleading zero values
    """
    pending("TST-REQ-UI-011-02", "REQ-UI-011")
