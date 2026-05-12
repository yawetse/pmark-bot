"""Red-phase tests for Notifications."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.adapters.aws import EmailMessage, InMemorySesEmailAdapter
from app.domain import Environment
from app.services import (
    ActorContext,
    AlertCooldownLedger,
    AuthService,
    ConfigPatchOperation,
    ConfigService,
    DailyPnlSummary,
    DigestInputs,
    NotificationDeliveryLedger,
    NotificationSettings,
    PositionMovement,
    alert_allowed_by_cooldown,
    detect_daily_pnl_alert,
    detect_large_movement_alert,
    render_daily_digest,
    send_large_movement_alert,
    send_scheduled_daily_digest,
)


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


def test_req_not_001_03_digest_schedule_reached_sends_to_allowlisted_recipients() -> None:
    """TST-REQ-NOT-001-03: Validates REQ-NOT-001

    Given: the daily digest schedule is reached and allowlisted recipients exist
    When: the notification loop runs
    Then: SES sends the rendered digest to the configured allowlist
    """
    adapter = InMemorySesEmailAdapter()
    ledger = NotificationDeliveryLedger()

    result = send_scheduled_daily_digest(
        settings=NotificationSettings(
            recipients={"yaw": "yaw@example.com"},
            digest_schedule_utc="13:00",
        ),
        inputs=DigestInputs(
            pnl_summary="Realized 12.00",
            open_positions="2 open positions",
            new_trades="1 new trade",
            exits="0 exits",
            refused_orders="0 refused",
            budget_usage="OpenAI 1.00",
            ingestion_status="fresh",
            risk_status="within limits",
        ),
        now=datetime(2026, 5, 10, 13, 0, tzinfo=UTC),
        ses_adapter=adapter,
        delivery_ledger=ledger,
    )

    assert result.sent
    assert adapter.sent_count == 1
    assert adapter.attempts[0].recipients == ("yaw@example.com",)
    assert "P&L: Realized 12.00" in adapter.attempts[0].body
    assert ledger.records[0].notification_type == "daily_digest"


def test_req_not_002_01_digest_inputs_available_digest_rendered_includes_p_l() -> None:
    """TST-REQ-NOT-002-01: Validates REQ-NOT-002

    Given: digest inputs are available
    When: the digest is rendered
    Then: it includes P&L, open positions, trades, exits, refused orders, budget, ingestion, and risk status
    """
    digest = render_daily_digest(
        DigestInputs(
            pnl_summary="Realized 12.00, unrealized -3.00",
            open_positions="2 open positions",
            new_trades="3 new trades",
            exits="1 exit",
            refused_orders="0 refused orders",
            budget_usage="Claude 4.00, OpenAI 3.50",
            ingestion_status="fresh",
            risk_status="within limits",
        )
    )

    assert digest.unavailable_sections == ()
    assert "P&L: Realized 12.00, unrealized -3.00" in digest.body
    assert "Open positions: 2 open positions" in digest.body
    assert "Trades: 3 new trades" in digest.body
    assert "Exits: 1 exit" in digest.body
    assert "Refused orders: 0 refused orders" in digest.body
    assert "Budget: Claude 4.00, OpenAI 3.50" in digest.body
    assert "Ingestion: fresh" in digest.body
    assert "Risk: within limits" in digest.body

def test_req_not_002_02_one_digest_input_source_unavailable_digest_rendered_missing() -> None:
    """TST-REQ-NOT-002-02: Validates REQ-NOT-002

    Given: one digest input source is unavailable
    When: the digest is rendered
    Then: the missing section is marked unavailable and delivery can still proceed if policy allows
    """
    digest = render_daily_digest(
        DigestInputs(
            pnl_summary="Realized 0.00, unrealized 0.00",
            open_positions="0 open positions",
            new_trades="0 new trades",
            exits="0 exits",
            refused_orders="0 refused orders",
            budget_usage=None,
            ingestion_status="fresh",
            risk_status=None,
        )
    )

    assert digest.unavailable_sections == ("budget", "risk")
    assert "Budget: unavailable" in digest.body
    assert "Risk: unavailable" in digest.body
    assert digest.delivery_allowed

def test_req_not_003_01_position_p_l_change_reaches_25_usd_10() -> None:
    """TST-REQ-NOT-003-01: Validates REQ-NOT-003

    Given: a position P&L change reaches 25 USD or 10 percent by default
    When: movement detection runs
    Then: SES sends a large-movement alert
    """
    alert = detect_large_movement_alert(
        PositionMovement(position_id="pos-1", change_usd=Decimal("25.00"), change_pct=Decimal("0.05"))
    )

    assert alert.should_send
    assert alert.alert_type == "large_position_movement"
    assert "25.00" in alert.body

def test_req_not_003_02_position_p_l_change_below_both_default_thresholds() -> None:
    """TST-REQ-NOT-003-02: Validates REQ-NOT-003

    Given: a position P&L change is below both default thresholds
    When: movement detection runs
    Then: no large-movement alert is sent
    """
    alert = detect_large_movement_alert(
        PositionMovement(position_id="pos-1", change_usd=Decimal("24.99"), change_pct=Decimal("0.099"))
    )

    assert not alert.should_send
    assert alert.skipped_reason == "movement below threshold"


def test_req_not_003_03_large_movement_alert_sends_subject_to_cooldown() -> None:
    """TST-REQ-NOT-003-03: Validates REQ-NOT-003

    Given: position P&L crosses the alert threshold and no cooldown is active
    When: alert delivery runs
    Then: SES sends the alert and records cooldown for the alert key
    """
    adapter = InMemorySesEmailAdapter()
    cooldown = AlertCooldownLedger()
    delivery_ledger = NotificationDeliveryLedger()
    now = datetime(2026, 5, 10, 14, 0, tzinfo=UTC)

    result = send_large_movement_alert(
        settings=NotificationSettings(recipients={"yaw": "yaw@example.com"}),
        movement=PositionMovement(
            position_id="pos-1",
            change_usd=Decimal("26.00"),
            change_pct=Decimal("0.05"),
        ),
        alert_key="market-1:openai:large_position_movement",
        now=now,
        ses_adapter=adapter,
        cooldown_ledger=cooldown,
        delivery_ledger=delivery_ledger,
    )

    assert result.sent
    assert adapter.sent_count == 1
    assert cooldown.sent_at["market-1:openai:large_position_movement"] == now
    assert delivery_ledger.records[0].notification_type == "large_position_movement"


def test_req_not_004_01_daily_realized_unrealized_p_l_crosses_configured_threshold() -> None:
    """TST-REQ-NOT-004-01: Validates REQ-NOT-004

    Given: daily realized or unrealized P&L crosses a configured threshold
    When: notification checks run
    Then: SES sends an alert
    """
    alert = detect_daily_pnl_alert(
        DailyPnlSummary(realized_pnl=Decimal("-10.00"), unrealized_pnl=Decimal("-25.00")),
        threshold_usd=Decimal("25.00"),
    )

    assert alert.should_send
    assert alert.alert_type == "daily_pnl_threshold"
    assert "unrealized -25.00" in alert.body

def test_req_not_004_02_daily_p_l_remains_within_thresholds_notification_checks() -> None:
    """TST-REQ-NOT-004-02: Validates REQ-NOT-004

    Given: daily P&L remains within thresholds
    When: notification checks run
    Then: no threshold alert is sent
    """
    alert = detect_daily_pnl_alert(
        DailyPnlSummary(realized_pnl=Decimal("-10.00"), unrealized_pnl=Decimal("-24.99")),
        threshold_usd=Decimal("25.00"),
    )

    assert not alert.should_send
    assert alert.skipped_reason == "daily pnl within thresholds"

def test_req_not_005_01_default_notification_config_alert_was_sent_less_than() -> None:
    """TST-REQ-NOT-005-01: Validates REQ-NOT-005

    Given: default notification config
    When: an alert was sent less than 30 minutes ago for the same market and provider
    Then: another alert is suppressed
    """
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    ledger = AlertCooldownLedger()
    ledger.record_sent("market-1:openai:large_position_movement", now - timedelta(minutes=10))

    result = alert_allowed_by_cooldown(
        ledger,
        "market-1:openai:large_position_movement",
        now,
    )

    assert not result.allowed
    assert result.skipped_reason == "alert cooldown active"

def test_req_not_005_02_30_minute_cooldown_elapsed_alert_condition_still_holds() -> None:
    """TST-REQ-NOT-005-02: Validates REQ-NOT-005

    Given: the 30-minute cooldown has elapsed
    When: the alert condition still holds
    Then: a new alert is allowed
    """
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    ledger = AlertCooldownLedger()
    ledger.record_sent("market-1:openai:large_position_movement", now - timedelta(minutes=31))

    result = alert_allowed_by_cooldown(
        ledger,
        "market-1:openai:large_position_movement",
        now,
    )

    assert result.allowed
    assert result.next_allowed_at is None

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


def test_req_not_006_02_notification_settings_change_applies_on_next_loop() -> None:
    """TST-REQ-NOT-006-02: Validates REQ-NOT-006

    Given: notification settings change in the dashboard
    When: the next notification loop reads config
    Then: recipients, thresholds, schedule, and cooldown use the updated values
    """
    auth = AuthService(allowed_usernames={"yaw"}, signing_secret="test-secret")
    service = ConfigService(auth.registry)
    service.save_config_patches(
        actor=ActorContext(username="yaw", ip_address="203.0.113.10"),
        access=auth.authorize_request(auth.create_session_token(username="yaw")),
        environment=Environment.DEVELOPMENT,
        expected_version=None,
        version="v1",
        patches=[
            ConfigPatchOperation("replace", "notifications.recipients", {"yaw": "yaw@example.com"}),
            ConfigPatchOperation("replace", "notifications.thresholds.position_usd", "30.00"),
            ConfigPatchOperation("replace", "notifications.digest_schedule_utc", "15:15"),
            ConfigPatchOperation("replace", "notifications.cooldown_seconds", 600),
        ],
    )

    payload = service.config_for_next_loop(Environment.DEVELOPMENT).snapshot.payload["notifications"]
    settings = NotificationSettings.from_config(payload)

    assert settings.recipients == {"yaw": "yaw@example.com"}
    assert settings.thresholds["position_usd"] == Decimal("30.00")
    assert settings.digest_schedule_utc == "15:15"
    assert settings.cooldown_seconds == 600


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


def test_req_not_007_02_ses_failure_recorded_with_retry_timing() -> None:
    """TST-REQ-NOT-007-02: Validates REQ-NOT-007

    Given: SES delivery fails
    When: notification delivery handles the result
    Then: the failure is recorded and next retry timing follows policy
    """
    adapter = InMemorySesEmailAdapter(fail_delivery=True)
    ledger = NotificationDeliveryLedger()
    now = datetime(2026, 5, 10, 13, 0, tzinfo=UTC)

    result = send_scheduled_daily_digest(
        settings=NotificationSettings(
            recipients={"yaw": "yaw@example.com"},
            digest_schedule_utc="13:00",
            retry_delay_seconds=300,
        ),
        inputs=DigestInputs(
            pnl_summary="Realized 0.00",
            open_positions="0 open positions",
            new_trades="0 trades",
            exits="0 exits",
            refused_orders="0 refused",
            budget_usage="OpenAI 0.00",
            ingestion_status="fresh",
            risk_status="within limits",
        ),
        now=now,
        ses_adapter=adapter,
        delivery_ledger=ledger,
    )

    assert not result.sent
    assert result.retryable
    assert result.next_retry_at == now + timedelta(seconds=300)
    assert ledger.records[0].error_summary == "SES delivery failed"
    assert ledger.records[0].next_retry_at == now + timedelta(seconds=300)
