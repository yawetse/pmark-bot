"""Runtime readiness and dashboard status helpers.

REQ: REQ-UI-004, REQ-UI-009, REQ-NOT-006, REQ-DAT-008,
REQ-WAL-005, REQ-WAL-006, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.db.schema import SHARED_SCHEMA
from app.domain import Environment, ModelProvider, Venue
from app.services.llm_service import SCORING_SYSTEM_PROMPT


PLACEHOLDER_VALUES = {"", "change-me", "set-locally", "optional-in-dry-run"}


@dataclass(frozen=True)
class RuntimeCredentialView:
    """Dashboard-safe credential/account readiness row.

    REQ: REQ-UI-009, REQ-WAL-005
    """

    id: str
    label: str
    venue: str
    provider: str
    public_identifier: str
    present: bool
    reference: str
    status: str
    required_for_live: bool = True
    message: str | None = None

    def dashboard_payload(self) -> dict[str, Any]:
        """Return credential metadata without private material.

        REQ: REQ-UI-009, REQ-WAL-005
        """

        return {
            "id": self.id,
            "label": self.label,
            "venue": self.venue,
            "provider": self.provider,
            "publicIdentifier": self.public_identifier,
            "present": self.present,
            "reference": self.reference,
            "status": self.status,
            "requiredForLive": self.required_for_live,
            "message": self.message,
        }


class RuntimeStatusService:
    """Build live dashboard status from environment, config, and heartbeats.

    REQ: REQ-UI-004, REQ-UI-009, REQ-NOT-006, REQ-DAT-008
    """

    WORKER_JOB_NAME = "market-data-ingestion"
    MANUAL_RUN_JOB_NAME = "manual-trading-loop"
    USER_PREFERENCES_TABLE = f"{SHARED_SCHEMA}.user_preferences"
    MARKET_DATA_PULLS_TABLE = f"{SHARED_SCHEMA}.market_data_pulls"
    AI_USAGE_EVENTS_TABLE = f"{SHARED_SCHEMA}.ai_usage_events"

    def __init__(self, *, settings: Any, registry: RepositoryRegistry | None = None) -> None:
        self.settings = settings
        self.registry = registry or RepositoryRegistry()

    def runtime_config_payload(self) -> dict[str, Any]:
        """Return config defaults aligned to deployed runtime flags.

        REQ: REQ-UI-004, REQ-UI-005, REQ-EXE-001
        """

        return {
            "default_selected_venue": self.settings.default_selected_venue.value,
            "live_enabled": self.settings.live_enabled,
            "venues": {
                Venue.POLYMARKET_US.value: {"enabled": self.settings.polymarket_us_enabled},
                Venue.POLYMARKET_INTERNATIONAL.value: {
                    "enabled": self.settings.polymarket_international_enabled
                },
                Venue.ALPACA.value: {"enabled": self.settings.alpaca_enabled},
            },
            "trading_loop_interval_seconds": 60,
            "strategies": {
                "arbitrage": {"enabled": True, "settings": {}},
                "convergence": {"enabled": True, "settings": {}},
                "whale_copy": {"enabled": True, "settings": {}},
            },
            "llm": {
                ModelProvider.CLAUDE.value: {"budget_usd": "20.00", "settings": {}},
                ModelProvider.OPENAI.value: {"budget_usd": "20.00", "settings": {}},
            },
            "risk": {
                "polymarket": {
                    "max_position_usd": "25.00",
                    "max_daily_loss_usd": "50.00",
                    "max_open_positions": 5,
                    "market_order_slippage_threshold": self.settings.polymarket_slippage_threshold,
                },
                "alpaca": {
                    "max_position_usd": "100.00",
                    "max_daily_loss_usd": "100.00",
                    "max_open_positions": 5,
                    "max_portfolio_allocation_per_symbol": "0.10",
                    "market_order_slippage_threshold": self.settings.alpaca_slippage_threshold,
                },
            },
            "alpaca": {
                "account_mode": self.settings.trading_account_mode,
                "account_status": self.settings.alpaca_account_status,
                "symbol_universe": ["SPY"],
            },
            "notifications": {
                "recipients": self.settings.notification_recipients,
                "thresholds": {},
                "cooldown_seconds": 1800,
                "digest_schedule_utc": "13:00",
                "ses_identity": self.settings.ses_identity_email,
            },
        }

    def record_worker_heartbeat(self, *, status: str = "ok", message: str | None = None) -> None:
        """Persist an ingestion scheduler heartbeat for dashboard reads.

        REQ: REQ-DAT-008, REQ-OBS-005
        """

        now = datetime.now(UTC)
        try:
            self.registry.state.insert(
                f"{SHARED_SCHEMA}.job_runs",
                {
                    "id": str(uuid4()),
                    "job_name": self.WORKER_JOB_NAME,
                    "status": status,
                    "heartbeat_at": now,
                    "metadata": {
                        "message": message or "scheduler heartbeat",
                        "scheduled": True,
                    },
                    "created_at": now,
                },
            )
        except PersistenceUnavailableError:
            return

    def user_preferences(self, *, username: str, environment: Environment) -> dict[str, Any]:
        """Return saved dashboard preferences with fail-safe defaults.

        REQ: REQ-UI-004, REQ-OBS-005
        """

        try:
            rows = [
                row
                for row in self.registry.state.rows(self.USER_PREFERENCES_TABLE)
                if row["username"] == username and row["environment"] == environment.value
            ]
        except PersistenceUnavailableError:
            rows = []
        if not rows:
            return {
                "environment": environment.value,
                "username": username,
                "settings": default_user_preferences(),
                "updatedAt": None,
            }
        latest = max(rows, key=lambda row: row["updated_at"])
        return {
            "environment": environment.value,
            "username": username,
            "settings": _merge_preferences(latest["payload"]),
            "updatedAt": latest["updated_at"].isoformat(),
        }

    def save_user_preferences(
        self,
        *,
        username: str,
        ip_address: str,
        environment: Environment,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one user's dashboard display and cost assumptions.

        REQ: REQ-UI-004, REQ-OBS-004, REQ-OBS-005
        """

        preferences = _validate_user_preferences(payload)
        now = datetime.now(UTC)
        row = self.registry.state.insert(
            self.USER_PREFERENCES_TABLE,
            {
                "id": str(uuid4()),
                "username": username,
                "environment": environment.value,
                "payload": preferences,
                "updated_at": now,
            },
        )
        audit_event = self.registry.shared().record_audit_event(
            event_type="dashboard_preferences_change",
            actor=username,
            action="preferences.update",
            environment=environment,
            success=True,
            metadata={
                "ip_address": ip_address,
                "theme": preferences["theme"],
                "time_zone": preferences["timeZone"],
                "aws_monthly_infra_cost_usd": preferences["awsMonthlyInfraCostUsd"],
            },
        )
        return {
            "environment": environment.value,
            "username": username,
            "settings": row["payload"],
            "updatedAt": row["updated_at"].isoformat(),
            "auditEventId": audit_event["id"],
        }

    def trigger_manual_run(
        self,
        *,
        username: str,
        ip_address: str,
        environment: Environment,
        config_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Record an operator-triggered dry-run loop request for the dashboard.

        REQ: REQ-UI-008, REQ-DAT-008, REQ-OBS-004, REQ-OBS-005
        """

        now = datetime.now(UTC)
        run_id = str(uuid4())
        selected_venue = str(config_payload.get("default_selected_venue", "unknown"))
        market_data_pull = self._record_market_data_pull(
            environment=environment,
            venue=selected_venue,
            trigger="manual",
            status="accepted",
            message="Manual run accepted. No external market data adapter call is attached to this dashboard record yet.",
            candidates=[],
            created_at=now,
            run_id=run_id,
        )
        self.registry.state.insert(
            f"{SHARED_SCHEMA}.job_runs",
            {
                "id": run_id,
                "job_name": self.MANUAL_RUN_JOB_NAME,
                "status": "accepted",
                "heartbeat_at": now,
                "metadata": {
                    "message": "manual loop request accepted",
                    "scheduled": False,
                    "triggered_by": username,
                    "market_data_pull_id": market_data_pull["id"],
                },
                "created_at": now,
            },
        )
        self.registry.state.insert(
            f"{SHARED_SCHEMA}.job_runs",
            {
                "id": str(uuid4()),
                "job_name": self.WORKER_JOB_NAME,
                "status": "ok",
                "heartbeat_at": now,
                "metadata": {
                    "message": "manual dashboard run heartbeat",
                    "scheduled": False,
                    "triggered_by": username,
                    "manual_run_id": run_id,
                },
                "created_at": now,
            },
        )
        audit_event = self.registry.shared().record_audit_event(
            event_type="manual_loop_trigger",
            actor=username,
            action="loop.manual_run",
            environment=environment,
            entity_id=run_id,
            success=True,
            metadata={
                "ip_address": ip_address,
                "venue": selected_venue,
                "market_data_pull_id": market_data_pull["id"],
            },
        )
        return {
            "environment": environment.value,
            "runId": run_id,
            "status": "accepted",
            "triggeredBy": username,
            "triggeredAt": now.isoformat(),
            "auditEventId": audit_event["id"],
            "message": "Manual run accepted. Live order submission still depends on all configured gates.",
            "marketDataPull": market_data_pull,
        }

    def worker_status(self) -> dict[str, Any]:
        """Return latest worker heartbeat status.

        REQ: REQ-DAT-008, REQ-OBS-005
        """

        try:
            rows = [
                row
                for row in self.registry.state.rows(f"{SHARED_SCHEMA}.job_runs")
                if row["job_name"] == self.WORKER_JOB_NAME
            ]
        except PersistenceUnavailableError:
            return {
                "state": "blocked",
                "value": "Worker status unavailable",
                "lastHeartbeatAt": None,
                "ageSeconds": None,
            }
        if not rows:
            return {
                "state": "blocked",
                "value": "Awaiting worker heartbeat",
                "lastHeartbeatAt": None,
                "ageSeconds": None,
            }
        latest = max(rows, key=lambda row: row["heartbeat_at"] or row["created_at"])
        heartbeat = latest["heartbeat_at"] or latest["created_at"]
        age_seconds = int((datetime.now(UTC) - heartbeat).total_seconds())
        state = "ok" if latest["status"] == "ok" and age_seconds <= 180 else "blocked"
        value = "Scheduler heartbeat current" if state == "ok" else "Worker heartbeat stale"
        return {
            "state": state,
            "value": value,
            "lastHeartbeatAt": heartbeat.isoformat(),
            "ageSeconds": age_seconds,
        }

    def credential_rows(self, environment: Environment) -> list[dict[str, Any]]:
        """Return safe credential readiness rows for wallet/account UI.

        REQ: REQ-UI-009, REQ-WAL-005, REQ-WAL-006
        """

        rows = [
            self._credential_row(
                credential_id="polymarket_us-openai-wallet",
                label="Polymarket US wallet",
                venue=Venue.POLYMARKET_US.value,
                provider=ModelProvider.OPENAI.value,
                reference=f"/codex-poly-bot/{environment.value}/polymarket",
                required_names=("POLYMARKET_KEY_ID", "POLYMARKET_SECRET_KEY", "POLYMARKET_PRIVATE_KEY"),
                public_identifier="pm-openai-" + environment.value,
                enabled=self.settings.polymarket_us_enabled,
            ),
            self._credential_row(
                credential_id="alpaca-claude-account",
                label="Alpaca account",
                venue=Venue.ALPACA.value,
                provider=ModelProvider.CLAUDE.value,
                reference=f"/codex-poly-bot/{environment.value}/alpaca",
                required_names=("ALPACA_KEY_ID", "ALPACA_SECRET_KEY"),
                public_identifier="alpaca-claude-" + self.settings.trading_account_mode,
                enabled=self.settings.alpaca_enabled,
                account_status=self.settings.alpaca_account_status,
            ),
            self._credential_row(
                credential_id="openai-api",
                label="OpenAI API",
                venue="llm",
                provider=ModelProvider.OPENAI.value,
                reference=f"/codex-poly-bot/{environment.value}/openai/api-key",
                required_names=("OPENAI_API_KEY",),
                public_identifier="openai-" + environment.value,
                enabled=True,
            ),
            self._credential_row(
                credential_id="anthropic-api",
                label="Anthropic API",
                venue="llm",
                provider=ModelProvider.CLAUDE.value,
                reference=f"/codex-poly-bot/{environment.value}/anthropic/api-key",
                required_names=("ANTHROPIC_API_KEY",),
                public_identifier="anthropic-" + environment.value,
                enabled=True,
            ),
        ]
        return [row.dashboard_payload() for row in rows]

    def status_items(self, *, environment: Environment, config_payload: dict[str, Any]) -> list[dict[str, str]]:
        """Build the dashboard status overview from runtime state.

        REQ: REQ-UI-004, REQ-OBS-005
        """

        worker = self.worker_status()
        credentials = self.credential_rows(environment)
        missing_required = [item for item in credentials if item["requiredForLive"] and not item["present"]]
        notifications = self.notification_summary(config_payload)
        live_enabled = bool(config_payload.get("live_enabled", False))
        selected_venue = str(config_payload.get("default_selected_venue", "unknown"))
        venues = config_payload.get("venues", {})
        selected_enabled = bool(venues.get(selected_venue, {}).get("enabled", False))
        live_blocked = bool(missing_required) or self.settings.alpaca_account_status in {"reviewing", "pending"}
        return [
            {
                "label": "Venue",
                "value": f"{selected_venue} {'enabled' if selected_enabled else 'disabled'}",
                "state": "ok" if selected_enabled else "blocked",
            },
            {
                "label": "Wallet",
                "value": "Credentials ready" if not missing_required else f"{len(missing_required)} missing",
                "state": "ok" if not missing_required else "blocked",
            },
            {
                "label": "Ingestion",
                "value": str(worker["value"]),
                "state": str(worker["state"]),
            },
            {
                "label": "Trading loop",
                "value": "Live gated" if live_enabled and live_blocked else ("Live enabled" if live_enabled else "Dry run"),
                "state": "blocked" if live_enabled and live_blocked else "ok",
            },
            {
                "label": "Notification",
                "value": notifications["value"],
                "state": notifications["state"],
            },
            {"label": "Audit", "value": "Ready", "state": "ok"},
            {"label": "Health", "value": "API reachable", "state": "ok"},
        ]

    def notification_summary(self, config_payload: dict[str, Any]) -> dict[str, Any]:
        """Return notification dashboard readiness.

        REQ: REQ-NOT-006, REQ-OBS-005
        """

        notification_config = config_payload.get("notifications", {})
        recipients = notification_config.get("recipients", {})
        valid_recipients = [value for value in recipients.values() if _valid_email(str(value))]
        recipient_count = len(valid_recipients)
        ses_identity = notification_config.get("ses_identity") or self.settings.ses_identity_email
        configured = bool(recipient_count and ses_identity)
        return {
            "state": "ok" if configured else "blocked",
            "status": "configured" if configured else "not_configured",
            "value": f"{recipient_count} recipient configured" if configured else "Not configured",
            "recipientCount": recipient_count,
            "sesIdentity": ses_identity,
            "settings": notification_config,
        }

    def operations_summary(self, environment: Environment) -> dict[str, Any]:
        """Return operational status and latest order rows.

        REQ: REQ-EXE-014, REQ-EXE-016, REQ-OBS-005
        """

        order_items = self.order_events()
        open_orders = [
            item
            for item in order_items
            if item["state"] not in {"filled", "canceled", "failed", "refused"}
        ]
        return {
            "environment": environment.value,
            "killSwitch": "inactive",
            "openOrders": len(open_orders),
            "cancelProgress": "0 / 0",
            "manualReview": "none",
            "degradedVenueStatus": "none",
            "manualReviewState": "clear",
            "orderEvents": order_items,
        }

    def market_data_pull(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Return the latest dashboard-visible market-data pull.

        REQ: REQ-DAT-001, REQ-DAT-008, REQ-OBS-005
        """

        selected_venue = str(config_payload.get("default_selected_venue", "unknown"))
        try:
            rows = [
                row
                for row in self.registry.state.rows(self.MARKET_DATA_PULLS_TABLE)
                if row["environment"] == environment.value
            ]
        except PersistenceUnavailableError:
            rows = []
        if not rows:
            return {
                "id": None,
                "environment": environment.value,
                "venue": selected_venue,
                "status": "idle",
                "trigger": "none",
                "source": "dashboard store",
                "lastPulledAt": None,
                "candidateCount": 0,
                "candidates": [],
                "message": "No market data pull has been recorded in the dashboard store.",
            }
        latest = max(rows, key=lambda row: row["created_at"])
        return self._market_data_payload(latest)

    def economics_summary(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        """Return token, cost, and P&L totals for profitability review.

        REQ: REQ-UI-004, REQ-UI-010, REQ-CMP-002, REQ-OBS-005
        """

        ai_usage = self._ai_usage_summary(environment, config_payload)
        trading = self._trading_pnl_summary()
        monthly_aws = _as_money(preferences.get("awsMonthlyInfraCostUsd", "0.00"))
        daily_aws = monthly_aws / Decimal("30")
        recorded_costs = _as_money(ai_usage["totalCostUsd"]) + daily_aws
        trading_total = _as_money(trading["totalPnlUsd"])
        net = trading_total - recorded_costs
        return {
            "environment": environment.value,
            "generatedAt": datetime.now(UTC).isoformat(),
            "trading": trading,
            "ai": ai_usage,
            "aws": {
                "monthlyInfraCostUsd": _money(monthly_aws),
                "dailyInfraCostEstimateUsd": _money(daily_aws),
                "source": "user preference",
            },
            "profitability": {
                "netAfterRecordedCostsUsd": _money(net),
                "status": "profitable" if net > 0 else ("losing" if net < 0 else "flat"),
                "costBasis": "trading P&L minus recorded AI cost and one day of AWS infrastructure cost",
            },
        }

    def loop_observability(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        config_degraded: bool = False,
        kill_switch_active: bool = False,
    ) -> dict[str, Any]:
        """Return a dashboard-safe view of loop timing, inputs, gates, and logic.

        REQ: REQ-UI-004, REQ-OBS-005
        """

        now = datetime.now(UTC)
        worker = self.worker_status()
        interval_seconds = _positive_int(
            config_payload.get("trading_loop_interval_seconds"),
            default=60,
        )
        last_heartbeat = _parse_datetime(worker.get("lastHeartbeatAt"))
        next_run_at = (
            last_heartbeat + timedelta(seconds=interval_seconds)
            if last_heartbeat is not None
            else now + timedelta(seconds=interval_seconds)
        )
        seconds_until_next_run = max(0, int((next_run_at - now).total_seconds()))
        selected_venue = str(config_payload.get("default_selected_venue", "unknown"))
        venues = config_payload.get("venues", {})
        selected_venue_enabled = bool(venues.get(selected_venue, {}).get("enabled", False))
        live_enabled = bool(config_payload.get("live_enabled", False))
        credentials = self.credential_rows(environment)
        credential_blockers = self._loop_credential_blockers(credentials, selected_venue)
        order_events = self.order_events()
        open_orders = [
            item
            for item in order_events
            if item["state"] not in {"filled", "canceled", "failed", "refused"}
        ]
        status = self._loop_status(
            worker_state=str(worker["state"]),
            live_enabled=live_enabled,
            selected_venue_enabled=selected_venue_enabled,
            credential_blockers=len(credential_blockers),
            kill_switch_active=kill_switch_active,
        )
        alpaca_config = config_payload.get("alpaca", {})
        alpaca_symbols = alpaca_config.get("symbol_universe") or []
        risk_config = config_payload.get("risk", {})
        llm_config = config_payload.get("llm", {})
        enabled_strategies = [
            name
            for name, strategy_config in config_payload.get("strategies", {}).items()
            if strategy_config.get("enabled", False)
        ]
        market_data = self.market_data_pull(
            environment=environment,
            config_payload=config_payload,
        )

        return {
            "environment": environment.value,
            "generatedAt": now.isoformat(),
            "status": status,
            "schedule": {
                "intervalSeconds": interval_seconds,
                "lastHeartbeatAt": worker.get("lastHeartbeatAt"),
                "ageSeconds": worker.get("ageSeconds"),
                "nextRunAt": next_run_at.isoformat(),
                "secondsUntilNextRun": seconds_until_next_run,
                "source": worker.get("value"),
            },
            "currentPhase": self._current_loop_phase(
                worker_state=str(worker["state"]),
                live_enabled=live_enabled,
                selected_venue_enabled=selected_venue_enabled,
                credential_blockers=len(credential_blockers),
                kill_switch_active=kill_switch_active,
            ),
            "stages": self._loop_stages(
                worker_state=str(worker["state"]),
                config_degraded=config_degraded,
                live_enabled=live_enabled,
                selected_venue_enabled=selected_venue_enabled,
                credential_blockers=len(credential_blockers),
                kill_switch_active=kill_switch_active,
                order_count=len(order_events),
            ),
            "dataInputs": [
                {
                    "label": "Selected venue",
                    "value": selected_venue,
                    "state": "ok" if selected_venue_enabled else "blocked",
                    "detail": "Venue flag controls whether candidates can be evaluated there.",
                },
                {
                    "label": "Alpaca symbols",
                    "value": ", ".join(str(symbol) for symbol in alpaca_symbols) or "none",
                    "state": "ok" if alpaca_symbols else "blocked",
                    "detail": "Symbols are read from config before Alpaca candidate filtering.",
                },
                {
                    "label": "Market candidates",
                    "value": f"{market_data['candidateCount']} captured",
                    "state": "ok" if market_data["candidateCount"] else "idle",
                    "detail": market_data["message"],
                },
                {
                    "label": "Recent order events",
                    "value": str(len(order_events)),
                    "state": "ok" if order_events else "idle",
                    "detail": "Order events are read from provider-specific order event tables.",
                },
                {
                    "label": "Open orders",
                    "value": str(len(open_orders)),
                    "state": "blocked" if open_orders else "ok",
                    "detail": "Non-terminal order events stay visible for operator review.",
                },
            ],
            "prompts": [
                {
                    "label": "Scoring system prompt",
                    "value": SCORING_SYSTEM_PROMPT,
                    "state": "ok",
                    "detail": "Used by OpenAI Responses and Claude Messages scoring adapters.",
                },
                {
                    "label": "Prompt version",
                    "value": "pm-v1",
                    "state": "ok",
                    "detail": "Default request version attached to each LLM scoring request.",
                },
                {
                    "label": "Latest prompt run",
                    "value": "none captured",
                    "state": "idle",
                    "detail": "No prompt execution row is available in the dashboard store.",
                },
            ],
            "logic": [
                {
                    "label": "Candidate filters",
                    "value": "enabled venue, liquidity, spread, resolution window, symbol universe",
                    "state": "ok",
                    "detail": "Deterministic filters run before any LLM scoring request.",
                },
                {
                    "label": "Enabled strategies",
                    "value": ", ".join(enabled_strategies) or "none",
                    "state": "ok" if enabled_strategies else "blocked",
                    "detail": "Strategy consensus requires persisted directional signals.",
                },
                {
                    "label": "LLM scoring budgets",
                    "value": self._llm_budget_summary(llm_config),
                    "state": "ok",
                    "detail": "Provider budgets gate scoring requests before cost is recorded.",
                },
                {
                    "label": "Live order gates",
                    "value": "live flag, venue, credentials, market data, scoring, risk, kill switch",
                    "state": status["state"],
                    "detail": "Every gate must pass before live venue submission.",
                },
            ],
            "calculations": [
                {
                    "label": "Loop cadence",
                    "formula": "next_run_at = last_heartbeat_at + interval_seconds",
                    "value": f"{interval_seconds}s interval",
                    "state": "ok" if worker["state"] == "ok" else "blocked",
                },
                {
                    "label": "Kelly capped notional",
                    "formula": "min(bankroll * Kelly fraction, risk cap)",
                    "value": "waiting for score and bankroll",
                    "state": "idle",
                },
                {
                    "label": "Alpaca allocation cap",
                    "formula": "model_capital * max_portfolio_allocation_per_symbol",
                    "value": self._risk_value(
                        risk_config,
                        "alpaca",
                        "max_portfolio_allocation_per_symbol",
                    ),
                    "state": "ok",
                },
                {
                    "label": "Max Alpaca position",
                    "formula": "projected_symbol_exposure <= max_position_usd",
                    "value": self._risk_value(risk_config, "alpaca", "max_position_usd"),
                    "state": "ok",
                },
                {
                    "label": "Max Polymarket position",
                    "formula": "proposed_notional <= max_position_usd",
                    "value": self._risk_value(risk_config, "polymarket", "max_position_usd"),
                    "state": "ok",
                },
            ],
            "gates": [
                self._gate("Worker heartbeat", worker["state"] == "ok", str(worker["value"])),
                self._gate("Live flag", live_enabled, "live enabled" if live_enabled else "dry run"),
                self._gate(
                    "Selected venue",
                    selected_venue_enabled,
                    f"{selected_venue} {'enabled' if selected_venue_enabled else 'disabled'}",
                ),
                self._gate(
                    "Credentials",
                    not credential_blockers,
                    "ready" if not credential_blockers else f"{len(credential_blockers)} blocker",
                ),
                self._gate(
                    "Kill switch",
                    not kill_switch_active,
                    "inactive" if not kill_switch_active else "active",
                ),
                {
                    "label": "Market data",
                    "state": "ok" if market_data["candidateCount"] else "idle",
                    "value": market_data["status"],
                },
                {
                    "label": "Scoring",
                    "state": "idle",
                    "value": "no current prompt run",
                },
                {
                    "label": "Risk",
                    "state": "idle",
                    "value": "waiting for candidate sizing inputs",
                },
            ],
            "records": {
                "orderEvents": len(order_events),
                "openOrders": len(open_orders),
                "auditEvents": self._audit_event_count(),
            },
        }

    def _loop_status(
        self,
        *,
        worker_state: str,
        live_enabled: bool,
        selected_venue_enabled: bool,
        credential_blockers: int,
        kill_switch_active: bool,
    ) -> dict[str, str]:
        if worker_state != "ok":
            return {
                "state": "blocked",
                "label": "Worker blocked",
                "detail": "The dashboard cannot confirm a current scheduler heartbeat.",
            }
        if kill_switch_active:
            return {
                "state": "blocked",
                "label": "Stopped",
                "detail": "The kill switch is active, so live order submission is blocked.",
            }
        if not live_enabled:
            return {
                "state": "idle",
                "label": "Dry run",
                "detail": "The scheduler heartbeat is current, but live order submission is disabled.",
            }
        if not selected_venue_enabled or credential_blockers:
            return {
                "state": "blocked",
                "label": "Live gated",
                "detail": "Live mode is on, but venue or credential gates still block orders.",
            }
        return {
            "state": "waiting",
            "label": "Watching next loop",
            "detail": "Live gates are ready, but no candidate decision is currently in flight.",
        }

    def _current_loop_phase(
        self,
        *,
        worker_state: str,
        live_enabled: bool,
        selected_venue_enabled: bool,
        credential_blockers: int,
        kill_switch_active: bool,
    ) -> dict[str, str]:
        if worker_state != "ok":
            return {
                "id": "scheduler",
                "label": "Scheduler heartbeat blocked",
                "state": "blocked",
                "detail": "No current worker heartbeat is available.",
            }
        if kill_switch_active:
            return {
                "id": "execution",
                "label": "Execution stopped",
                "state": "blocked",
                "detail": "The kill switch must be cleared before any live order path can run.",
            }
        if live_enabled and (not selected_venue_enabled or credential_blockers):
            return {
                "id": "gates",
                "label": "Pre-trade gates blocked",
                "state": "blocked",
                "detail": "Resolve venue and credential blockers before live order submission.",
            }
        return {
            "id": "scheduler",
            "label": "Waiting for next scheduler tick",
            "state": "waiting",
            "detail": "The visible backend loop is currently a scheduler heartbeat.",
        }

    def _loop_stages(
        self,
        *,
        worker_state: str,
        config_degraded: bool,
        live_enabled: bool,
        selected_venue_enabled: bool,
        credential_blockers: int,
        kill_switch_active: bool,
        order_count: int,
    ) -> list[dict[str, str]]:
        return [
            {
                "id": "scheduler",
                "label": "Scheduler",
                "state": "ok" if worker_state == "ok" else "blocked",
                "detail": "Maintains the heartbeat and starts loop work when enabled.",
            },
            {
                "id": "config",
                "label": "Config snapshot",
                "state": "blocked" if config_degraded else "ok",
                "detail": "Loads venue, risk, model, symbol, and notification settings.",
            },
            {
                "id": "market-data",
                "label": "Market data",
                "state": "idle",
                "detail": "No current candidate snapshot is attached to the dashboard store.",
            },
            {
                "id": "scoring",
                "label": "LLM prompts",
                "state": "idle",
                "detail": "Scoring prompts are defined, but no prompt run is captured now.",
            },
            {
                "id": "strategy",
                "label": "Strategy logic",
                "state": "idle",
                "detail": "Strategies wait for filtered and scored candidates.",
            },
            {
                "id": "risk",
                "label": "Risk calculations",
                "state": "idle",
                "detail": "Kelly sizing and venue risk checks wait for a candidate.",
            },
            {
                "id": "execution",
                "label": "Execution",
                "state": self._execution_stage_state(
                    live_enabled=live_enabled,
                    selected_venue_enabled=selected_venue_enabled,
                    credential_blockers=credential_blockers,
                    kill_switch_active=kill_switch_active,
                ),
                "detail": "Submits dry-run or live orders only after all gates pass.",
            },
            {
                "id": "records",
                "label": "Audit and orders",
                "state": "ok" if order_count else "idle",
                "detail": "Records decisions, order events, and operator changes.",
            },
        ]

    def _execution_stage_state(
        self,
        *,
        live_enabled: bool,
        selected_venue_enabled: bool,
        credential_blockers: int,
        kill_switch_active: bool,
    ) -> str:
        if kill_switch_active or (live_enabled and (not selected_venue_enabled or credential_blockers)):
            return "blocked"
        if live_enabled:
            return "waiting"
        return "idle"

    def _llm_budget_summary(self, llm_config: dict[str, Any]) -> str:
        values = []
        for provider in ModelProvider:
            budget = llm_config.get(provider.value, {}).get("budget_usd", "0.00")
            values.append(f"{provider.value} ${budget}")
        return ", ".join(values)

    def _loop_credential_blockers(
        self,
        credentials: list[dict[str, Any]],
        selected_venue: str,
    ) -> list[dict[str, Any]]:
        required_venues = {selected_venue, "llm"}
        return [
            credential
            for credential in credentials
            if credential["requiredForLive"]
            and credential["venue"] in required_venues
            and not credential["present"]
        ]

    def _risk_value(self, risk_config: dict[str, Any], venue: str, field_name: str) -> str:
        value = risk_config.get(venue, {}).get(field_name)
        return str(value) if value is not None else "not configured"

    def _gate(self, label: str, passed: bool, value: str) -> dict[str, str]:
        return {"label": label, "state": "ok" if passed else "blocked", "value": value}

    def _audit_event_count(self) -> int:
        try:
            return len(self.registry.state.rows(f"{SHARED_SCHEMA}.audit_events"))
        except PersistenceUnavailableError:
            return 0

    def _record_market_data_pull(
        self,
        *,
        environment: Environment,
        venue: str,
        trigger: str,
        status: str,
        message: str,
        candidates: list[dict[str, Any]],
        created_at: datetime,
        run_id: str,
    ) -> dict[str, Any]:
        row = self.registry.state.insert(
            self.MARKET_DATA_PULLS_TABLE,
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "venue": venue,
                "status": status,
                "trigger": trigger,
                "source": "dashboard manual trigger",
                "candidates": candidates,
                "message": message,
                "run_id": run_id,
                "created_at": created_at,
            },
        )
        return self._market_data_payload(row)

    def _market_data_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        candidates = [_safe_candidate_payload(candidate) for candidate in row.get("candidates", [])]
        return {
            "id": row["id"],
            "environment": row["environment"],
            "venue": row["venue"],
            "status": row["status"],
            "trigger": row.get("trigger", "unknown"),
            "source": row.get("source", "dashboard store"),
            "lastPulledAt": row["created_at"].isoformat(),
            "candidateCount": len(candidates),
            "candidates": candidates,
            "message": row.get("message") or "Market data pull recorded.",
        }

    def _ai_usage_summary(
        self,
        environment: Environment,
        config_payload: dict[str, Any],
    ) -> dict[str, Any]:
        providers: list[dict[str, Any]] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = Decimal("0")
        for provider in ModelProvider:
            rows = self._ai_usage_rows(environment, provider)
            prompt_tokens = sum(_as_int(row.get("prompt_tokens")) for row in rows)
            completion_tokens = sum(_as_int(row.get("completion_tokens")) for row in rows)
            provider_cost = sum((_as_money(row.get("cost_usd", "0")) for row in rows), Decimal("0"))
            total_prompt_tokens += prompt_tokens
            total_completion_tokens += completion_tokens
            total_cost += provider_cost
            budget = config_payload.get("llm", {}).get(provider.value, {}).get("budget_usd", "0.00")
            providers.append(
                {
                    "provider": provider.value,
                    "promptTokens": prompt_tokens,
                    "completionTokens": completion_tokens,
                    "totalTokens": prompt_tokens + completion_tokens,
                    "costUsd": _money(provider_cost),
                    "budgetUsd": _money(_as_money(budget)),
                    "events": len(rows),
                }
            )
        return {
            "providers": providers,
            "promptTokens": total_prompt_tokens,
            "completionTokens": total_completion_tokens,
            "totalTokens": total_prompt_tokens + total_completion_tokens,
            "totalCostUsd": _money(total_cost),
            "source": self.AI_USAGE_EVENTS_TABLE,
        }

    def _ai_usage_rows(self, environment: Environment, provider: ModelProvider) -> list[dict[str, Any]]:
        try:
            rows = self.registry.state.rows(self.AI_USAGE_EVENTS_TABLE)
        except PersistenceUnavailableError:
            return []
        return [
            row
            for row in rows
            if row.get("environment", environment.value) == environment.value
            and row.get("provider") == provider.value
        ]

    def _trading_pnl_summary(self) -> dict[str, Any]:
        realized = Decimal("0")
        unrealized = Decimal("0")
        open_positions = 0
        closed_positions = 0
        for provider in ModelProvider:
            try:
                rows = self.registry.state.rows(f"{provider.value}.positions")
            except PersistenceUnavailableError:
                rows = []
            for row in rows:
                realized += _as_money(row.get("realized_pnl", "0"))
                unrealized += _as_money(row.get("unrealized_pnl", "0"))
                if row.get("state") == "closed":
                    closed_positions += 1
                else:
                    open_positions += 1
        total = realized + unrealized
        return {
            "realizedPnlUsd": _money(realized),
            "unrealizedPnlUsd": _money(unrealized),
            "totalPnlUsd": _money(total),
            "openPositions": open_positions,
            "closedPositions": closed_positions,
            "orderEvents": len(self.order_events()),
        }

    def order_events(self) -> list[dict[str, Any]]:
        """Return recent order events across provider schemas.

        REQ: REQ-EXE-016, REQ-OBS-005
        """

        items: list[dict[str, Any]] = []
        for provider in ModelProvider:
            table = f"{provider.value}.order_events"
            try:
                rows = self.registry.state.rows(table)
            except PersistenceUnavailableError:
                continue
            for row in rows[-50:]:
                items.append(
                    {
                        "id": row["order_id"],
                        "state": row["event_type"],
                        "venue": row["venue"],
                        "provider": row["model_provider"],
                        "createdAt": row["created_at"].isoformat(),
                        "message": row.get("message"),
                    }
                )
        items.sort(key=lambda item: item["createdAt"], reverse=True)
        return items

    def _credential_row(
        self,
        *,
        credential_id: str,
        label: str,
        venue: str,
        provider: str,
        reference: str,
        required_names: tuple[str, ...],
        public_identifier: str,
        enabled: bool,
        account_status: str = "active",
    ) -> RuntimeCredentialView:
        present = enabled and all(_configured(self.settings.runtime_env.get(name, "")) for name in required_names)
        if account_status in {"reviewing", "pending"}:
            present = False
        if not enabled:
            status = "disabled"
            message = "venue disabled"
        elif account_status in {"reviewing", "pending"}:
            status = account_status
            message = "account approval pending"
        elif present:
            status = "present"
            message = "configured"
        else:
            status = "missing"
            message = "required credential value missing"
        return RuntimeCredentialView(
            id=credential_id,
            label=label,
            venue=venue,
            provider=provider,
            public_identifier=public_identifier,
            present=present,
            reference=reference,
            status=status,
            message=message,
        )


def _configured(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip() not in PLACEHOLDER_VALUES


def _valid_email(value: str) -> bool:
    stripped = value.strip()
    if "@" not in stripped:
        return False
    local_part, domain = stripped.rsplit("@", 1)
    return bool(local_part and "." in domain)


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def default_user_preferences() -> dict[str, str]:
    """Return default dashboard preferences.

    `system` lets the browser use its own color scheme and IANA time zone.
    """

    return {
        "theme": "system",
        "timeZone": "system",
        "awsMonthlyInfraCostUsd": "0.00",
    }


def _merge_preferences(payload: dict[str, Any] | None) -> dict[str, str]:
    merged = default_user_preferences()
    if payload:
        merged.update({key: str(value) for key, value in payload.items() if key in merged})
    return _validate_user_preferences(merged)


def _validate_user_preferences(payload: dict[str, Any]) -> dict[str, str]:
    theme = str(payload.get("theme", "system")).strip().lower()
    if theme not in {"system", "light", "dark"}:
        raise ValueError("theme must be system, light, or dark")

    time_zone = str(payload.get("timeZone", "system")).strip()
    if not time_zone:
        time_zone = "system"
    if time_zone != "system":
        try:
            ZoneInfo(time_zone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timeZone must be system or a valid IANA time zone") from exc

    aws_monthly = _as_money(payload.get("awsMonthlyInfraCostUsd", "0.00"))
    if aws_monthly < 0:
        raise ValueError("awsMonthlyInfraCostUsd cannot be negative")
    return {
        "theme": theme,
        "timeZone": time_zone,
        "awsMonthlyInfraCostUsd": _money(aws_monthly),
    }


def _safe_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    pulled_at = candidate.get("pulledAt") or candidate.get("pulled_at")
    if isinstance(pulled_at, datetime):
        pulled_at = pulled_at.isoformat()
    return {
        "id": str(candidate.get("id") or candidate.get("symbol") or candidate.get("market") or "candidate"),
        "venue": str(candidate.get("venue", "")),
        "symbol": _optional_text(candidate.get("symbol")),
        "market": _optional_text(candidate.get("market")),
        "price": _optional_text(candidate.get("price")),
        "liquidity": _optional_text(candidate.get("liquidity")),
        "spread": _optional_text(candidate.get("spread")),
        "state": str(candidate.get("state", "unknown")),
        "pulledAt": _optional_text(pulled_at),
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_money(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    if not parsed.is_finite():
        return Decimal("0")
    return parsed


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _as_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
