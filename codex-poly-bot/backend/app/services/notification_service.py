"""Notification rendering, alert, and cooldown helpers.

REQ: REQ-NOT-001, REQ-NOT-002, REQ-NOT-003, REQ-NOT-004,
REQ-NOT-005, REQ-NOT-006, REQ-NOT-007, REQ-OBS-001
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.adapters.aws import EmailDeliveryResult, EmailMessage, InMemorySesEmailAdapter


@dataclass(frozen=True)
class DigestInputs:
    """Inputs required for the daily notification digest.

    REQ: REQ-NOT-002
    """

    pnl_summary: str | None
    open_positions: str | None
    new_trades: str | None
    exits: str | None
    refused_orders: str | None
    budget_usage: str | None
    ingestion_status: str | None
    risk_status: str | None


@dataclass(frozen=True)
class RenderedDigest:
    """Rendered daily digest body and unavailable sections.

    REQ: REQ-NOT-002
    """

    body: str
    unavailable_sections: tuple[str, ...] = ()
    delivery_allowed: bool = True


@dataclass(frozen=True)
class NotificationSettings:
    """Runtime notification settings for the next notification loop.

    REQ: REQ-NOT-001, REQ-NOT-003, REQ-NOT-004, REQ-NOT-005,
    REQ-NOT-006, REQ-NOT-007
    """

    recipients: dict[str, str]
    thresholds: dict[str, Decimal] = field(default_factory=dict)
    digest_schedule_utc: str = "13:00"
    cooldown_seconds: int = 1800
    retry_delay_seconds: int = 300

    @classmethod
    def from_config(cls, payload: dict[str, Any]) -> NotificationSettings:
        """Build notification loop settings from persisted config.

        REQ: REQ-NOT-006
        """

        thresholds = {
            key: _as_decimal(value)
            for key, value in payload.get("thresholds", {}).items()
        }
        return cls(
            recipients=dict(payload.get("recipients", {})),
            thresholds=thresholds,
            digest_schedule_utc=str(payload.get("digest_schedule_utc", "13:00")),
            cooldown_seconds=int(payload.get("cooldown_seconds", 1800)),
            retry_delay_seconds=int(payload.get("retry_delay_seconds", 300)),
        )

    @property
    def recipient_emails(self) -> tuple[str, ...]:
        return tuple(email for email in self.recipients.values() if str(email).strip())


@dataclass(frozen=True)
class NotificationSendResult:
    """Notification delivery result emitted by notification loop helpers.

    REQ: REQ-NOT-001, REQ-NOT-003, REQ-NOT-004, REQ-NOT-007
    """

    sent: bool
    notification_type: str
    message_id: str | None = None
    skipped_reason: str | None = None
    retryable: bool = False
    next_retry_at: datetime | None = None
    error_summary: str | None = None


@dataclass(frozen=True)
class NotificationDeliveryRecord:
    """Recorded notification delivery attempt.

    REQ: REQ-NOT-007, REQ-OBS-001
    """

    notification_type: str
    recipients: tuple[str, ...]
    subject: str
    attempted_at: datetime
    sent: bool
    message_id: str | None = None
    skipped_reason: str | None = None
    retryable: bool = False
    next_retry_at: datetime | None = None
    error_summary: str | None = None


@dataclass
class NotificationDeliveryLedger:
    """In-memory notification delivery ledger used by tests and dry-run mode.

    REQ: REQ-NOT-007, REQ-OBS-001
    """

    records: list[NotificationDeliveryRecord] = field(default_factory=list)

    def record(self, record: NotificationDeliveryRecord) -> None:
        """Record one notification delivery result.

        REQ: REQ-NOT-007
        """

        self.records.append(record)


@dataclass(frozen=True)
class PositionMovement:
    """Position P&L movement input for alert checks.

    REQ: REQ-NOT-003
    """

    position_id: str
    change_usd: Decimal
    change_pct: Decimal


@dataclass(frozen=True)
class DailyPnlSummary:
    """Daily realized and unrealized P&L input for alert checks.

    REQ: REQ-NOT-004
    """

    realized_pnl: Decimal
    unrealized_pnl: Decimal


@dataclass(frozen=True)
class NotificationAlertDecision:
    """Alert send or skip decision.

    REQ: REQ-NOT-003, REQ-NOT-004
    """

    should_send: bool
    alert_type: str
    subject: str = ""
    body: str = ""
    skipped_reason: str | None = None


@dataclass(frozen=True)
class AlertCooldownResult:
    """Cooldown gate result for one alert key.

    REQ: REQ-NOT-005
    """

    allowed: bool
    next_allowed_at: datetime | None = None
    skipped_reason: str | None = None


@dataclass
class AlertCooldownLedger:
    """In-memory last-sent index by alert key.

    REQ: REQ-NOT-005
    """

    sent_at: dict[str, datetime] = field(default_factory=dict)

    def record_sent(self, alert_key: str, sent_at: datetime) -> None:
        """Record a successful alert send timestamp.

        REQ: REQ-NOT-005
        """

        self.sent_at[alert_key] = sent_at


def render_daily_digest(inputs: DigestInputs) -> RenderedDigest:
    """Render a digest with unavailable sections marked explicitly.

    REQ: REQ-NOT-002
    """

    sections = (
        ("pnl", "P&L", inputs.pnl_summary),
        ("open_positions", "Open positions", inputs.open_positions),
        ("trades", "Trades", inputs.new_trades),
        ("exits", "Exits", inputs.exits),
        ("refused_orders", "Refused orders", inputs.refused_orders),
        ("budget", "Budget", inputs.budget_usage),
        ("ingestion", "Ingestion", inputs.ingestion_status),
        ("risk", "Risk", inputs.risk_status),
    )
    unavailable: list[str] = []
    lines: list[str] = []
    for key, label, value in sections:
        if value is None:
            unavailable.append(key)
            lines.append(f"{label}: unavailable")
            continue
        lines.append(f"{label}: {value}")
    return RenderedDigest(
        body="\n".join(lines),
        unavailable_sections=tuple(unavailable),
        delivery_allowed=True,
    )


def send_scheduled_daily_digest(
    *,
    settings: NotificationSettings,
    inputs: DigestInputs,
    now: datetime,
    ses_adapter: InMemorySesEmailAdapter,
    delivery_ledger: NotificationDeliveryLedger,
    last_sent_at: datetime | None = None,
) -> NotificationSendResult:
    """Send the daily digest when the configured UTC schedule is reached.

    REQ: REQ-NOT-001, REQ-NOT-002, REQ-NOT-006, REQ-NOT-007
    """

    if not _digest_schedule_due(now, settings.digest_schedule_utc, last_sent_at):
        return _record_notification_result(
            delivery_ledger=delivery_ledger,
            delivery=EmailDeliveryResult(sent=False, attempt_recorded=False, skipped_reason="schedule not reached"),
            message=EmailMessage(recipients=settings.recipient_emails, subject="Daily digest", body=""),
            notification_type="daily_digest",
            now=now,
            retry_delay_seconds=settings.retry_delay_seconds,
        )
    digest = render_daily_digest(inputs)
    return _deliver_notification(
        delivery_ledger=delivery_ledger,
        delivery=ses_adapter.send_digest(
            EmailMessage(
                recipients=settings.recipient_emails,
                subject="Daily digest",
                body=digest.body,
            )
        ),
        message=EmailMessage(
            recipients=settings.recipient_emails,
            subject="Daily digest",
            body=digest.body,
        ),
        notification_type="daily_digest",
        now=now,
        retry_delay_seconds=settings.retry_delay_seconds,
    )


def detect_large_movement_alert(
    movement: PositionMovement,
    *,
    threshold_usd: Decimal = Decimal("25"),
    threshold_pct: Decimal = Decimal("0.10"),
) -> NotificationAlertDecision:
    """Return an alert when position P&L movement crosses defaults.

    REQ: REQ-NOT-003
    """

    change_usd = _as_decimal(movement.change_usd)
    change_pct = _as_decimal(movement.change_pct)
    if abs(change_usd) < threshold_usd and abs(change_pct) < threshold_pct:
        return NotificationAlertDecision(
            should_send=False,
            alert_type="large_position_movement",
            skipped_reason="movement below threshold",
        )
    return NotificationAlertDecision(
        should_send=True,
        alert_type="large_position_movement",
        subject="Large position movement",
        body=(
            f"Position {movement.position_id} P&L changed "
            f"{change_usd} USD / {change_pct:.2%}"
        ),
    )


def send_large_movement_alert(
    *,
    settings: NotificationSettings,
    movement: PositionMovement,
    alert_key: str,
    now: datetime,
    ses_adapter: InMemorySesEmailAdapter,
    cooldown_ledger: AlertCooldownLedger,
    delivery_ledger: NotificationDeliveryLedger,
) -> NotificationSendResult:
    """Send a large movement alert when thresholds and cooldown allow it.

    REQ: REQ-NOT-003, REQ-NOT-005, REQ-NOT-006, REQ-NOT-007
    """

    decision = detect_large_movement_alert(
        movement,
        threshold_usd=settings.thresholds.get("position_usd", Decimal("25")),
        threshold_pct=settings.thresholds.get("position_pct", Decimal("0.10")),
    )
    if not decision.should_send:
        return _record_notification_result(
            delivery_ledger=delivery_ledger,
            delivery=EmailDeliveryResult(
                sent=False,
                attempt_recorded=False,
                skipped_reason=decision.skipped_reason,
            ),
            message=EmailMessage(
                recipients=settings.recipient_emails,
                subject=decision.subject,
                body=decision.body,
            ),
            notification_type=decision.alert_type,
            now=now,
            retry_delay_seconds=settings.retry_delay_seconds,
        )

    cooldown = alert_allowed_by_cooldown(
        cooldown_ledger,
        alert_key,
        now,
        cooldown_seconds=settings.cooldown_seconds,
    )
    if not cooldown.allowed:
        return _record_notification_result(
            delivery_ledger=delivery_ledger,
            delivery=EmailDeliveryResult(
                sent=False,
                attempt_recorded=False,
                skipped_reason=cooldown.skipped_reason,
            ),
            message=EmailMessage(
                recipients=settings.recipient_emails,
                subject=decision.subject,
                body=decision.body,
            ),
            notification_type=decision.alert_type,
            now=now,
            retry_delay_seconds=settings.retry_delay_seconds,
        )

    message = EmailMessage(
        recipients=settings.recipient_emails,
        subject=decision.subject,
        body=decision.body,
    )
    result = _deliver_notification(
        delivery_ledger=delivery_ledger,
        delivery=ses_adapter.send_alert(message),
        message=message,
        notification_type=decision.alert_type,
        now=now,
        retry_delay_seconds=settings.retry_delay_seconds,
    )
    if result.sent:
        cooldown_ledger.record_sent(alert_key, now)
    return result


def detect_daily_pnl_alert(
    summary: DailyPnlSummary,
    *,
    threshold_usd: Decimal,
) -> NotificationAlertDecision:
    """Return an alert when daily realized or unrealized P&L crosses threshold.

    REQ: REQ-NOT-004
    """

    realized = _as_decimal(summary.realized_pnl)
    unrealized = _as_decimal(summary.unrealized_pnl)
    threshold = _as_decimal(threshold_usd)
    if abs(realized) < threshold and abs(unrealized) < threshold:
        return NotificationAlertDecision(
            should_send=False,
            alert_type="daily_pnl_threshold",
            skipped_reason="daily pnl within thresholds",
        )
    return NotificationAlertDecision(
        should_send=True,
        alert_type="daily_pnl_threshold",
        subject="Daily P&L threshold crossed",
        body=f"Daily P&L crossed threshold: realized {realized}, unrealized {unrealized}",
    )


def alert_allowed_by_cooldown(
    ledger: AlertCooldownLedger,
    alert_key: str,
    now: datetime,
    *,
    cooldown_seconds: int = 1800,
) -> AlertCooldownResult:
    """Allow a new alert only after the configured cooldown window.

    REQ: REQ-NOT-005
    """

    last_sent_at = ledger.sent_at.get(alert_key)
    if last_sent_at is None:
        return AlertCooldownResult(allowed=True)
    next_allowed_at = last_sent_at + timedelta(seconds=cooldown_seconds)
    if now >= next_allowed_at:
        return AlertCooldownResult(allowed=True)
    return AlertCooldownResult(
        allowed=False,
        next_allowed_at=next_allowed_at,
        skipped_reason="alert cooldown active",
    )


def _deliver_notification(
    *,
    delivery_ledger: NotificationDeliveryLedger,
    delivery: EmailDeliveryResult,
    message: EmailMessage,
    notification_type: str,
    now: datetime,
    retry_delay_seconds: int,
) -> NotificationSendResult:
    return _record_notification_result(
        delivery_ledger=delivery_ledger,
        delivery=delivery,
        message=message,
        notification_type=notification_type,
        now=now,
        retry_delay_seconds=retry_delay_seconds,
    )


def _record_notification_result(
    *,
    delivery_ledger: NotificationDeliveryLedger,
    delivery: EmailDeliveryResult,
    message: EmailMessage,
    notification_type: str,
    now: datetime,
    retry_delay_seconds: int,
) -> NotificationSendResult:
    next_retry_at = now + timedelta(seconds=retry_delay_seconds) if delivery.retryable else None
    delivery_ledger.record(
        NotificationDeliveryRecord(
            notification_type=notification_type,
            recipients=message.recipients,
            subject=message.subject,
            attempted_at=now,
            sent=delivery.sent,
            message_id=delivery.message_id,
            skipped_reason=delivery.skipped_reason,
            retryable=delivery.retryable,
            next_retry_at=next_retry_at,
            error_summary=delivery.error_summary,
        )
    )
    return NotificationSendResult(
        sent=delivery.sent,
        notification_type=notification_type,
        message_id=delivery.message_id,
        skipped_reason=delivery.skipped_reason,
        retryable=delivery.retryable,
        next_retry_at=next_retry_at,
        error_summary=delivery.error_summary,
    )


def _digest_schedule_due(
    now: datetime,
    schedule_utc: str,
    last_sent_at: datetime | None,
) -> bool:
    scheduled = _parse_hhmm(schedule_utc)
    current = now.astimezone(UTC)
    if last_sent_at is not None and last_sent_at.astimezone(UTC).date() == current.date():
        return False
    return current.time().replace(second=0, microsecond=0) >= scheduled


def _parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _as_decimal(value: Any) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("value must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError("value must be finite")
    return decimal
