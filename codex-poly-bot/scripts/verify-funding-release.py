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


def main() -> int:
    environment = _required("DEPLOY_ENVIRONMENT")
    if environment not in {"development", "production"}:
        raise RuntimeError("DEPLOY_ENVIRONMENT must be development or production")

    application_url = _application_url()
    username = _required("RUNTIME_CONFIG_USERNAME")
    token = _backend_token(username, _required("BACKEND_TOKEN_SIGNING_SECRET"))
    release_start_ms = _required("RELEASE_START_MS")
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
                "maxTransferUsd": "0.00",
                "maxMonthlyTransferUsd": "0.00",
                "brokerPostEvents": 0,
                "realTransferSmokeTest": "not-performed",
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
