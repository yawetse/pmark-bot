#!/usr/bin/env python3
"""Run a safe Alpaca paper-trading smoke check.

This command reads gitignored development env values, checks the paper account
and market clock, and only submits a small paper order when --submit is passed.
It refuses production/live endpoints.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(PROJECT_ROOT / ".env.development"))
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--notional", default="1.00")
    parser.add_argument("--side", default="buy", choices=("buy", "sell"))
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--allow-closed-market", action="store_true")
    args = parser.parse_args()

    try:
        notional = parse_positive_decimal(args.notional, "notional")
        env = read_env(Path(args.env_file))
        check_development_paper_env(env)
    except ValueError as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2

    headers = {
        "APCA-API-KEY-ID": env["ALPACA_KEY_ID"],
        "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"],
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    base_url = env["ALPACA_BASE_URL"].rstrip("/")
    with httpx.Client(base_url=base_url, headers=headers, timeout=20.0) as client:
        account = request_json(client, "GET", "/v2/account")
        clock = request_json(client, "GET", "/v2/clock")
        print(
            json.dumps(
                {
                    "account_status": account.get("status"),
                    "buying_power": account.get("buying_power"),
                    "clock_is_open": clock.get("is_open"),
                    "next_open": clock.get("next_open"),
                    "paper_base_url": base_url,
                },
                indent=2,
                sort_keys=True,
            )
        )

        if not args.submit:
            print("dry_run: pass --submit to place the paper order")
            return 0
        if not clock.get("is_open") and not args.allow_closed_market:
            print("blocked: market is closed; rerun during market hours or pass --allow-closed-market")
            return 2

        order_payload = {
            "symbol": args.symbol.strip().upper(),
            "notional": str(notional),
            "side": args.side,
            "type": "market",
            "time_in_force": "day",
        }
        order = request_json(client, "POST", "/v2/orders", json_body=order_payload)
        print(
            json.dumps(
                {
                    "order_id": order.get("id"),
                    "status": order.get("status"),
                    "symbol": order.get("symbol"),
                    "notional": order.get("notional"),
                    "submitted_at": order.get("submitted_at"),
                    "type": order.get("type"),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"missing env file: {path}")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def check_development_paper_env(env: dict[str, str]) -> None:
    required = ("ALPACA_KEY_ID", "ALPACA_SECRET_KEY", "ALPACA_BASE_URL")
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise ValueError(f"missing required Alpaca env values: {', '.join(missing)}")
    if env.get("APP_ENV") not in {"", "development"}:
        raise ValueError("paper smoke requires APP_ENV=development")
    if env.get("ENVIRONMENT") not in {"", "development"}:
        raise ValueError("paper smoke requires ENVIRONMENT=development")
    if env.get("TRADING_ACCOUNT_MODE") != "paper":
        raise ValueError("paper smoke requires TRADING_ACCOUNT_MODE=paper")
    if env.get("LIVE_ENABLED", "false").lower() == "true":
        raise ValueError("paper smoke refuses LIVE_ENABLED=true")
    if env["ALPACA_BASE_URL"].rstrip("/") != PAPER_BASE_URL:
        raise ValueError(f"paper smoke requires ALPACA_BASE_URL={PAPER_BASE_URL}")


def parse_positive_decimal(value: str, field_name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if parsed <= 0 or not parsed.is_finite():
        raise ValueError(f"{field_name} must be positive")
    if parsed > Decimal("25.00"):
        raise ValueError(f"{field_name} must be 25.00 or less for this smoke command")
    return parsed.quantize(Decimal("0.01"))


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.request(method, path, json=json_body)
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"raw": response.text}
    if response.status_code >= 400:
        message = payload.get("message") if isinstance(payload, dict) else None
        raise ValueError(f"Alpaca {method} {path} failed with {response.status_code}: {message}")
    if not isinstance(payload, dict):
        raise ValueError(f"Alpaca {method} {path} returned an unexpected payload")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
