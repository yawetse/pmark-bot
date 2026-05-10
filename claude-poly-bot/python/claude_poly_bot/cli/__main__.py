"""Typer CLI entry point.

Per task list (TASK-001 / TASK-005 / TASK-008 / TASK-009):
- M1: `scanner [--once]` to run the scanner debug pass.
- M4+: `setup-wallets`, `setup-alpaca`, `setup-oauth`, `refresh-data`.

Other service subcommands (`claude-bot`, `openai-bot`, `dashboard-api`,
`data-refresh`) dispatch to bot.runner; current milestone returns a
stub error code.
"""

from __future__ import annotations

import asyncio
import sys

import typer

from claude_poly_bot.bot.runner import main as run_main

app = typer.Typer(help="claude-poly-bot CLI")


@app.command(name="scanner")
def scanner(once: bool = typer.Option(False, "--once", help="Run a single scan and exit.")) -> None:
    """Start the Polymarket scanner. Default: cadence loop. Use --once for the M1 demo."""
    code = asyncio.run(run_main("scanner", once=once))
    raise SystemExit(code)


@app.command(name="claude-bot")
def claude_bot() -> None:
    """Run the Claude bot. Stub until M2."""
    code = asyncio.run(run_main("claude-bot"))
    raise SystemExit(code)


@app.command(name="openai-bot")
def openai_bot() -> None:
    """Run the OpenAI bot. Stub until M6."""
    code = asyncio.run(run_main("openai-bot"))
    raise SystemExit(code)


@app.command(name="dashboard-api")
def dashboard_api() -> None:
    """Run the FastAPI dashboard backend. Stub until M8."""
    code = asyncio.run(run_main("dashboard-api"))
    raise SystemExit(code)


@app.command(name="data-refresh")
def data_refresh() -> None:
    """Run the daily data-refresh job. Stub until M11."""
    code = asyncio.run(run_main("data-refresh"))
    raise SystemExit(code)


def main() -> None:
    """Console-script entry point declared in pyproject.toml."""
    app()


if __name__ == "__main__":
    main()


# Silence unused-import warning — sys kept for potential future flag handling.
_ = sys
