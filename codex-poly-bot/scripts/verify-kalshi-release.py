#!/usr/bin/env python3
"""Verify a deployed Kalshi release using read-only calls and safe evidence."""

from __future__ import annotations

import base64
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.venues.kalshi import (  # noqa: E402
    KALSHI_DEMO_API_BASE_URL,
    KALSHI_PRODUCTION_API_BASE_URL,
    KalshiAuthSigner,
    KalshiCredentials,
    KalshiLiveOrderAdapter,
    kalshi_live_order_adapter_from_env,
)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _aws_json(arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["aws", *arguments, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _secret(name: str) -> str:
    payload = _aws_json(
        ["secretsmanager", "get-secret-value", "--secret-id", name]
    )
    value = str(payload.get("SecretString") or "")
    if not value:
        raise RuntimeError(f"required Kalshi secret is unavailable: {name}")
    return value.replace("\\n", "\n")


def _optional_secret(name: str) -> str | None:
    result = subprocess.run(
        [
            "aws",
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            name,
            "--output",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        if "ResourceNotFoundException" in result.stderr:
            return None
        raise RuntimeError(f"Kalshi secret lookup failed: {name}")
    payload = json.loads(result.stdout)
    value = str(payload.get("SecretString") or "")
    return value.replace("\\n", "\n") if value else None


def _json_get(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = Request(url, headers=headers or {}, method="GET")
    with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed release hosts
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"GET {url} returned a non-object response")
    return payload


def _signed_get(
    *,
    base_url: str,
    signer: KalshiAuthSigner,
    path: str,
    params: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    query = f"?{urlencode(params or [])}" if params else ""
    signed_path = f"/trade-api/v2/{path.lstrip('/')}"
    return _json_get(
        f"{base_url}/{path.lstrip('/')}{query}",
        headers=signer.headers("GET", signed_path),
    )


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _backend_token(username: str, secret: str) -> str:
    claims = {"username": username, "exp": int(time.time()) + 300}
    body = _base64url(json.dumps(claims, separators=(",", ":")).encode())
    signature = _base64url(
        hmac.new(secret.encode(), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def _runtime_username() -> str:
    explicit = os.environ.get("RUNTIME_CONFIG_USERNAME", "").strip()
    if explicit:
        return explicit
    allowed = [
        value.strip()
        for value in os.environ.get("DASHBOARD_ALLOWED_USERS", "").split(",")
        if value.strip()
    ]
    if len(allowed) != 1:
        raise RuntimeError("RUNTIME_CONFIG_USERNAME is required")
    return allowed[0]


def _validate_runtime_credential_rows(
    rows: list[dict[str, Any]],
    *,
    authenticated: bool,
) -> None:
    if len(rows) != 3 or any("private" in json.dumps(row).lower() for row in rows):
        raise RuntimeError("runtime Kalshi credential readiness is incomplete or unsafe")
    if authenticated:
        if any(not bool(row.get("configured")) for row in rows):
            raise RuntimeError("runtime Kalshi credential injection is incomplete")
        if any(str(row.get("status") or "") not in {"present", "disabled"} for row in rows):
            raise RuntimeError("runtime Kalshi credential state is not ready")
    elif any(bool(row.get("configured")) or bool(row.get("present")) for row in rows):
        raise RuntimeError("runtime reports Kalshi credentials configured when secrets are absent")


def _mutation_log_count(log_group: str, start_ms: str) -> int:
    payload = _aws_json(
        [
            "logs",
            "filter-log-events",
            "--log-group-name",
            log_group,
            "--start-time",
            start_ms,
            "--filter-pattern",
            '"kalshi_venue_request"',
        ]
    )
    return sum(
        1
        for event in payload.get("events") or []
        if "method=POST" in str(event.get("message") or "")
        or "method=DELETE" in str(event.get("message") or "")
    )


def _ecs_evidence(environment: str) -> dict[str, str]:
    service = _aws_json(
        [
            "ecs",
            "describe-services",
            "--cluster",
            f"codex-poly-bot-{environment}-cluster",
            "--services",
            f"codex-poly-bot-{environment}-backend",
        ]
    ).get("services") or []
    if len(service) != 1 or int(service[0].get("runningCount") or 0) < 1:
        raise RuntimeError("Kalshi release ECS backend is not stable")
    task_definition_arn = str(service[0].get("taskDefinition") or "")
    task_arns = _aws_json(
        [
            "ecs",
            "list-tasks",
            "--cluster",
            f"codex-poly-bot-{environment}-cluster",
            "--service-name",
            f"codex-poly-bot-{environment}-backend",
            "--desired-status",
            "RUNNING",
        ]
    ).get("taskArns") or []
    if not task_arns:
        raise RuntimeError("running backend task readback is unavailable")
    tasks = _aws_json(
        [
            "ecs",
            "describe-tasks",
            "--cluster",
            f"codex-poly-bot-{environment}-cluster",
            "--tasks",
            *task_arns,
        ]
    ).get("tasks") or []
    backend = next(
        (
            row
            for task in tasks
            for row in task.get("containers") or []
            if str(row.get("name") or "") == "backend"
        ),
        None,
    )
    image_digest = str((backend or {}).get("imageDigest") or "")
    if not image_digest.startswith("sha256:"):
        raise RuntimeError("running backend image digest is unavailable")
    return {
        "taskDefinition": task_definition_arn,
        "imageDigest": image_digest,
    }


def _credentials(environment: str, provider: str) -> KalshiCredentials:
    prefix = f"/codex-poly-bot/{environment}/kalshi/{provider}"
    return KalshiCredentials(
        key_id=_secret(f"{prefix}/key-id"),
        private_key_pem=_secret(f"{prefix}/private-key"),
    )


def _credential_inventory(
    environment: str,
) -> tuple[dict[str, KalshiCredentials] | None, list[dict[str, Any]]]:
    values: dict[str, dict[str, str | None]] = {}
    references: list[dict[str, Any]] = []
    for provider in ("market-data", "openai", "claude"):
        prefix = f"/codex-poly-bot/{environment}/kalshi/{provider}"
        provider_values: dict[str, str | None] = {}
        for field, suffix in (("key_id", "key-id"), ("private_key_pem", "private-key")):
            reference = f"{prefix}/{suffix}"
            value = _optional_secret(reference)
            provider_values[field] = value
            references.append({"reference": reference, "configured": value is not None})
        values[provider] = provider_values

    configured_count = sum(
        value is not None
        for provider_values in values.values()
        for value in provider_values.values()
    )
    if configured_count == 0:
        return None, references
    if configured_count != 6:
        missing = [row["reference"] for row in references if not row["configured"]]
        raise RuntimeError(
            "Kalshi secret configuration is incomplete: " + ", ".join(missing)
        )
    return (
        {
            provider: KalshiCredentials(
                key_id=str(provider_values["key_id"]),
                private_key_pem=str(provider_values["private_key_pem"]),
            )
            for provider, provider_values in values.items()
        },
        references,
    )


def main() -> int:
    environment = _required("DEPLOY_ENVIRONMENT")
    if environment not in {"development", "production"}:
        raise RuntimeError("DEPLOY_ENVIRONMENT must be development or production")
    base_url = (
        KALSHI_PRODUCTION_API_BASE_URL
        if environment == "production"
        else KALSHI_DEMO_API_BASE_URL
    )
    application_url = (
        os.environ.get("APPLICATION_URL", "").strip().rstrip("/")
        or f"https://{_required('APPLICATION_DOMAIN_NAME').rstrip('/')}"
    )
    release_start_ms = _required("RELEASE_START_MS")
    log_group = os.environ.get(
        "APPLICATION_LOG_GROUP_NAME",
        f"/aws/ecs/codex-poly-bot/{environment}",
    ).strip()

    exchange = _json_get(f"{base_url}/exchange/status")
    if not all(isinstance(exchange.get(key), bool) for key in ("exchange_active", "trading_active")):
        raise RuntimeError("public Kalshi exchange status is malformed")
    markets = _json_get(
        f"{base_url}/markets?{urlencode({'limit': 1, 'status': 'open', 'mve_filter': 'exclude'})}"
    ).get("markets") or []
    if not markets or not str(markets[0].get("ticker") or "").strip():
        raise RuntimeError("public Kalshi market summary returned no ticker")
    ticker = str(markets[0]["ticker"])

    credentials, secret_references = _credential_inventory(environment)
    credential_mode = "authenticated" if credentials is not None else "not-configured"
    authenticated_ticker_count: int | None = None
    provider_evidence: dict[str, dict[str, Any]] = {
        provider: {"status": "not-configured"}
        for provider in ("openai", "claude")
    }
    initial_counts: dict[str, tuple[int, int]] = {}
    adapters: dict[str, KalshiLiveOrderAdapter] = {}
    if credentials is not None:
        batch = _signed_get(
            base_url=base_url,
            signer=KalshiAuthSigner(credentials["market-data"]),
            path="markets/orderbooks",
            params=[("tickers", ticker)],
        )
        returned_tickers = {
            str(row.get("ticker") or "")
            for row in batch.get("orderbooks") or []
            if isinstance(row, dict)
        }
        if returned_tickers != {ticker}:
            raise RuntimeError(
                "authenticated Kalshi batch order book did not return the requested ticker"
            )
        authenticated_ticker_count = len(returned_tickers)

        for provider in ("openai", "claude"):
            provider_credentials = credentials[provider]
            adapter = KalshiLiveOrderAdapter(
                base_url=base_url,
                credentials=provider_credentials,
            )
            adapters[provider] = adapter
            api_keys = adapter.api_keys()
            balance = adapter.balance()
            fills = adapter.fills()
            orders = adapter.orders()
            if not all(result.ok for result in (api_keys, balance, fills, orders)):
                raise RuntimeError(f"authenticated Kalshi {provider} readback failed")
            matching = [
                row
                for row in api_keys.payload.get("api_keys") or []
                if str(row.get("api_key_id") or "") == provider_credentials.key_id
            ]
            if len(matching) != 1 or "read" not in {
                str(scope).lower() for scope in matching[0].get("scopes") or []
            }:
                raise RuntimeError(f"Kalshi {provider} key lacks broad read scope")
            raw_balance = balance.payload.get("balance")
            if not isinstance(raw_balance, int):
                raise RuntimeError(f"Kalshi {provider} balance is not integer cents")
            initial_counts[provider] = (
                len(fills.payload.get("fills") or []),
                len(orders.payload.get("orders") or []),
            )
            provider_evidence[provider] = {
                "status": "verified",
                "balanceCents": raw_balance,
                "balanceUsd": format(Decimal(raw_balance) / Decimal("100"), ".2f"),
                "scopesVerified": True,
            }

    token = _backend_token(
        _runtime_username(),
        _required("BACKEND_TOKEN_SIGNING_SECRET"),
    )
    wallets = _json_get(
        f"{application_url}/api/wallets/status",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Environment": environment,
        },
    )
    kalshi_rows = [
        row for row in wallets.get("credentials") or [] if row.get("venue") == "kalshi"
    ]
    _validate_runtime_credential_rows(
        kalshi_rows,
        authenticated=credentials is not None,
    )

    try:
        kalshi_live_order_adapter_from_env(
            {
                "APP_ENV": environment,
                "KALSHI_ENVIRONMENT": "production" if environment == "production" else "demo",
            }
        )
    except ValueError:
        missing_secret_refusal = True
    else:
        raise RuntimeError("missing-secret adapter construction did not fail closed")

    order_and_fill_counts_unchanged: bool | None = None
    if adapters:
        final_counts: dict[str, tuple[int, int]] = {}
        for provider, adapter in adapters.items():
            fills = adapter.fills()
            orders = adapter.orders()
            if not fills.ok or not orders.ok:
                raise RuntimeError(
                    f"final authenticated Kalshi {provider} count readback failed"
                )
            final_counts[provider] = (
                len(fills.payload.get("fills") or []),
                len(orders.payload.get("orders") or []),
            )
        if final_counts != initial_counts:
            raise RuntimeError("Kalshi order or fill counts changed during read-only verification")
        order_and_fill_counts_unchanged = True
    mutation_count = _mutation_log_count(log_group, release_start_ms)
    if mutation_count:
        raise RuntimeError(f"found {mutation_count} Kalshi POST or DELETE events")

    print(
        json.dumps(
            {
                "environment": environment,
                "kalshiHost": base_url.split("/trade-api", 1)[0],
                "publicExchangeStatus": "verified",
                "publicMarketTickerCount": 1,
                "credentialMode": credential_mode,
                "secretReferences": secret_references,
                "authenticatedBatchOrderBookStatus": (
                    "verified" if credentials is not None else "not-configured"
                ),
                "batchOrderBookRequestedTickerCount": 1 if credentials is not None else None,
                "batchOrderBookReturnedTickerCount": authenticated_ticker_count,
                "providerBalances": provider_evidence,
                "runtimeCredentialRows": len(kalshi_rows),
                "missingSecretLiveRefusal": missing_secret_refusal,
                "kalshiMutationEvents": 0,
                "orderAndFillCountsUnchanged": order_and_fill_counts_unchanged,
                "realOrderSmokeTest": "not-performed",
                **_ecs_evidence(environment),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Kalshi release verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
