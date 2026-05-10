"""Red-phase tests for Notifications."""

from __future__ import annotations

from app.adapters.aws import EmailMessage, InMemorySesEmailAdapter
from app.domain import Environment
from app.services import ActorContext, AuthService, ConfigPatchOperation, ConfigService
from tests.spec.helpers import pending


def test_req_not_001_01_daily_digest_schedule_fires_allowlisted_users_exist_notifications() -> None:
    """TST-REQ-NOT-001-01: Validates REQ-NOT-001

    Given: the daily digest schedule fires and allowlisted users exist
    When: notifications run
    Then: SES sends digest email to allowlisted users
    """
    adapter = InMemorySesEmailAdapter()

    result = adapter.send_digest(
        EmailMessage(
            recipients=("yaw@example.com",),
            subject="Daily digest",
            body="P&L: 0.00",
        )
    )

    assert result.sent
    assert result.message_id == "ses-message-1"
    assert adapter.sent_count == 1

def test_req_not_001_02_no_allowlisted_recipients_exist_digest_notifications_run_no() -> None:
    """TST-REQ-NOT-001-02: Validates REQ-NOT-001

    Given: no allowlisted recipients exist
    When: digest notifications run
    Then: no email is sent and the skipped reason is recorded
    """
    adapter = InMemorySesEmailAdapter()

    result = adapter.send_digest(
        EmailMessage(
            recipients=(),
            subject="Daily digest",
            body="P&L: 0.00",
        )
    )

    assert not result.sent
    assert result.skipped_reason == "no recipients"
    assert adapter.sent_count == 0

def test_req_not_002_01_digest_inputs_available_digest_rendered_includes_p_l() -> None:
    """TST-REQ-NOT-002-01: Validates REQ-NOT-002

    Given: digest inputs are available
    When: the digest is rendered
    Then: it includes P&L, open positions, trades, exits, refused orders, budget, ingestion, and risk status
    """
    pending("TST-REQ-NOT-002-01", "REQ-NOT-002")

def test_req_not_002_02_one_digest_input_source_unavailable_digest_rendered_missing() -> None:
    """TST-REQ-NOT-002-02: Validates REQ-NOT-002

    Given: one digest input source is unavailable
    When: the digest is rendered
    Then: the missing section is marked unavailable and delivery can still proceed if policy allows
    """
    pending("TST-REQ-NOT-002-02", "REQ-NOT-002")

def test_req_not_003_01_position_p_l_change_reaches_25_usd_10() -> None:
    """TST-REQ-NOT-003-01: Validates REQ-NOT-003

    Given: a position P&L change reaches 25 USD or 10 percent by default
    When: movement detection runs
    Then: SES sends a large-movement alert
    """
    pending("TST-REQ-NOT-003-01", "REQ-NOT-003")

def test_req_not_003_02_position_p_l_change_below_both_default_thresholds() -> None:
    """TST-REQ-NOT-003-02: Validates REQ-NOT-003

    Given: a position P&L change is below both default thresholds
    When: movement detection runs
    Then: no large-movement alert is sent
    """
    pending("TST-REQ-NOT-003-02", "REQ-NOT-003")

def test_req_not_004_01_daily_realized_unrealized_p_l_crosses_configured_threshold() -> None:
    """TST-REQ-NOT-004-01: Validates REQ-NOT-004

    Given: daily realized or unrealized P&L crosses a configured threshold
    When: notification checks run
    Then: SES sends an alert
    """
    pending("TST-REQ-NOT-004-01", "REQ-NOT-004")

def test_req_not_004_02_daily_p_l_remains_within_thresholds_notification_checks() -> None:
    """TST-REQ-NOT-004-02: Validates REQ-NOT-004

    Given: daily P&L remains within thresholds
    When: notification checks run
    Then: no threshold alert is sent
    """
    pending("TST-REQ-NOT-004-02", "REQ-NOT-004")

def test_req_not_005_01_default_notification_config_alert_was_sent_less_than() -> None:
    """TST-REQ-NOT-005-01: Validates REQ-NOT-005

    Given: default notification config
    When: an alert was sent less than 30 minutes ago for the same market and provider
    Then: another alert is suppressed
    """
    pending("TST-REQ-NOT-005-01", "REQ-NOT-005")

def test_req_not_005_02_30_minute_cooldown_elapsed_alert_condition_still_holds() -> None:
    """TST-REQ-NOT-005-02: Validates REQ-NOT-005

    Given: the 30-minute cooldown has elapsed
    When: the alert condition still holds
    Then: a new alert is allowed
    """
    pending("TST-REQ-NOT-005-02", "REQ-NOT-005")

def test_req_not_006_01_authorized_dashboard_user_changes_recipients_thresholds_schedules_cooldowns() -> None:
    """TST-REQ-NOT-006-01: Validates REQ-NOT-006

    Given: an authorized dashboard user changes recipients, thresholds, schedules, or cooldowns
    When: notification config is saved
    Then: the updated settings persist
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)
    result = service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=auth.authorize_request(auth.create_session_token(username="yaw")),
        environment=Environment.DEVELOPMENT,
        expected_version=None,
        version="v1",
        patches=[
            ConfigPatchOperation("replace", "notifications.recipients", {"yaw": "yaw@example.com"}),
            ConfigPatchOperation("replace", "notifications.thresholds.drawdown_usd", "25.00"),
            ConfigPatchOperation("replace", "notifications.digest_schedule_utc", "14:30"),
            ConfigPatchOperation("replace", "notifications.cooldown_seconds", 1200),
        ],
    )
    payload = result.mutation.config_version["payload"]["notifications"]

    assert payload["recipients"] == {"yaw": "yaw@example.com"}
    assert payload["thresholds"]["drawdown_usd"] == "25.00"
    assert payload["digest_schedule_utc"] == "14:30"
    assert payload["cooldown_seconds"] == 1200

def test_req_not_007_01_ses_delivery_fails_retry_policy_runs_failure_recorded() -> None:
    """TST-REQ-NOT-007-01: Validates REQ-NOT-007

    Given: SES delivery fails
    When: retry policy runs
    Then: the failure is recorded and retry timing follows config
    """
    adapter = InMemorySesEmailAdapter(fail_delivery=True)

    result = adapter.send_email(
        EmailMessage(
            recipients=("yaw@example.com",),
            subject="Risk alert",
            body="Daily P&L crossed threshold.",
        )
    )

    assert not result.sent
    assert result.retryable
    assert result.attempt_recorded
    assert result.error_summary == "SES delivery failed"
