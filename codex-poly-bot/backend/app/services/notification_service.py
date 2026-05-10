"""Notification rendering, alert, and cooldown helpers.

REQ: REQ-NOT-002, REQ-NOT-003, REQ-NOT-004, REQ-NOT-005
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any


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


def _as_decimal(value: Any) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("value must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError("value must be finite")
    return decimal
