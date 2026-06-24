#!/usr/bin/env python3
"""Synchronize local environment files without printing secret values.

This script creates or normalizes:

- .env.production
- .env.development
- .env.local

Existing values are preserved by default. Optional AWS and GitHub variable pulls
can fill missing keys when the local CLIs are authenticated. GitHub Actions
secrets cannot be read back through the GitHub API, so this script only reads
GitHub variables.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENTS = ("local", "development", "production")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

ORDERED_KEYS = (
    "APP_ENV",
    "ENVIRONMENT",
    "AWS_REGION",
    "AWS_ACCOUNT_ID",
    "AWS_PROFILE",
    "AWS_DEPLOY_ROLE_ARN",
    "AWS_SECRET_ACCESS_KEY",
    "LIVE_ENABLED",
    "TRADING_ACCOUNT_MODE",
    "DEFAULT_SELECTED_VENUE",
    "POLYMARKET_US_ENABLED",
    "POLYMARKET_INTERNATIONAL_ENABLED",
    "ALPACA_ENABLED",
    "POLYMARKET_MARKET_ORDER_SLIPPAGE",
    "ALPACA_MARKET_ORDER_SLIPPAGE",
    "ALPACA_ACCOUNT_STATUS",
    "POLYMARKET_API_BASE_URL",
    "POLYMARKET_GATEWAY_BASE_URL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "GITHUB_ALLOWED_USERS",
    "DASHBOARD_ALLOWED_USERS",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "BACKEND_TOKEN_SIGNING_SECRET",
    "DASHBOARD_SESSION_SECRET",
    "DASHBOARD_CSRF_TOKEN",
    "NEXTAUTH_URL",
    "DASHBOARD_TRUSTED_ORIGINS",
    "NEXT_PUBLIC_API_BASE_URL",
    "BACKEND_API_BASE_URL",
    "NEXT_PUBLIC_APP_ENV",
    "ALLOW_LOCAL_AUTH_BYPASS",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "POLYMARKET_KEY_ID",
    "POLYMARKET_SECRET_KEY",
    "POLYMARKET_PRIVATE_KEY",
    "ALPACA_KEY_ID",
    "ALPACA_SECRET_KEY",
    "ALPACA_BASE_URL",
    "ALPACA_DATA_FEED",
)

PROFILE_KEYS = {
    "APP_ENV",
    "ENVIRONMENT",
    "LIVE_ENABLED",
    "TRADING_ACCOUNT_MODE",
    "DEFAULT_SELECTED_VENUE",
    "POLYMARKET_US_ENABLED",
    "POLYMARKET_INTERNATIONAL_ENABLED",
    "ALPACA_ENABLED",
    "NEXT_PUBLIC_APP_ENV",
    "ALLOW_LOCAL_AUTH_BYPASS",
    "ALPACA_BASE_URL",
}

DEFAULTS: dict[str, OrderedDict[str, str]] = {
    "local": OrderedDict(
        (
            ("APP_ENV", "local"),
            ("ENVIRONMENT", "local"),
            ("AWS_REGION", "us-east-1"),
            ("AWS_ACCOUNT_ID", ""),
            ("AWS_PROFILE", ""),
            ("AWS_DEPLOY_ROLE_ARN", ""),
            ("AWS_SECRET_ACCESS_KEY", ""),
            ("LIVE_ENABLED", "false"),
            ("TRADING_ACCOUNT_MODE", "local"),
            ("DEFAULT_SELECTED_VENUE", "polymarket_us"),
            ("POLYMARKET_US_ENABLED", "false"),
            ("POLYMARKET_INTERNATIONAL_ENABLED", "false"),
            ("ALPACA_ENABLED", "false"),
            ("POLYMARKET_MARKET_ORDER_SLIPPAGE", "0.02"),
            ("ALPACA_MARKET_ORDER_SLIPPAGE", "0.005"),
            ("ALPACA_ACCOUNT_STATUS", "active"),
            ("POLYMARKET_API_BASE_URL", "https://api.polymarket.us"),
            ("POLYMARKET_GATEWAY_BASE_URL", "https://gateway.polymarket.us"),
            ("POLYMARKET_GAMMA_BASE_URL", "https://gamma-api.polymarket.com"),
            ("POLYMARKET_CLOB_BASE_URL", "https://clob.polymarket.com"),
            ("POLYMARKET_MARKET_DATA_LIMIT", "5"),
            ("POSTGRES_HOST", "localhost"),
            ("POSTGRES_PORT", "5432"),
            ("POSTGRES_DB", "codex_poly_bot"),
            ("POSTGRES_USER", "codex_poly_bot"),
            ("POSTGRES_PASSWORD", "change-me"),
            (
                "DATABASE_URL",
                "postgresql://codex_poly_bot:change-me@localhost:5432/codex_poly_bot",
            ),
            ("GITHUB_ALLOWED_USERS", ""),
            ("DASHBOARD_ALLOWED_USERS", "yaw"),
            ("GITHUB_CLIENT_ID", ""),
            ("GITHUB_CLIENT_SECRET", ""),
            ("BACKEND_TOKEN_SIGNING_SECRET", "local-dev-session-secret"),
            ("DASHBOARD_SESSION_SECRET", "local-dev-session-secret"),
            ("DASHBOARD_CSRF_TOKEN", "local-dev-csrf-token"),
            ("NEXTAUTH_URL", "http://localhost:3000"),
            ("DASHBOARD_TRUSTED_ORIGINS", "http://localhost:3000"),
            ("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000"),
            ("BACKEND_API_BASE_URL", "http://localhost:8000"),
            ("NEXT_PUBLIC_APP_ENV", "local"),
            ("ALLOW_LOCAL_AUTH_BYPASS", "true"),
            ("OPENAI_API_KEY", ""),
            ("ANTHROPIC_API_KEY", ""),
            ("POLYMARKET_KEY_ID", ""),
            ("POLYMARKET_SECRET_KEY", ""),
            ("POLYMARKET_PRIVATE_KEY", ""),
            ("ALPACA_KEY_ID", ""),
            ("ALPACA_SECRET_KEY", ""),
            ("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
            ("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets/v2"),
            ("ALPACA_DATA_FEED", "iex"),
        )
    ),
    "development": OrderedDict(
        (
            ("APP_ENV", "development"),
            ("ENVIRONMENT", "development"),
            ("AWS_REGION", "us-east-1"),
            ("AWS_ACCOUNT_ID", ""),
            ("AWS_PROFILE", ""),
            ("AWS_DEPLOY_ROLE_ARN", ""),
            ("AWS_SECRET_ACCESS_KEY", ""),
            ("LIVE_ENABLED", "false"),
            ("TRADING_ACCOUNT_MODE", "paper"),
            ("DEFAULT_SELECTED_VENUE", "alpaca"),
            ("POLYMARKET_US_ENABLED", "false"),
            ("POLYMARKET_INTERNATIONAL_ENABLED", "false"),
            ("ALPACA_ENABLED", "true"),
            ("POLYMARKET_MARKET_ORDER_SLIPPAGE", "0.02"),
            ("ALPACA_MARKET_ORDER_SLIPPAGE", "0.005"),
            ("ALPACA_ACCOUNT_STATUS", "paper_ready"),
            ("POLYMARKET_API_BASE_URL", "https://api.polymarket.us"),
            ("POLYMARKET_GATEWAY_BASE_URL", "https://gateway.polymarket.us"),
            ("POLYMARKET_GAMMA_BASE_URL", "https://gamma-api.polymarket.com"),
            ("POLYMARKET_CLOB_BASE_URL", "https://clob.polymarket.com"),
            ("POLYMARKET_MARKET_DATA_LIMIT", "5"),
            ("POSTGRES_HOST", ""),
            ("POSTGRES_PORT", "5432"),
            ("POSTGRES_DB", "codexbot"),
            ("POSTGRES_USER", "codexbot"),
            ("POSTGRES_PASSWORD", ""),
            ("DATABASE_URL", ""),
            ("GITHUB_ALLOWED_USERS", ""),
            ("DASHBOARD_ALLOWED_USERS", "yawetse"),
            ("GITHUB_CLIENT_ID", ""),
            ("GITHUB_CLIENT_SECRET", ""),
            ("BACKEND_TOKEN_SIGNING_SECRET", ""),
            ("DASHBOARD_SESSION_SECRET", ""),
            ("DASHBOARD_CSRF_TOKEN", ""),
            ("NEXTAUTH_URL", ""),
            ("DASHBOARD_TRUSTED_ORIGINS", ""),
            ("NEXT_PUBLIC_API_BASE_URL", ""),
            ("BACKEND_API_BASE_URL", ""),
            ("NEXT_PUBLIC_APP_ENV", "development"),
            ("ALLOW_LOCAL_AUTH_BYPASS", "false"),
            ("OPENAI_API_KEY", ""),
            ("ANTHROPIC_API_KEY", ""),
            ("POLYMARKET_KEY_ID", ""),
            ("POLYMARKET_SECRET_KEY", ""),
            ("POLYMARKET_PRIVATE_KEY", ""),
            ("ALPACA_KEY_ID", ""),
            ("ALPACA_SECRET_KEY", ""),
            ("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
            ("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets/v2"),
            ("ALPACA_DATA_FEED", "iex"),
        )
    ),
    "production": OrderedDict(
        (
            ("APP_ENV", "production"),
            ("ENVIRONMENT", "production"),
            ("AWS_REGION", "us-east-1"),
            ("AWS_ACCOUNT_ID", ""),
            ("AWS_PROFILE", ""),
            ("AWS_DEPLOY_ROLE_ARN", ""),
            ("AWS_SECRET_ACCESS_KEY", ""),
            ("LIVE_ENABLED", "true"),
            ("TRADING_ACCOUNT_MODE", "live"),
            ("DEFAULT_SELECTED_VENUE", "polymarket_us"),
            ("POLYMARKET_US_ENABLED", "true"),
            ("POLYMARKET_INTERNATIONAL_ENABLED", "false"),
            ("ALPACA_ENABLED", "true"),
            ("POLYMARKET_MARKET_ORDER_SLIPPAGE", "0.02"),
            ("ALPACA_MARKET_ORDER_SLIPPAGE", "0.005"),
            ("ALPACA_ACCOUNT_STATUS", "reviewing"),
            ("POLYMARKET_API_BASE_URL", "https://api.polymarket.us"),
            ("POLYMARKET_GATEWAY_BASE_URL", "https://gateway.polymarket.us"),
            ("POLYMARKET_GAMMA_BASE_URL", "https://gamma-api.polymarket.com"),
            ("POLYMARKET_CLOB_BASE_URL", "https://clob.polymarket.com"),
            ("POLYMARKET_MARKET_DATA_LIMIT", "5"),
            ("POSTGRES_HOST", ""),
            ("POSTGRES_PORT", "5432"),
            ("POSTGRES_DB", "codexbot"),
            ("POSTGRES_USER", "codexbot"),
            ("POSTGRES_PASSWORD", ""),
            ("DATABASE_URL", ""),
            ("GITHUB_ALLOWED_USERS", ""),
            ("DASHBOARD_ALLOWED_USERS", "yawetse"),
            ("GITHUB_CLIENT_ID", ""),
            ("GITHUB_CLIENT_SECRET", ""),
            ("BACKEND_TOKEN_SIGNING_SECRET", ""),
            ("DASHBOARD_SESSION_SECRET", ""),
            ("DASHBOARD_CSRF_TOKEN", ""),
            ("NEXTAUTH_URL", ""),
            ("DASHBOARD_TRUSTED_ORIGINS", ""),
            ("NEXT_PUBLIC_API_BASE_URL", ""),
            ("BACKEND_API_BASE_URL", ""),
            ("NEXT_PUBLIC_APP_ENV", "production"),
            ("ALLOW_LOCAL_AUTH_BYPASS", "false"),
            ("OPENAI_API_KEY", ""),
            ("ANTHROPIC_API_KEY", ""),
            ("POLYMARKET_KEY_ID", ""),
            ("POLYMARKET_SECRET_KEY", ""),
            ("POLYMARKET_PRIVATE_KEY", ""),
            ("ALPACA_KEY_ID", ""),
            ("ALPACA_SECRET_KEY", ""),
            ("ALPACA_BASE_URL", "https://api.alpaca.markets"),
            ("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets/v2"),
            ("ALPACA_DATA_FEED", "iex"),
        )
    ),
}

PATH_KEY_MAP = {
    "openai/api-key": "OPENAI_API_KEY",
    "anthropic/api-key": "ANTHROPIC_API_KEY",
    "polymarket/key-id": "POLYMARKET_KEY_ID",
    "polymarket/api-key-id": "POLYMARKET_KEY_ID",
    "polymarket/secret-key": "POLYMARKET_SECRET_KEY",
    "polymarket/api-secret": "POLYMARKET_SECRET_KEY",
    "polymarket/private-key": "POLYMARKET_PRIVATE_KEY",
    "alpaca/key-id": "ALPACA_KEY_ID",
    "alpaca/api-key-id": "ALPACA_KEY_ID",
    "alpaca/secret-key": "ALPACA_SECRET_KEY",
    "alpaca/api-secret": "ALPACA_SECRET_KEY",
    "github/client-id": "GITHUB_CLIENT_ID",
    "github/client-secret": "GITHUB_CLIENT_SECRET",
    "dashboard/backend-token-signing-secret": "BACKEND_TOKEN_SIGNING_SECRET",
    "dashboard/session-secret": "DASHBOARD_SESSION_SECRET",
    "dashboard/csrf-token": "DASHBOARD_CSRF_TOKEN",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "environment",
        nargs="?",
        default="all",
        choices=(*ENVIRONMENTS, "all"),
    )
    parser.add_argument("--pull-aws", action="store_true")
    parser.add_argument("--pull-github-vars", action="store_true")
    parser.add_argument("--repo", default="yawetse/pmark-bot")
    parser.add_argument("--overwrite-remote", action="store_true")
    args = parser.parse_args()

    targets = ENVIRONMENTS if args.environment == "all" else (args.environment,)
    for environment in targets:
        current = read_env(env_path(environment))
        values = OrderedDict(DEFAULTS[environment])
        values.update({k: v for k, v in current.items() if v != ""})
        for key in PROFILE_KEYS:
            values[key] = DEFAULTS[environment][key]

        if args.pull_aws and environment != "local":
            aws_values = read_aws_values(environment)
            merge_remote_values(values, aws_values, overwrite=args.overwrite_remote)

        if args.pull_github_vars:
            github_values = read_github_variables(args.repo, environment)
            merge_remote_values(values, github_values, overwrite=args.overwrite_remote)

        write_env(env_path(environment), values)
        print(f"wrote {env_path(environment).relative_to(PROJECT_ROOT)}")

    return 0


def env_path(environment: str) -> Path:
    if environment == "local":
        return PROJECT_ROOT / ".env.local"
    return PROJECT_ROOT / f".env.{environment}"


def read_env(path: Path) -> OrderedDict[str, str]:
    values: OrderedDict[str, str] = OrderedDict()
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values


def write_env(path: Path, values: OrderedDict[str, str]) -> None:
    keys = list(ORDERED_KEYS)
    keys.extend(key for key in values if key not in keys)
    lines = [
        "# Local copy of runtime environment settings.",
        "# Do not commit this file or paste secret values into chat.",
        "",
    ]
    seen: set[str] = set()
    for key in keys:
        if key in values:
            lines.append(f"{key}={values[key]}")
            seen.add(key)
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")


def merge_remote_values(
    values: OrderedDict[str, str],
    remote_values: dict[str, str],
    *,
    overwrite: bool,
) -> None:
    for key, value in remote_values.items():
        if key not in values:
            continue
        if overwrite or not values[key]:
            values[key] = value


def read_aws_values(environment: str) -> dict[str, str]:
    prefix = f"/codex-poly-bot/{environment}/"
    try:
        secret_names = aws_json(
            "secretsmanager",
            "list-secrets",
            "--filters",
            f"Key=name,Values={prefix}",
            "--query",
            "SecretList[].Name",
        )
    except RuntimeError as exc:
        print(f"skipped AWS {environment}: {exc}", file=sys.stderr)
        return {}

    values: dict[str, str] = {}
    for secret_name in secret_names or []:
        try:
            secret_string = aws_text(
                "secretsmanager",
                "get-secret-value",
                "--secret-id",
                secret_name,
                "--query",
                "SecretString",
            )
        except RuntimeError as exc:
            print(f"skipped AWS secret {secret_name}: {exc}", file=sys.stderr)
            continue
        values.update(secret_string_to_env(secret_name, prefix, secret_string))
    return values


def secret_string_to_env(secret_name: str, prefix: str, secret_string: str) -> dict[str, str]:
    try:
        payload = json.loads(secret_string)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return {
            key: str(value)
            for key, value in payload.items()
            if KEY_RE.match(str(key)) and value is not None
        }

    suffix = secret_name.removeprefix(prefix).strip("/")
    key = PATH_KEY_MAP.get(suffix)
    if key:
        return {key: secret_string}
    return {}


def read_github_variables(repo: str, environment: str) -> dict[str, str]:
    values: dict[str, str] = {}
    scopes: list[list[str]] = [["variable", "list", "--repo", repo, "--json", "name,value"]]
    if environment != "local":
        scopes.append(
            [
                "variable",
                "list",
                "--repo",
                repo,
                "--env",
                environment,
                "--json",
                "name,value",
            ]
        )
    for command in scopes:
        try:
            payload = gh_json(*command)
        except RuntimeError as exc:
            print(f"skipped GitHub variables {environment}: {exc}", file=sys.stderr)
            continue
        for item in payload or []:
            name = str(item.get("name", ""))
            value = str(item.get("value", ""))
            if KEY_RE.match(name):
                values[name] = value
    return values


def aws_json(*args: str) -> object:
    return json.loads(run_command("aws", *args, "--output", "json"))


def aws_text(*args: str) -> str:
    return run_command("aws", *args, "--output", "text")


def gh_json(*args: str) -> object:
    return json.loads(run_command("gh", *args))


def run_command(*args: str) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(message[-1] if message else f"{args[0]} failed")
    return result.stdout


if __name__ == "__main__":
    raise SystemExit(main())
