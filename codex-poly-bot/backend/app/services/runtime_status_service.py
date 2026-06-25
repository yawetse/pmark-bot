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

from app.adapters.aws import BillingUnavailableError, billing_adapter_from_env
from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.db.schema import SHARED_SCHEMA
from app.domain import Environment, ModelProvider, Venue
from app.services.config_service import DEFAULT_ALPACA_SYMBOL_UNIVERSE
from app.services.llm_service import SCORING_SYSTEM_PROMPT
from app.services.market_data_provider import (
    MarketDataProvider,
    ProviderBackedMarketDataFetcher,
)
from app.services.stock_universe import DEFAULT_ALPACA_SYMBOL_PRESETS


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
    LEGACY_MARKET_DATA_PULLS_TABLE = f"{SHARED_SCHEMA}.market_data_pulls"
    MARKET_DATA_PULLS_TABLE = f"{SHARED_SCHEMA}.dashboard_market_data_pulls"
    PIPELINE_RUNS_TABLE = f"{SHARED_SCHEMA}.pipeline_runs"
    PIPELINE_STEPS_TABLE = f"{SHARED_SCHEMA}.pipeline_steps"
    AI_USAGE_EVENTS_TABLE = f"{SHARED_SCHEMA}.ai_usage_events"
    PIPELINE_STAGES = (
        ("data_fetch", 1, "Data Fetch"),
        ("scanner", 2, "Scanner"),
        ("brain", 3, "Reasoning / Brain"),
        ("execution", 4, "Execution"),
        ("exit", 5, "Exit"),
    )

    def __init__(
        self,
        *,
        settings: Any,
        registry: RepositoryRegistry | None = None,
        billing_adapter: Any | None = None,
        market_data_fetcher: MarketDataProvider | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry or RepositoryRegistry()
        self.billing_adapter = billing_adapter or billing_adapter_from_env(
            getattr(settings, "runtime_env", {})
        )
        self.market_data_fetcher = market_data_fetcher or ProviderBackedMarketDataFetcher(
            environ=getattr(settings, "runtime_env", {})
        )

    def runtime_config_payload(self) -> dict[str, Any]:
        """Return config defaults aligned to deployed runtime flags.

        REQ: REQ-UI-004, REQ-UI-005, REQ-EXE-001
        """

        alpaca_symbol_presets = list(
            getattr(self.settings, "alpaca_symbol_presets", DEFAULT_ALPACA_SYMBOL_PRESETS)
        )
        alpaca_custom_symbols = list(getattr(self.settings, "alpaca_custom_symbols", ()))
        alpaca_payload = {
            "account_mode": self.settings.trading_account_mode,
            "account_status": self.settings.alpaca_account_status,
            "symbol_universe": list(
                getattr(self.settings, "alpaca_symbol_universe", DEFAULT_ALPACA_SYMBOL_UNIVERSE)
            ),
        }
        if alpaca_symbol_presets or alpaca_custom_symbols:
            alpaca_payload.update(
                {
                    "symbol_presets": alpaca_symbol_presets,
                    "custom_symbols": alpaca_custom_symbols,
                    "custom_presets": {},
                }
            )

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
            "alpaca": alpaca_payload,
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
        market_data_pulls = [
            self._fetch_and_record_market_data_pull(
                environment=environment,
                venue=venue,
                trigger="manual",
                config_payload=config_payload,
                created_at=now,
                run_id=run_id,
            )
            for venue in self._market_data_venues(config_payload)
        ]
        market_data_pull = self.market_data_pull(
            environment=environment,
            config_payload=config_payload,
        )
        market_data_pull_ids = [pull["id"] for pull in market_data_pulls]
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
                    "market_data_pull_id": market_data_pull_ids[0] if market_data_pull_ids else None,
                    "market_data_pull_ids": market_data_pull_ids,
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
                "venues": [pull["venue"] for pull in market_data_pulls],
                "market_data_pull_id": market_data_pull_ids[0] if market_data_pull_ids else None,
                "market_data_pull_ids": market_data_pull_ids,
            },
        )
        pipeline_run = self._record_pipeline_run(
            environment=environment,
            run_id=run_id,
            trigger="manual",
            started_at=now,
            completed_at=now,
            market_data_pulls=market_data_pulls,
            actor=username,
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
            "marketDataPulls": market_data_pulls,
            "pipelineRun": pipeline_run,
        }

    def trigger_scheduled_run(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Run scheduled provider market-data ingestion and record the heartbeat."""

        now = datetime.now(UTC)
        run_id = str(uuid4())
        market_data_pulls = [
            self._fetch_and_record_market_data_pull(
                environment=environment,
                venue=venue,
                trigger="scheduled",
                config_payload=config_payload,
                created_at=now,
                run_id=run_id,
            )
            for venue in self._market_data_venues(config_payload)
        ]
        status = _aggregate_market_data_pull_status([pull["status"] for pull in market_data_pulls])
        try:
            self.registry.state.insert(
                f"{SHARED_SCHEMA}.job_runs",
                {
                    "id": run_id,
                    "job_name": self.WORKER_JOB_NAME,
                    "status": status,
                    "heartbeat_at": now,
                    "metadata": {
                        "message": "scheduled provider market data ingestion",
                        "scheduled": True,
                        "market_data_pull_ids": [pull["id"] for pull in market_data_pulls],
                        "venues": [pull["venue"] for pull in market_data_pulls],
                    },
                    "created_at": now,
                },
            )
        except PersistenceUnavailableError:
            pass
        pipeline_run = self._record_pipeline_run(
            environment=environment,
            run_id=run_id,
            trigger="scheduled",
            started_at=now,
            completed_at=now,
            market_data_pulls=market_data_pulls,
            actor="scheduler",
        )
        return {
            "environment": environment.value,
            "runId": run_id,
            "status": status,
            "triggeredAt": now.isoformat(),
            "marketDataPull": self.market_data_pull(
                environment=environment,
                config_payload=config_payload,
            ),
            "marketDataPulls": market_data_pulls,
            "pipelineRun": pipeline_run,
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
            "pipelineRuns": self.pipeline_runs(environment),
        }

    def pipeline_runs(self, environment: Environment, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent loop runs with the user-visible processing stages.

        REQ: REQ-UI-008, REQ-DAT-008, REQ-OBS-005
        """

        try:
            rows = [
                row
                for row in self.registry.state.rows(self.PIPELINE_RUNS_TABLE)
                if row["environment"] == environment.value
            ]
            step_rows = [
                row
                for row in self.registry.state.rows(self.PIPELINE_STEPS_TABLE)
                if row["environment"] == environment.value
            ]
        except PersistenceUnavailableError:
            return []
        rows.sort(key=lambda row: row.get("started_at") or row.get("created_at"), reverse=True)
        payloads = []
        for row in rows[: max(1, limit)]:
            steps = [
                step
                for step in step_rows
                if step.get("run_id") == row["id"]
            ]
            steps.sort(key=lambda step: step.get("step_order", 0))
            payloads.append(self._pipeline_run_payload(row, steps))
        return payloads

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
            rows = self._market_data_rows(environment)
        except PersistenceUnavailableError:
            rows = []
        return self._market_data_summary_payload(
            environment=environment,
            config_payload=config_payload,
            rows=rows,
            selected_venue=selected_venue,
        )

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
        aws_cost = self._aws_cost_summary(environment=environment, preferences=preferences)
        daily_aws = _as_money(aws_cost["dailyInfraCostEstimateUsd"])
        recorded_costs = _as_money(ai_usage["totalCostUsd"]) + daily_aws
        trading_total = _as_money(trading["totalPnlUsd"])
        net = trading_total - recorded_costs
        return {
            "environment": environment.value,
            "generatedAt": datetime.now(UTC).isoformat(),
            "trading": trading,
            "ai": ai_usage,
            "aws": aws_cost,
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

    def _record_pipeline_run(
        self,
        *,
        environment: Environment,
        run_id: str,
        trigger: str,
        started_at: datetime,
        completed_at: datetime,
        market_data_pulls: list[dict[str, Any]],
        actor: str,
    ) -> dict[str, Any]:
        pull_status = _aggregate_market_data_pull_status([pull["status"] for pull in market_data_pulls])
        candidate_count = sum(_as_int(pull.get("candidateCount")) for pull in market_data_pulls)
        pipeline_status = _pipeline_run_status(pull_status)
        venue_names = [pull["venue"] for pull in market_data_pulls]
        run_row = {
            "id": run_id,
            "environment": environment.value,
            "trigger": trigger,
            "status": pipeline_status,
            "started_at": started_at,
            "completed_at": completed_at,
            "metadata": {
                "actor": actor,
                "marketDataStatus": pull_status,
                "candidateCount": candidate_count,
                "venues": venue_names,
            },
            "created_at": completed_at,
        }
        step_rows = self._pipeline_step_rows(
            environment=environment,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            market_data_pulls=market_data_pulls,
            candidate_count=candidate_count,
            market_data_status=pull_status,
        )
        try:
            self.registry.state.insert(self.PIPELINE_RUNS_TABLE, run_row)
            for step_row in step_rows:
                self.registry.state.insert(self.PIPELINE_STEPS_TABLE, step_row)
        except PersistenceUnavailableError:
            return self._pipeline_run_payload(run_row, step_rows)
        return self._pipeline_run_payload(run_row, step_rows)

    def _pipeline_step_rows(
        self,
        *,
        environment: Environment,
        run_id: str,
        started_at: datetime,
        completed_at: datetime,
        market_data_pulls: list[dict[str, Any]],
        candidate_count: int,
        market_data_status: str,
    ) -> list[dict[str, Any]]:
        pull_ids = [pull["id"] for pull in market_data_pulls if pull.get("id")]
        venue_names = [pull["venue"] for pull in market_data_pulls]
        first_message = next((pull["message"] for pull in market_data_pulls if pull.get("message")), "")
        data_fetch_message = (
            f"Fetched {candidate_count} priced candidate"
            f"{'' if candidate_count == 1 else 's'} across {len(venue_names)} venue"
            f"{'' if len(venue_names) == 1 else 's'}."
            if candidate_count
            else first_message or "No enabled provider venues were selected for this run."
        )
        scanner_status = "completed" if candidate_count else (
            "blocked" if market_data_status in {"failed", "rate_limited"} else "waiting"
        )
        scanner_message = (
            f"Scanner has {candidate_count} priced candidate"
            f"{'' if candidate_count == 1 else 's'} ready for downstream filters."
            if candidate_count
            else "No priced candidates reached the scanner from provider data."
        )
        stage_payloads = {
            "data_fetch": {
                "status": _pipeline_data_fetch_status(market_data_status),
                "message": data_fetch_message,
                "metrics": {
                    "candidateCount": candidate_count,
                    "venueCount": len(venue_names),
                    "marketDataStatus": market_data_status,
                },
                "record_ids": pull_ids,
            },
            "scanner": {
                "status": scanner_status,
                "message": scanner_message,
                "metrics": {"candidateCount": candidate_count},
                "record_ids": pull_ids,
            },
            "brain": {
                "status": "waiting",
                "message": "Reasoning is waiting for scanner-to-LLM orchestration.",
                "metrics": {"promptCount": 0},
                "record_ids": [],
            },
            "execution": {
                "status": "waiting",
                "message": "Execution is waiting for scored strategy decisions and risk approval.",
                "metrics": {"orderIntentCount": 0},
                "record_ids": [],
            },
            "exit": {
                "status": "waiting",
                "message": "Exit checks are waiting for open-position monitoring.",
                "metrics": {"openPositionCount": 0},
                "record_ids": [],
            },
        }
        rows = []
        for key, order, label in self.PIPELINE_STAGES:
            payload = stage_payloads[key]
            rows.append(
                {
                    "id": f"{run_id}:{key}",
                    "run_id": run_id,
                    "environment": environment.value,
                    "step_key": key,
                    "step_order": order,
                    "label": label,
                    "status": payload["status"],
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "message": payload["message"],
                    "metrics": payload["metrics"],
                    "record_ids": payload["record_ids"],
                    "created_at": completed_at,
                }
            )
        return rows

    def _pipeline_run_payload(
        self,
        row: dict[str, Any],
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": row["id"],
            "environment": row["environment"],
            "trigger": row["trigger"],
            "status": row["status"],
            "startedAt": _isoformat_or_none(row.get("started_at")),
            "completedAt": _isoformat_or_none(row.get("completed_at")),
            "metadata": row.get("metadata", {}),
            "steps": [
                {
                    "id": step["id"],
                    "key": step["step_key"],
                    "order": step["step_order"],
                    "label": step["label"],
                    "status": step["status"],
                    "startedAt": _isoformat_or_none(step.get("started_at")),
                    "completedAt": _isoformat_or_none(step.get("completed_at")),
                    "message": step.get("message"),
                    "metrics": step.get("metrics", {}),
                    "recordIds": step.get("record_ids", []),
                }
                for step in steps
            ],
        }

    def _fetch_and_record_market_data_pull(
        self,
        *,
        environment: Environment,
        venue: str,
        trigger: str,
        config_payload: dict[str, Any],
        created_at: datetime,
        run_id: str,
    ) -> dict[str, Any]:
        result = self.market_data_fetcher.fetch(
            venue=venue,
            config_payload=config_payload,
            pulled_at=created_at,
        )
        return self._record_market_data_pull(
            environment=environment,
            venue=venue,
            trigger=trigger,
            status=result.status,
            source=result.source,
            message=result.message,
            candidates=result.candidates,
            error_code=result.error_code,
            created_at=created_at,
            run_id=run_id,
        )

    def _record_market_data_pull(
        self,
        *,
        environment: Environment,
        venue: str,
        trigger: str,
        status: str,
        source: str,
        message: str,
        candidates: list[dict[str, Any]],
        error_code: str | None,
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
                "source": source,
                "candidates": candidates,
                "message": message,
                "error_code": error_code,
                "run_id": run_id,
                "created_at": created_at,
            },
        )
        return self._market_data_payload(row)

    def _market_data_rows(self, environment: Environment) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.registry.state.rows(self.MARKET_DATA_PULLS_TABLE)
            if row["environment"] == environment.value
        ]
        if rows:
            return rows
        return [
            row
            for row in self.registry.state.rows(self.LEGACY_MARKET_DATA_PULLS_TABLE)
            if row["environment"] == environment.value
        ]

    def _market_data_venues(self, config_payload: dict[str, Any]) -> list[str]:
        selected_venue = str(
            config_payload.get("default_selected_venue")
            or self.settings.default_selected_venue.value
        )
        supported = [
            Venue.POLYMARKET_US.value,
            Venue.POLYMARKET_INTERNATIONAL.value,
            Venue.ALPACA.value,
        ]
        enabled = [venue for venue in supported if self._venue_enabled(venue, config_payload)]
        if not enabled:
            return [selected_venue] if selected_venue else [Venue.POLYMARKET_US.value]
        ordered = []
        for venue in [selected_venue, *supported]:
            if venue in enabled and venue not in ordered:
                ordered.append(venue)
        return ordered

    def _venue_enabled(self, venue: str, config_payload: dict[str, Any]) -> bool:
        venues = config_payload.get("venues", {})
        if isinstance(venues, dict) and venue in venues:
            venue_config = venues.get(venue)
            if isinstance(venue_config, dict):
                return bool(venue_config.get("enabled", False))
        if venue == Venue.POLYMARKET_US.value:
            return bool(self.settings.polymarket_us_enabled)
        if venue == Venue.POLYMARKET_INTERNATIONAL.value:
            return bool(self.settings.polymarket_international_enabled)
        if venue == Venue.ALPACA.value:
            return bool(self.settings.alpaca_enabled)
        return False

    def _market_data_summary_payload(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        rows: list[dict[str, Any]],
        selected_venue: str,
    ) -> dict[str, Any]:
        venues = self._market_data_venues(config_payload)
        venue_payloads = []
        for venue in venues:
            venue_rows = [row for row in rows if row["venue"] == venue]
            if venue_rows:
                venue_payloads.append(self._market_data_payload(max(venue_rows, key=lambda row: row["created_at"])))
            else:
                venue_payloads.append(
                    self._empty_market_data_payload(
                        environment=environment,
                        venue=venue,
                        message=f"No market data pull has been recorded for {venue}.",
                    )
                )

        rows_for_enabled_venues = [row for row in rows if row["venue"] in venues]
        latest = max(rows_for_enabled_venues, key=lambda row: row["created_at"]) if rows_for_enabled_venues else None
        if latest is None:
            summary = self._empty_market_data_payload(
                environment=environment,
                venue=selected_venue,
                message="No market data pull has been recorded in the dashboard store.",
            )
        else:
            summary = self._market_data_payload(latest)
            summary["message"] = (
                f"Latest market data pull records are shown for {len(venue_payloads)} enabled venue"
                f"{'' if len(venue_payloads) == 1 else 's'}."
            )

        all_candidates = [
            candidate
            for venue_payload in venue_payloads
            for candidate in venue_payload["candidates"]
        ]
        summary["status"] = _aggregate_market_data_pull_status(
            [venue_payload["status"] for venue_payload in venue_payloads]
        )
        summary["candidateCount"] = len(all_candidates)
        summary["candidates"] = all_candidates
        summary["venues"] = venue_payloads
        return summary

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
            "errorCode": row.get("error_code"),
        }

    def _empty_market_data_payload(
        self,
        *,
        environment: Environment,
        venue: str,
        message: str,
    ) -> dict[str, Any]:
        return {
            "id": None,
            "environment": environment.value,
            "venue": venue,
            "status": "idle",
            "trigger": "none",
            "source": "dashboard store",
            "lastPulledAt": None,
            "candidateCount": 0,
            "candidates": [],
            "message": message,
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

    def _aws_cost_summary(
        self,
        *,
        environment: Environment,
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        monthly_fallback = _as_money(preferences.get("awsMonthlyInfraCostUsd", "0.00"))
        daily_fallback = monthly_fallback / Decimal("30")
        if self.billing_adapter is not None:
            try:
                billing = self.billing_adapter.dashboard_costs(environment=environment)
            except BillingUnavailableError as exc:
                return _aws_fallback_payload(
                    monthly_fallback=monthly_fallback,
                    daily_fallback=daily_fallback,
                    message=f"AWS Cost Explorer unavailable; using saved fallback. {exc}",
                )
            return {
                "monthlyInfraCostUsd": _money(billing.month_to_date_cost_usd),
                "monthToDateCostUsd": _money(billing.month_to_date_cost_usd),
                "dailyInfraCostEstimateUsd": _money(billing.daily_cost_usd),
                "dailyInfraCostUsd": _money(billing.daily_cost_usd),
                "fallbackMonthlyCostUsd": _money(monthly_fallback),
                "fallbackDailyCostUsd": _money(daily_fallback),
                "source": billing.source,
                "scope": billing.scope,
                "periodStart": billing.daily_start.isoformat(),
                "periodEnd": billing.daily_end.isoformat(),
                "monthPeriodStart": billing.month_start.isoformat(),
                "monthPeriodEnd": billing.month_end.isoformat(),
                "estimated": billing.estimated,
                "message": billing.message,
            }
        return _aws_fallback_payload(
            monthly_fallback=monthly_fallback,
            daily_fallback=daily_fallback,
            message="AWS Cost Explorer is not enabled for this runtime; using saved fallback.",
        )

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

    def model_summary(
        self,
        *,
        provider: ModelProvider,
        environment: Environment,
        config_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Return provider schema rows for dashboard data grids."""

        positions = self._model_positions(provider)
        decisions = self._model_trade_decisions(provider, environment)
        orders = self._model_order_events(provider)
        usage_rows = self._ai_usage_rows(environment, provider)
        used = sum((_as_money(row.get("cost_usd", "0")) for row in usage_rows), Decimal("0"))
        budget = config_payload.get("llm", {}).get(provider.value, {}).get("budget_usd", "0.00")
        pnl = sum(
            (
                _as_money(row.get("realizedPnlUsd", "0"))
                + _as_money(row.get("unrealizedPnlUsd", "0"))
                for row in positions
            ),
            Decimal("0"),
        )
        return {
            "provider": provider.value,
            "positions": positions,
            "decisions": decisions,
            "orders": orders,
            "budget": {"used_usd": _money(used), "limit_usd": _money(_as_money(budget))},
            "pnl": _money(pnl),
            "degraded_sections": [],
        }

    def _model_positions(self, provider: ModelProvider) -> list[dict[str, Any]]:
        try:
            rows = self.registry.state.rows(f"{provider.value}.positions")
        except PersistenceUnavailableError:
            return []
        items = [
            {
                "positionId": str(row.get("position_id", "")),
                "state": str(row.get("state", "unknown")),
                "realizedPnlUsd": _money(_as_money(row.get("realized_pnl", "0"))),
                "unrealizedPnlUsd": _money(_as_money(row.get("unrealized_pnl", "0"))),
                "updatedAt": _isoformat_or_none(row.get("updated_at")),
            }
            for row in rows[-50:]
        ]
        items.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)
        return items

    def _model_trade_decisions(
        self,
        provider: ModelProvider,
        environment: Environment,
    ) -> list[dict[str, Any]]:
        try:
            rows = self.registry.state.rows(f"{provider.value}.trade_decisions")
        except PersistenceUnavailableError:
            return []
        items = []
        for row in rows[-50:]:
            if row.get("environment", environment.value) != environment.value:
                continue
            items.append(
                {
                    "id": str(row.get("id", "")),
                    "venue": str(row.get("venue", "")),
                    "instrument": str(row.get("instrument_identifier", "")),
                    "instrumentType": str(row.get("instrument_type", "")),
                    "decision": str(row.get("decision", "")),
                    "orderType": str(row.get("order_type", "")),
                    "size": str(row.get("size", "")),
                    "createdAt": _isoformat_or_none(row.get("created_at")),
                }
            )
        items.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
        return items

    def _model_order_events(self, provider: ModelProvider) -> list[dict[str, Any]]:
        try:
            rows = self.registry.state.rows(f"{provider.value}.order_events")
        except PersistenceUnavailableError:
            return []
        items = [
            {
                "id": str(row.get("order_id", row.get("id", ""))),
                "state": str(row.get("event_type", "unknown")),
                "venue": str(row.get("venue", "")),
                "provider": str(row.get("model_provider", provider.value)),
                "message": str(row.get("message", "")),
                "createdAt": _isoformat_or_none(row.get("created_at")),
            }
            for row in rows[-50:]
        ]
        items.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
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


def _aws_fallback_payload(
    *,
    monthly_fallback: Decimal,
    daily_fallback: Decimal,
    message: str,
) -> dict[str, Any]:
    return {
        "monthlyInfraCostUsd": _money(monthly_fallback),
        "monthToDateCostUsd": _money(monthly_fallback),
        "dailyInfraCostEstimateUsd": _money(daily_fallback),
        "dailyInfraCostUsd": _money(daily_fallback),
        "fallbackMonthlyCostUsd": _money(monthly_fallback),
        "fallbackDailyCostUsd": _money(daily_fallback),
        "source": "user preference fallback",
        "scope": "fallback",
        "periodStart": None,
        "periodEnd": None,
        "monthPeriodStart": None,
        "monthPeriodEnd": None,
        "estimated": True,
        "message": message,
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
        "dataSource": _optional_text(candidate.get("dataSource")),
        "historyBarCount": _as_int(candidate.get("historyBarCount")),
        "previousClose": _optional_text(candidate.get("previousClose")),
        "historyStart": _optional_text(candidate.get("historyStart")),
        "historyEnd": _optional_text(candidate.get("historyEnd")),
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _isoformat_or_none(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _aggregate_market_data_pull_status(statuses: list[str]) -> str:
    if not statuses:
        return "empty"
    pulled = any(status == "pulled" for status in statuses)
    partial = any(status == "partial" for status in statuses)
    failed = any(status == "failed" for status in statuses)
    rate_limited = any(status == "rate_limited" for status in statuses)
    if partial or (pulled and (failed or rate_limited)):
        return "partial"
    if failed:
        return "failed"
    if rate_limited:
        return "rate_limited"
    if pulled:
        return "pulled"
    return "empty"


def _pipeline_data_fetch_status(market_data_status: str) -> str:
    if market_data_status == "pulled":
        return "completed"
    if market_data_status == "partial":
        return "partial"
    if market_data_status in {"failed", "rate_limited"}:
        return "blocked"
    return "waiting"


def _pipeline_run_status(market_data_status: str) -> str:
    if market_data_status == "pulled":
        return "accepted"
    if market_data_status == "partial":
        return "partial"
    if market_data_status in {"failed", "rate_limited"}:
        return "blocked"
    return "waiting"


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
