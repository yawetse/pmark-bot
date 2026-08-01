#!/usr/bin/env python3
"""Verify deployed recurring-funding release guardrails without sending a transfer."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BROKER_POST_EVENT = "funding_broker_post_attempt"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _application_url() -> str:
    explicit = os.environ.get("APPLICATION_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    return f"https://{_required('APPLICATION_DOMAIN_NAME').rstrip('/')}"


def _runtime_username() -> str:
    explicit = os.environ.get("RUNTIME_CONFIG_USERNAME", "").strip()
    if explicit:
        return explicit
    allowed = [
        value.strip()
        for value in os.environ.get("DASHBOARD_ALLOWED_USERS", "").split(",")
        if value.strip()
    ]
    if len(allowed) == 1:
        return allowed[0]
    raise RuntimeError(
        "RUNTIME_CONFIG_USERNAME is required when DASHBOARD_ALLOWED_USERS does not contain exactly one user"
    )


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _backend_token(username: str, secret: str) -> str:
    claims = {
        "username": username,
        "exp": int(time.time()) + 300,
    }
    body = _base64url(
        json.dumps(claims, separators=(",", ":")).encode("utf-8")
    )
    signature = _base64url(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def _get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    attempts: int = 12,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers=headers or {}, method="GET")
            with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed release URL
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(5)
    raise RuntimeError(f"GET {url} did not return valid JSON: {last_error}")


def _broker_post_count(log_group: str, start_ms: str) -> int:
    command = [
        "aws",
        "logs",
        "filter-log-events",
        "--log-group-name",
        log_group,
        "--start-time",
        start_ms,
        "--filter-pattern",
        f'"{BROKER_POST_EVENT}"',
        "--output",
        "json",
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return len(payload.get("events", []))


def _aws_json(arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["aws", *arguments, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _release_asset_status(
    environment: str,
    ses_identity_email: str,
    certificate_arn: str,
) -> dict[str, object]:
    identity = _aws_json(
        ["sesv2", "get-email-identity", "--email-identity", ses_identity_email]
    )
    if identity.get("VerifiedForSendingStatus") is not True:
        raise RuntimeError("SES identity is not verified for sending")
    stacks = _aws_json(
        [
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            f"codex-poly-bot-{environment}",
        ]
    ).get("Stacks") or []
    if len(stacks) != 1:
        raise RuntimeError("CloudFormation stack readback is unavailable")
    stack = stacks[0]
    stack_status = str(stack.get("StackStatus") or "")
    if stack_status not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise RuntimeError(f"CloudFormation stack is not complete: {stack_status or 'unknown'}")
    outputs = {
        str(item.get("OutputKey")): item.get("OutputValue")
        for item in stack.get("Outputs") or []
    }
    if outputs.get("CertificateArn") != certificate_arn:
        raise RuntimeError("CloudFormation certificate output does not match the release certificate")
    return {
        "sesIdentityVerified": True,
        "cloudFormationStatus": stack_status,
        "acmCertificateBinding": "STACK_OUTPUT_MATCH",
        "tlsCertificateStatus": "VALID",
    }


def main() -> int:
    environment = _required("DEPLOY_ENVIRONMENT")
    if environment not in {"development", "production"}:
        raise RuntimeError("DEPLOY_ENVIRONMENT must be development or production")

    application_url = _application_url()
    username = _runtime_username()
    token = _backend_token(username, _required("BACKEND_TOKEN_SIGNING_SECRET"))
    release_start_ms = _required("RELEASE_START_MS")
    ses_identity_email = _required("SES_IDENTITY_EMAIL")
    certificate_arn = _required("CERTIFICATE_ARN")
    log_group = os.environ.get(
        "APPLICATION_LOG_GROUP_NAME",
        f"/aws/ecs/codex-poly-bot/{environment}",
    ).strip()

    health = _get_json(f"{application_url}/health")
    if health != {"status": "ok"}:
        raise RuntimeError(f"unexpected health response: {health!r}")

    funding = _get_json(
        f"{application_url}/api/funding?limit=1",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Environment": environment,
        },
    )
    if funding.get("environment") != environment:
        raise RuntimeError("funding readback returned the wrong environment")
    readiness = funding.get("directTransferReadiness") or {}
    actual = {
        "enabled": readiness.get("enabled"),
        "maxTransferUsd": readiness.get("maxTransferUsd"),
        "maxMonthlyTransferUsd": readiness.get("maxMonthlyTransferUsd"),
    }
    expected = {
        "enabled": False,
        "maxTransferUsd": "0.00",
        "maxMonthlyTransferUsd": "0.00",
    }
    if actual != expected:
        raise RuntimeError(f"unsafe direct-transfer readback: {actual!r}")

    config = _get_json(
        f"{application_url}/api/config/current",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Environment": environment,
        },
    )
    if config.get("environment") != environment:
        raise RuntimeError("config readback returned the wrong environment")
    settings = config.get("settings") or {}
    alpaca = settings.get("alpaca") or {}
    if alpaca.get("allow_shorting") is not False:
        raise RuntimeError("unsafe Alpaca short-selling readback: allow_shorting must be false")

    release_assets = _release_asset_status(
        environment,
        ses_identity_email,
        certificate_arn,
    )
    broker_post_count = _broker_post_count(log_group, release_start_ms)
    if broker_post_count != 0:
        raise RuntimeError(
            f"found {broker_post_count} {BROKER_POST_EVENT} events in the release window"
        )

    print(
        json.dumps(
            {
                "environment": environment,
                "health": "ok",
                "directTransfersEnabled": False,
                "alpacaShortingEnabled": False,
                "maxTransferUsd": "0.00",
                "maxMonthlyTransferUsd": "0.00",
                "brokerPostEvents": 0,
                "realTransferSmokeTest": "not-performed",
                **release_assets,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Funding release verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
