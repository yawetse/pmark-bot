"""SES email adapter contract helpers.

REQ: REQ-NOT-001, REQ-NOT-003, REQ-NOT-004, REQ-NOT-007
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


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


class BotoSesEmailAdapter:
    """SES adapter used by deployed runtime notification paths."""

    def __init__(
        self,
        *,
        source: str,
        region_name: str | None = None,
        client: object | None = None,
    ) -> None:
        self.source = _source_email_address(source)
        self.region_name = region_name
        if client is not None:
            self.client = client
            return
        import boto3

        self.client = boto3.client("ses", region_name=region_name)

    def send_email(self, message: EmailMessage) -> EmailDeliveryResult:
        """Send an email through AWS SES and return retry metadata."""

        if not message.recipients:
            return EmailDeliveryResult(
                sent=False,
                attempt_recorded=False,
                skipped_reason="no recipients",
            )
        try:
            response = self.client.send_email(
                Source=self.source,
                Destination={"ToAddresses": list(message.recipients)},
                Message={
                    "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": message.body, "Charset": "UTF-8"}},
                },
            )
        except Exception as exc:
            return EmailDeliveryResult(
                sent=False,
                attempt_recorded=True,
                retryable=True,
                error_summary=str(exc)[:240],
            )
        message_id = response.get("MessageId") if isinstance(response, dict) else None
        return EmailDeliveryResult(
            sent=True,
            attempt_recorded=True,
            message_id=str(message_id) if message_id else None,
        )

    def send_digest(self, digest: EmailMessage) -> EmailDeliveryResult:
        """Send a daily digest email."""

        return self.send_email(digest)

    def send_alert(self, alert: EmailMessage) -> EmailDeliveryResult:
        """Send an alert email."""

        return self.send_email(alert)


def ses_adapter_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    source: str | None = None,
) -> BotoSesEmailAdapter | None:
    """Build a real SES adapter when an identity is configured."""

    env = environ or os.environ
    ses_source = (source or env.get("SES_IDENTITY_EMAIL", "")).strip()
    if not ses_source:
        return None
    region = (env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1").strip()
    try:
        return BotoSesEmailAdapter(source=ses_source, region_name=region)
    except ImportError:
        return None


def _source_email_address(source: str) -> str:
    configured = source.strip()
    if "@" in configured:
        return configured
    domain = configured.removeprefix("@").strip()
    return f"notifications@{domain}"
