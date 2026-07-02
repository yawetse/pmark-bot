#!/usr/bin/env python3
"""Run a safe Polymarket US read-only smoke check.

The command fetches credential values from AWS Secrets Manager by name, performs
authenticated account and market reads through the Polymarket US adapter, and
prints only non-secret status metadata. It never calls order creation, preview,
or close-position methods.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import boto3


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain import Environment, Venue  # noqa: E402
from app.venues.polymarket import (  # noqa: E402
    POLYMARKET_US_API_BASE_URL,
    POLYMARKET_US_GATEWAY_BASE_URL,
    PolymarketApiCredentials,
    PolymarketClientBoundary,
    PolymarketLiveOrderAdapter,
    PolymarketVenueConfig,
)


SECRET_NAME_MAP = {
    "key_id": "polymarket/key-id",
    "secret_key": "polymarket/secret-key",
    "private_key": "polymarket/private-key",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("development", "production"), default="production")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--market-limit", type=int, default=5)
    parser.add_argument("--api-base-url", default=POLYMARKET_US_API_BASE_URL)
    parser.add_argument("--gateway-base-url", default=POLYMARKET_US_GATEWAY_BASE_URL)
    args = parser.parse_args()

    if args.market_limit <= 0 or args.market_limit > 50:
        print("blocked: --market-limit must be between 1 and 50", file=sys.stderr)
        return 2

    try:
        result = run_check(
            environment=Environment(args.environment),
            region=args.region,
            market_limit=args.market_limit,
            api_base_url=args.api_base_url,
            gateway_base_url=args.gateway_base_url,
        )
    except ValueError as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def run_check(
    *,
    environment: Environment,
    region: str,
    market_limit: int,
    api_base_url: str,
    gateway_base_url: str,
) -> dict[str, Any]:
    secrets = load_polymarket_secrets(environment=environment, region=region)
    credentials = PolymarketApiCredentials(
        key_id=secrets["key_id"],
        secret_key=secrets.get("secret_key") or secrets.get("private_key") or "",
    )
    adapter = PolymarketLiveOrderAdapter(
        config=PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=environment is Environment.PRODUCTION,
            client_boundary=PolymarketClientBoundary.OFFICIAL_SDK,
            base_url=api_base_url,
            gateway_base_url=gateway_base_url,
            credential_ref=f"/codex-poly-bot/{environment.value}/polymarket/secret-key",
        ),
        credentials=credentials,
    )

    credential_result = adapter.verify_credentials()
    market_result = adapter.read_markets(limit=market_limit)
    return {
        "environment": environment.value,
        "market_limit": market_limit,
        "ok": credential_result.ok and market_result.ok,
        "operations_attempted": ["account.balances", "markets.list"],
        "order_operations_attempted": [],
        "read_only_account_check": safe_result(credential_result),
        "read_only_market_check": safe_result(market_result),
        "region": region,
        "secret_names_present": [
            f"/codex-poly-bot/{environment.value}/{suffix}"
            for suffix in SECRET_NAME_MAP.values()
            if secrets.get(secret_key_for_suffix(suffix))
        ],
    }


def load_polymarket_secrets(*, environment: Environment, region: str) -> dict[str, str]:
    client = boto3.client("secretsmanager", region_name=region)
    values: dict[str, str] = {}
    missing: list[str] = []
    for key, suffix in SECRET_NAME_MAP.items():
        name = f"/codex-poly-bot/{environment.value}/{suffix}"
        try:
            response = client.get_secret_value(SecretId=name)
        except client.exceptions.ResourceNotFoundException:
            if key == "private_key":
                continue
            missing.append(name)
            continue
        secret = response.get("SecretString") or ""
        if not secret.strip() and key != "private_key":
            missing.append(name)
            continue
        values[key] = secret.strip()

    if missing:
        raise ValueError("missing required Polymarket secrets: " + ", ".join(missing))
    if not values.get("secret_key") and not values.get("private_key"):
        raise ValueError(
            f"missing required Polymarket secret material under /codex-poly-bot/{environment.value}/polymarket"
        )
    return values


def safe_result(result: Any) -> dict[str, Any]:
    return {
        "ok": bool(result.ok),
        "operation": result.payload.get("operation"),
        "refusal_reasons": list(result.refusal_reasons),
        "venue": result.payload.get("venue"),
        **({"market_count": result.payload["market_count"]} if "market_count" in result.payload else {}),
        **({"status_code": result.payload["status_code"]} if "status_code" in result.payload else {}),
        **({"error_type": result.payload["error_type"]} if "error_type" in result.payload else {}),
        **({"request_id_present": True} if result.payload.get("request_id") else {}),
    }


def secret_key_for_suffix(suffix: str) -> str:
    for key, value in SECRET_NAME_MAP.items():
        if value == suffix:
            return key
    raise KeyError(suffix)


if __name__ == "__main__":
    raise SystemExit(main())
