"""SES email adapter contract helpers.

REQ: REQ-NOT-001, REQ-NOT-003, REQ-NOT-004, REQ-NOT-007
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmailMessage:
    """Email delivery request for digest or alert messages.

    REQ: REQ-NOT-001, REQ-NOT-003, REQ-NOT-004, REQ-NOT-007
    """

    recipients: tuple[str, ...]
    subject: str
    body: str


@dataclass(frozen=True)
class EmailDeliveryResult:
    """SES delivery outcome with retry metadata."""

    sent: bool
    attempt_recorded: bool
    message_id: str | None = None
    retryable: bool = False
    error_summary: str | None = None
    skipped_reason: str | None = None


class InMemorySesEmailAdapter:
    """Mockable SES adapter that records delivery attempts.

    REQ: REQ-NOT-001, REQ-NOT-007
    """

    def __init__(self, *, fail_delivery: bool = False) -> None:
        self.fail_delivery = fail_delivery
        self.sent_count = 0
        self.attempts: tuple[EmailMessage, ...] = ()

    def send_email(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send an email or return retryable failure metadata.

        REQ: REQ-NOT-001, REQ-NOT-007
        """

        if not message.recipients:
            return EmailDeliveryResult(
                sent=False,
                attempt_recorded=False,
                skipped_reason="no recipients",
            )

        self.attempts = (*self.attempts, message)
        if self.fail_delivery:
            return EmailDeliveryResult(
                sent=False,
                attempt_recorded=True,
                retryable=True,
                error_summary="SES delivery failed",
            )

        self.sent_count += 1
        return EmailDeliveryResult(
            sent=True,
            attempt_recorded=True,
            message_id=f"ses-message-{self.sent_count}",
        )

    def send_digest(self, digest: EmailMessage) -> EmailDeliveryResult:
        """Send a daily digest email.

        REQ: REQ-NOT-001
        """

        return self.send_email(digest)

    def send_alert(self, alert: EmailMessage) -> EmailDeliveryResult:
        """Send a threshold or movement alert.

        REQ: REQ-NOT-003, REQ-NOT-004
        """

        return self.send_email(alert)
