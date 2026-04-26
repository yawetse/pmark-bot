"""Red-phase tests for Venue Integration."""

from __future__ import annotations

from tests.spec.helpers import pending


def test_req_ven_001_01_supported_venue_configs_polymarket_us_international_venue_adapters() -> None:
    """TST-REQ-VEN-001-01: Validates REQ-VEN-001

    Given: supported venue configs for Polymarket US and International
    When: venue adapters are registered
    Then: both venues are available as configurable trading venues
    """
    pending("TST-REQ-VEN-001-01", "REQ-VEN-001")

def test_req_ven_001_02_unknown_polymarket_venue_key_venue_adapters_resolved_system() -> None:
    """TST-REQ-VEN-001-02: Validates REQ-VEN-001

    Given: an unknown Polymarket venue key
    When: venue adapters are resolved
    Then: the system rejects the venue and records a configuration error
    """
    pending("TST-REQ-VEN-001-02", "REQ-VEN-001")

def test_req_ven_002_01_no_explicit_venue_setting_app_loads_runtime_config() -> None:
    """TST-REQ-VEN-002-01: Validates REQ-VEN-002

    Given: no explicit venue setting
    When: the app loads runtime config
    Then: `polymarket_us` is selected as the default venue
    """
    pending("TST-REQ-VEN-002-01", "REQ-VEN-002")

def test_req_ven_002_02_explicit_supported_venue_setting_app_loads_runtime_config() -> None:
    """TST-REQ-VEN-002-02: Validates REQ-VEN-002

    Given: an explicit supported venue setting
    When: the app loads runtime config
    Then: the explicit setting is used instead of the default
    """
    pending("TST-REQ-VEN-002-02", "REQ-VEN-002")

def test_req_ven_003_01_venue_enabled_false_scan_score_trade_requested_system() -> None:
    """TST-REQ-VEN-003-01: Validates REQ-VEN-003

    Given: a venue with `enabled=false`
    When: scan, score, or trade is requested
    Then: the system refuses the operation before external calls
    """
    pending("TST-REQ-VEN-003-01", "REQ-VEN-003")

def test_req_ven_003_02_venue_toggled_enabled_disabled_next_loop_starts_no() -> None:
    """TST-REQ-VEN-003-02: Validates REQ-VEN-003

    Given: a venue is toggled from enabled to disabled
    When: the next loop starts
    Then: no stale enabled state allows scan, score, or trade
    """
    pending("TST-REQ-VEN-003-02", "REQ-VEN-003")

def test_req_ven_004_01_live_mode_approved_polymarket_order_execution_submits_order() -> None:
    """TST-REQ-VEN-004-01: Validates REQ-VEN-004

    Given: live mode and an approved Polymarket order
    When: execution submits the order
    Then: the official SDK or documented API client is used
    """
    pending("TST-REQ-VEN-004-01", "REQ-VEN-004")

def test_req_ven_004_02_non_official_polymarket_client_implementation_configured_live_order() -> None:
    """TST-REQ-VEN-004-02: Validates REQ-VEN-004

    Given: a non-official Polymarket client implementation is configured
    When: live order submission is attempted
    Then: the system blocks the submission
    """
    pending("TST-REQ-VEN-004-02", "REQ-VEN-004")

def test_req_ven_005_01_unsupported_venue_configuration_environment_live_order_checks_run() -> None:
    """TST-REQ-VEN-005-01: Validates REQ-VEN-005

    Given: an unsupported venue configuration for the environment
    When: live order checks run
    Then: live orders are blocked and the refusal reason is persisted
    """
    pending("TST-REQ-VEN-005-01", "REQ-VEN-005")

def test_req_ven_005_02_multiple_unsupported_venue_fields_validation_runs_refusal_event() -> None:
    """TST-REQ-VEN-005-02: Validates REQ-VEN-005

    Given: multiple unsupported venue fields
    When: validation runs
    Then: the refusal event includes each relevant unsupported setting
    """
    pending("TST-REQ-VEN-005-02", "REQ-VEN-005")

def test_req_ven_006_01_authorized_dashboard_update_venue_config_next_trading_loop() -> None:
    """TST-REQ-VEN-006-01: Validates REQ-VEN-006

    Given: an authorized dashboard update to venue config
    When: the next trading loop starts
    Then: the updated venue config is applied without restart
    """
    pending("TST-REQ-VEN-006-01", "REQ-VEN-006")
