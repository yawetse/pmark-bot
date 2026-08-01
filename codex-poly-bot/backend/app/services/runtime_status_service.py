"""Runtime readiness and dashboard status helpers.

REQ: REQ-UI-004, REQ-UI-009, REQ-NOT-006, REQ-DAT-008,
REQ-WAL-005, REQ-WAL-006, REQ-OBS-005, REQ-DB-008, REQ-UI-013,
REQ-UI-014, REQ-CMP-005
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.adapters.aws import (
    BillingUnavailableError,
    EmailMessage,
    billing_adapter_from_env,
    ses_adapter_from_env,
)
from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.db.schema import SHARED_SCHEMA
from app.domain import Environment, ModelProvider, Venue
from app.services.config_service import DEFAULT_ALPACA_SYMBOL_UNIVERSE, DEFAULT_FUNDING_CONFIG
from app.services.llm_service import SCORING_SYSTEM_PROMPT
from app.services.tick_summary_service import (
    DEFAULT_TICK_SUMMARY_CACHE_SECONDS,
    DEFAULT_TICK_SUMMARY_WINDOW_MINUTES,
    TickSummaryRequest,
    TickSummaryService,
)
from app.services.ai_usage_import_service import (
    AiUsageImportService,
    ProviderBackedAiUsageImportSource,
)
from app.services.market_data_provider import (
    MarketDataProvider,
    ProviderBackedMarketDataFetcher,
)
from app.services.scanner_service import (
    DEFAULT_SCANNER_CONFIG,
    ScannerRunResult,
    ScannerService,
    scanner_run_payload,
)
from app.services.brain_service import (
    BrainService,
    DEFAULT_REASONING_CONFIG,
    ReasoningRunResult,
    reasoning_run_payload,
)
from app.services.strategy_consensus_service import (
    DEFAULT_STRATEGY_CONSENSUS_CONFIG,
    StrategyConsensusRunResult,
    StrategyConsensusService,
    strategy_consensus_run_payload,
)
from app.services.lifecycle_service import (
    DEFAULT_EXECUTION_CONFIG,
    DEFAULT_EXIT_CONFIG,
    LifecycleRunResult,
    PipelineLifecycleService,
    execution_run_payload,
    exit_run_payload,
)
from app.services.notification_service import (
    NotificationDeliveryLedger,
    NotificationDeliveryRecord,
    NotificationSettings,
)
from app.services.wallet_service import CredentialTarget, resolve_credential_ref
from app.services.stock_universe import (
    DEFAULT_ALPACA_PRESET_REFRESH_CONFIG,
    DEFAULT_ALPACA_SYMBOL_PRESETS,
    normalize_symbol_list,
    resolve_alpaca_symbol_universe,
    seed_alpaca_preset_snapshots,
    stock_universe_metadata,
)
from app.services.stock_universe_refresh_service import (
    StockUniverseRefreshService,
    latest_preset_snapshot_payloads,
)
from app.services.venue_portfolio_service import (
    ProviderBackedVenuePortfolioSource,
    VenuePortfolioService,
    VenuePortfolioSource,
)
from app.venues import (
    alpaca_live_order_adapter_from_env,
    polymarket_us_live_adapter_from_env,
)


PLACEHOLDER_VALUES = {"", "change-me", "set-locally", "optional-in-dry-run"}
TRADING_MODEL_PROVIDERS = (ModelProvider.OPENAI, ModelProvider.CLAUDE)
MANUAL_NON_LIVE_POLYMARKET_MARKET_DATA_LIMIT = 10
MANUAL_NON_LIVE_ALPACA_SYMBOL_LIMIT = 20
DASHBOARD_DATA_EXPLORER_ROW_LIMIT = 500
DASHBOARD_PIPELINE_RUN_ROW_LIMIT = 250
DASHBOARD_PIPELINE_STEP_ROW_LIMIT = 1_250
DASHBOARD_PIPELINE_RECORD_ROW_LIMIT = 1_000
DASHBOARD_TICK_SUMMARY_ROW_LIMIT = 100
DASHBOARD_REASONING_OUTPUT_ROW_LIMIT = 100
DASHBOARD_STRATEGY_VOTE_ROW_LIMIT = 200
DASHBOARD_STRATEGY_OUTPUT_ROW_LIMIT = 100
DASHBOARD_EXECUTION_INTENT_ROW_LIMIT = 100
DASHBOARD_EXIT_INTENT_ROW_LIMIT = 100
DASHBOARD_AI_USAGE_ROW_LIMIT = 2_000
DASHBOARD_AI_USAGE_IMPORT_ROW_LIMIT = 250
DASHBOARD_ECONOMICS_SNAPSHOT_ROW_LIMIT = 400
DASHBOARD_ECONOMICS_SNAPSHOT_MIN_INTERVAL_SECONDS = 300
DASHBOARD_PNL_POSITION_ROW_LIMIT = 500
DASHBOARD_ORDER_EVENT_ROW_LIMIT = 50
DASHBOARD_ORDER_HISTORY_PAGE_SIZE = 100
DASHBOARD_ORDER_HISTORY_ROW_LIMIT = 500
CURRENT_WORKER_HEARTBEAT_STATUSES = {
    "ok",
    "accepted",
    "running",
    "pulled",
    "partial",
    "rate_limited",
    "empty",
}

DATA_EXPLORER_DATASETS: dict[str, dict[str, Any]] = {
    "market_data_pulls": {
        "table": f"{SHARED_SCHEMA}.dashboard_market_data_pulls",
        "label": "Market data pulls",
        "description": "Provider data captured before scanner filtering.",
        "columns": (
            "id",
            "environment",
            "venue",
            "status",
            "trigger",
            "source",
            "candidate_count",
            "message",
            "error_code",
            "run_id",
            "created_at",
        ),
    },
    "pipeline_runs": {
        "table": f"{SHARED_SCHEMA}.pipeline_runs",
        "label": "Pipeline runs",
        "description": "Manual and scheduled ticks.",
        "columns": ("id", "environment", "trigger", "status", "started_at", "completed_at"),
    },
    "pipeline_steps": {
        "table": f"{SHARED_SCHEMA}.pipeline_steps",
        "label": "Pipeline steps",
        "description": "Five-step trace records for each tick.",
        "columns": ("id", "run_id", "step_key", "step_order", "label", "status", "message", "created_at"),
    },
    "scanner_candidates": {
        "table": f"{SHARED_SCHEMA}.scanner_candidates",
        "label": "Scanner candidates",
        "description": "Accepted and rejected scanner candidates.",
        "columns": (
            "id",
            "scanner_run_id",
            "venue",
            "instrument_id",
            "display_name",
            "status",
            "refusal_reason",
            "price",
            "liquidity",
            "spread",
            "hours_to_resolution",
            "created_at",
        ),
    },
    "reasoning_outputs": {
        "table": f"{SHARED_SCHEMA}.reasoning_outputs",
        "label": "Reasoning outputs",
        "description": "Model scoring output for accepted scanner candidates.",
        "columns": (
            "id",
            "reasoning_run_id",
            "scanner_candidate_id",
            "venue",
            "instrument_id",
            "model_provider",
            "status",
            "refusal_reason",
            "confidence",
            "estimated_probability",
            "cost_usd",
            "created_at",
        ),
    },
    "strategy_votes": {
        "table": f"{SHARED_SCHEMA}.strategy_votes",
        "label": "Strategy votes",
        "description": "Strategy consensus votes before order sizing.",
        "columns": (
            "id",
            "consensus_run_id",
            "reasoning_output_id",
            "scanner_candidate_id",
            "venue",
            "instrument_id",
            "model_provider",
            "strategy_name",
            "status",
            "refusal_reason",
            "created_at",
        ),
    },
    "strategy_outputs": {
        "table": f"{SHARED_SCHEMA}.strategy_consensus_outputs",
        "label": "Strategy outputs",
        "description": "Approved or refused consensus outputs.",
        "columns": (
            "id",
            "consensus_run_id",
            "venue",
            "instrument_id",
            "model_provider",
            "status",
            "side",
            "size_multiplier",
            "signal_count",
            "refusal_reason",
            "created_at",
        ),
    },
    "order_intents": {
        "table": f"{SHARED_SCHEMA}.order_intents",
        "label": "Order intents",
        "description": "Risk-checked order intents from the execution step.",
        "columns": (
            "id",
            "execution_run_id",
            "pipeline_run_id",
            "venue",
            "instrument_id",
            "model_provider",
            "side",
            "status",
            "notional_usd",
            "refusal_reason",
            "created_at",
        ),
    },
    "exit_intents": {
        "table": f"{SHARED_SCHEMA}.exit_intents",
        "label": "Exit intents",
        "description": "Exit monitor decisions for open positions.",
        "columns": (
            "id",
            "exit_run_id",
            "pipeline_run_id",
            "venue",
            "instrument_id",
            "position_id",
            "trigger_type",
            "status",
            "refusal_reason",
            "created_at",
        ),
    },
    "tick_summaries": {
        "table": f"{SHARED_SCHEMA}.tick_summaries",
        "label": "Tick summaries",
        "description": "Cached AI or local summaries of recent ticks.",
        "columns": (
            "id",
            "environment",
            "window_minutes",
            "latest_run_id",
            "run_count",
            "status",
            "model",
            "message",
            "created_at",
        ),
    },
}


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
    MARKET_DATA_DASHBOARD_CANDIDATE_LIMIT = 50
    PIPELINE_RUNS_TABLE = f"{SHARED_SCHEMA}.pipeline_runs"
    PIPELINE_STEPS_TABLE = f"{SHARED_SCHEMA}.pipeline_steps"
    TICK_SUMMARIES_TABLE = f"{SHARED_SCHEMA}.tick_summaries"
    SCANNER_RUNS_TABLE = f"{SHARED_SCHEMA}.scanner_runs"
    SCANNER_CANDIDATES_TABLE = f"{SHARED_SCHEMA}.scanner_candidates"
    REASONING_RUNS_TABLE = f"{SHARED_SCHEMA}.reasoning_runs"
    REASONING_OUTPUTS_TABLE = f"{SHARED_SCHEMA}.reasoning_outputs"
    STRATEGY_CONSENSUS_RUNS_TABLE = f"{SHARED_SCHEMA}.strategy_consensus_runs"
    STRATEGY_VOTES_TABLE = f"{SHARED_SCHEMA}.strategy_votes"
    STRATEGY_CONSENSUS_OUTPUTS_TABLE = f"{SHARED_SCHEMA}.strategy_consensus_outputs"
    EXECUTION_RUNS_TABLE = f"{SHARED_SCHEMA}.execution_runs"
    ORDER_INTENTS_TABLE = f"{SHARED_SCHEMA}.order_intents"
    EXIT_RUNS_TABLE = f"{SHARED_SCHEMA}.exit_runs"
    EXIT_INTENTS_TABLE = f"{SHARED_SCHEMA}.exit_intents"
    AI_USAGE_EVENTS_TABLE = f"{SHARED_SCHEMA}.ai_usage_events"
    AI_USAGE_IMPORT_RUNS_TABLE = f"{SHARED_SCHEMA}.ai_usage_import_runs"
    ECONOMICS_SNAPSHOTS_TABLE = f"{SHARED_SCHEMA}.economics_snapshots"
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
        stock_universe_refresher: StockUniverseRefreshService | None = None,
        ai_usage_importer: AiUsageImportService | None = None,
        venue_portfolio_source: VenuePortfolioSource | None = None,
        alpaca_submitter: Any | None = None,
        polymarket_submitter: Any | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry or RepositoryRegistry()
        self.billing_adapter = billing_adapter or billing_adapter_from_env(
            getattr(settings, "runtime_env", {})
        )
        self.market_data_fetcher = market_data_fetcher or ProviderBackedMarketDataFetcher(
            environ=getattr(settings, "runtime_env", {})
        )
        self.scanner = ScannerService(self.registry)
        self.brain = BrainService(
            self.registry,
            environ=getattr(settings, "runtime_env", {}),
        )
        self.strategy_consensus = StrategyConsensusService(self.registry)
        resolved_alpaca_submitters = (
            {provider: alpaca_submitter for provider in TRADING_MODEL_PROVIDERS}
            if alpaca_submitter is not None
            else _alpaca_submitters_from_settings(settings)
        )
        resolved_polymarket_submitters = (
            {provider: polymarket_submitter for provider in TRADING_MODEL_PROVIDERS}
            if polymarket_submitter is not None
            else _polymarket_submitters_from_settings(settings)
        )
        resolved_alpaca_submitter = _first_submitter(resolved_alpaca_submitters)
        resolved_polymarket_submitter = _first_submitter(resolved_polymarket_submitters)
        self.notification_ledger = NotificationDeliveryLedger()
        self.lifecycle = PipelineLifecycleService(
            self.registry,
            alpaca_submitter=resolved_alpaca_submitter,
            alpaca_submitters=resolved_alpaca_submitters,
            alpaca_exit_submitter=resolved_alpaca_submitter,
            polymarket_submitter=resolved_polymarket_submitter,
            polymarket_submitters=resolved_polymarket_submitters,
            polymarket_position_closer=resolved_polymarket_submitter,
            notification_adapter=ses_adapter_from_env(
                getattr(settings, "runtime_env", {}),
                source=getattr(settings, "ses_identity_email", ""),
            ),
            notification_ledger=self.notification_ledger,
        )
        self.stock_universe_refresher = stock_universe_refresher or StockUniverseRefreshService(
            self.registry
        )
        self.ai_usage_importer = ai_usage_importer or AiUsageImportService(
            self.registry,
            source=ProviderBackedAiUsageImportSource(getattr(settings, "runtime_env", {})),
        )
        self.venue_portfolio = VenuePortfolioService(
            self.registry,
            source=venue_portfolio_source
            or ProviderBackedVenuePortfolioSource(
                getattr(settings, "runtime_env", {}),
                registry=self.registry,
            ),
        )

    def refresh_venue_portfolio(self, environment: Environment) -> dict[str, Any]:
        """Refresh sanitized account positions and confirmed fills from each venue.

        REQ: REQ-DB-008, REQ-UI-013, REQ-CMP-005
        """

        return self.venue_portfolio.refresh(environment)

    def venue_portfolio_summary(self, environment: Environment) -> dict[str, Any]:
        """Return venue-confirmed portfolio performance for the dashboard.

        REQ: REQ-UI-013, REQ-CMP-005
        """

        return self.venue_portfolio.summary(environment)

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
            "allow_shorting": False,
            "symbol_universe": list(
                getattr(self.settings, "alpaca_symbol_universe", DEFAULT_ALPACA_SYMBOL_UNIVERSE)
            ),
            "preset_refresh": DEFAULT_ALPACA_PRESET_REFRESH_CONFIG,
            "preset_snapshots": self._latest_preset_snapshot_payloads(self.settings.environment),
        }
        if alpaca_symbol_presets or alpaca_custom_symbols:
            alpaca_payload.update(
                {
                    "symbol_presets": alpaca_symbol_presets,
                    "custom_symbols": alpaca_custom_symbols,
                    "custom_presets": {},
                }
            )

        payload = {
            "default_selected_venue": self.settings.default_selected_venue.value,
            "trading_profile": "active_stock_day_trader",
            "live_enabled": self.settings.live_enabled,
            "venues": {
                Venue.POLYMARKET_US.value: {"enabled": self.settings.polymarket_us_enabled},
                Venue.POLYMARKET_INTERNATIONAL.value: {
                    "enabled": self.settings.polymarket_international_enabled
                },
                Venue.ALPACA.value: {"enabled": self.settings.alpaca_enabled},
            },
            "trading_loop_interval_seconds": 900,
            "strategies": {
                "arbitrage": {"enabled": True, "settings": {}},
                "convergence": {"enabled": True, "settings": {}},
                "whale_copy": {"enabled": True, "settings": {}},
            },
            "llm": {
                ModelProvider.CLAUDE.value: {
                    "budget_usd": "20.00",
                    "settings": {"budget_window_hours": 24},
                },
                ModelProvider.OPENAI.value: {
                    "budget_usd": "20.00",
                    "settings": {"budget_window_hours": 24},
                },
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
            "scanner": DEFAULT_SCANNER_CONFIG,
            "reasoning": DEFAULT_REASONING_CONFIG,
            "strategy_consensus": DEFAULT_STRATEGY_CONSENSUS_CONFIG,
            "execution": DEFAULT_EXECUTION_CONFIG,
            "exit": DEFAULT_EXIT_CONFIG,
            "historical_import": {
                "polymarket": _polymarket_historical_import_config(self.settings),
            },
            "alpaca": alpaca_payload,
            "notifications": {
                "recipients": self.settings.notification_recipients,
                "thresholds": {},
                "cooldown_seconds": 1800,
                "digest_schedule_utc": "13:00",
                "ses_identity": self.settings.ses_identity_email,
                "email_on_trade_placed": True,
            },
            "funding": deepcopy(DEFAULT_FUNDING_CONFIG),
        }
        if "symbol_presets" in alpaca_payload or "custom_symbols" in alpaca_payload:
            alpaca_payload["symbol_universe"] = resolve_alpaca_symbol_universe(payload)
        alpaca_payload["preset_metadata"] = stock_universe_metadata(payload)
        return payload

    def _with_latest_stock_universe(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload = deepcopy(config_payload)
        alpaca_payload = payload.setdefault("alpaca", {})
        if not isinstance(alpaca_payload, dict):
            return payload
        refresh_config = alpaca_payload.get("preset_refresh")
        sources = {}
        if isinstance(refresh_config, dict) and isinstance(refresh_config.get("sources"), dict):
            sources = refresh_config["sources"]
        alpaca_payload["preset_refresh"] = {
            **DEFAULT_ALPACA_PRESET_REFRESH_CONFIG,
            **(refresh_config if isinstance(refresh_config, dict) else {}),
            "sources": {
                **DEFAULT_ALPACA_PRESET_REFRESH_CONFIG["sources"],
                **sources,
            },
        }
        alpaca_payload["preset_snapshots"] = self._latest_preset_snapshot_payloads(environment)
        if "symbol_presets" in alpaca_payload or "custom_symbols" in alpaca_payload:
            alpaca_payload["symbol_universe"] = resolve_alpaca_symbol_universe(payload)
        alpaca_payload["preset_metadata"] = stock_universe_metadata(payload)
        return payload

    def _latest_preset_snapshot_payloads(self, environment: Environment) -> dict[str, dict[str, Any]]:
        try:
            rows = self.registry.shared().alpaca_symbol_preset_snapshots(environment=environment)
        except PersistenceUnavailableError:
            return seed_alpaca_preset_snapshots()
        snapshots = latest_preset_snapshot_payloads(rows)
        return snapshots or seed_alpaca_preset_snapshots()

    def record_worker_heartbeat(
        self,
        *,
        status: str = "ok",
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
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
                        "environment": self.settings.environment.value,
                        **(metadata or {}),
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
        run_mode: str = "full_dry_run",
    ) -> dict[str, Any]:
        """Record an operator-triggered dry-run loop request for the dashboard.

        REQ: REQ-UI-008, REQ-DAT-008, REQ-OBS-004, REQ-OBS-005
        """

        now = datetime.now(UTC)
        run_id = str(uuid4())
        requested_mode = _manual_run_mode(run_mode)
        config_payload = self._with_latest_stock_universe(
            environment=environment,
            config_payload=_config_for_manual_mode(config_payload, requested_mode),
        )
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
        if requested_mode == "data_import":
            scanner_run = self._skipped_scanner_run(
                environment=environment,
                pipeline_run_id=run_id,
                started_at=now,
                reason="Manual data import mode stops after provider data fetch.",
                source_pull_ids=market_data_pull_ids,
            )
            reasoning_run = self._skipped_reasoning_run(
                environment=environment,
                pipeline_run_id=run_id,
                scanner_run_id=scanner_run.payload.get("id"),
                started_at=now,
                reason="Manual data import mode did not run scanner-to-brain scoring.",
            )
            strategy_run = self._skipped_strategy_run(
                environment=environment,
                pipeline_run_id=run_id,
                reasoning_run_id=reasoning_run.payload.get("id"),
                started_at=now,
                reason="Manual data import mode did not run strategy consensus.",
            )
            execution_run = self._skipped_execution_run(
                environment=environment,
                pipeline_run_id=run_id,
                strategy_consensus_run_id=strategy_run.payload.get("id"),
                started_at=now,
                reason="Manual data import mode did not run execution.",
            )
            exit_run = self._skipped_exit_run(
                environment=environment,
                pipeline_run_id=run_id,
                started_at=now,
                reason="Manual data import mode did not run exit monitoring.",
            )
        else:
            scanner_run = self.scanner.run(
                environment=environment,
                pipeline_run_id=run_id,
                trigger="manual",
                market_data_pulls=market_data_pulls,
                config_payload=config_payload,
                started_at=now,
                completed_at=now,
            )
            if requested_mode == "scanner_only":
                reasoning_run = self._skipped_reasoning_run(
                    environment=environment,
                    pipeline_run_id=run_id,
                    scanner_run_id=scanner_run.payload.get("id"),
                    started_at=now,
                    reason="Manual scanner-only mode stops before reasoning.",
                )
                strategy_run = self._skipped_strategy_run(
                    environment=environment,
                    pipeline_run_id=run_id,
                    reasoning_run_id=reasoning_run.payload.get("id"),
                    started_at=now,
                    reason="Manual scanner-only mode did not run strategy consensus.",
                )
                execution_run = self._skipped_execution_run(
                    environment=environment,
                    pipeline_run_id=run_id,
                    strategy_consensus_run_id=strategy_run.payload.get("id"),
                    started_at=now,
                    reason="Manual scanner-only mode did not run execution.",
                )
                exit_run = self._skipped_exit_run(
                    environment=environment,
                    pipeline_run_id=run_id,
                    started_at=now,
                    reason="Manual scanner-only mode did not run exit monitoring.",
                )
            else:
                reasoning_run = self.brain.run(
                    environment=environment,
                    pipeline_run_id=run_id,
                    trigger="manual",
                    scanner_run=scanner_run.payload,
                    config_payload=config_payload,
                    started_at=now,
                    completed_at=now,
                )
                strategy_run = self.strategy_consensus.run(
                    environment=environment,
                    pipeline_run_id=run_id,
                    trigger="manual",
                    scanner_run=scanner_run.payload,
                    reasoning_run=reasoning_run.payload,
                    config_payload=config_payload,
                    started_at=now,
                    completed_at=now,
                )
                execution_run = self.lifecycle.run_execution(
                    environment=environment,
                    pipeline_run_id=run_id,
                    trigger="manual",
                    strategy_run=strategy_run.payload,
                    market_data_pulls=market_data_pulls,
                    config_payload=config_payload,
                    credential_status=self._venue_credential_status(environment),
                    started_at=now,
                    completed_at=now,
                )
                exit_run = self.lifecycle.run_exit(
                    environment=environment,
                    pipeline_run_id=run_id,
                    trigger="manual",
                    market_data_pulls=market_data_pulls,
                    config_payload=config_payload,
                    started_at=now,
                    completed_at=now,
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
                    "environment": environment.value,
                    "requested_mode": requested_mode,
                    "triggered_by": username,
                    "market_data_pull_id": market_data_pull_ids[0] if market_data_pull_ids else None,
                    "market_data_pull_ids": market_data_pull_ids,
                    "scanner_run_id": scanner_run.payload.get("id"),
                    "scanner_accepted": scanner_run.payload["acceptedCount"],
                    "scanner_rejected": scanner_run.payload["rejectedCount"],
                    "reasoning_run_id": reasoning_run.payload.get("id"),
                    "reasoning_scored": reasoning_run.payload["scoredCount"],
                    "reasoning_skipped": reasoning_run.payload["skippedCount"],
                    "reasoning_failed": reasoning_run.payload["failedCount"],
                    "strategy_consensus_run_id": strategy_run.payload.get("id"),
                    "strategy_votes": strategy_run.payload["voteCount"],
                    "strategy_approved": strategy_run.payload["approvedCount"],
                    "strategy_refused": strategy_run.payload["refusedCount"],
                    "execution_run_id": execution_run.payload.get("id"),
                    "order_intents": execution_run.payload["intentCount"],
                    "order_simulated": execution_run.payload["simulatedCount"],
                    "order_submitted": execution_run.payload["submittedCount"],
                    "order_refused": execution_run.payload["refusedCount"],
                    "exit_run_id": exit_run.payload.get("id"),
                    "exit_open_positions": exit_run.payload["openPositionCount"],
                    "exit_triggered": exit_run.payload["triggeredCount"],
                    "exit_refused": exit_run.payload["refusedCount"],
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
                    "environment": environment.value,
                    "requested_mode": requested_mode,
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
                "requested_mode": requested_mode,
                "venues": [pull["venue"] for pull in market_data_pulls],
                "market_data_pull_id": market_data_pull_ids[0] if market_data_pull_ids else None,
                "market_data_pull_ids": market_data_pull_ids,
                "scanner_run_id": scanner_run.payload.get("id"),
                "scanner_accepted": scanner_run.payload["acceptedCount"],
                "scanner_rejected": scanner_run.payload["rejectedCount"],
                "reasoning_run_id": reasoning_run.payload.get("id"),
                "reasoning_scored": reasoning_run.payload["scoredCount"],
                "reasoning_skipped": reasoning_run.payload["skippedCount"],
                "reasoning_failed": reasoning_run.payload["failedCount"],
                "strategy_consensus_run_id": strategy_run.payload.get("id"),
                "strategy_votes": strategy_run.payload["voteCount"],
                "strategy_approved": strategy_run.payload["approvedCount"],
                "strategy_refused": strategy_run.payload["refusedCount"],
                "execution_run_id": execution_run.payload.get("id"),
                "order_intents": execution_run.payload["intentCount"],
                "order_simulated": execution_run.payload["simulatedCount"],
                "order_submitted": execution_run.payload["submittedCount"],
                "order_refused": execution_run.payload["refusedCount"],
                "exit_run_id": exit_run.payload.get("id"),
                "exit_open_positions": exit_run.payload["openPositionCount"],
                "exit_triggered": exit_run.payload["triggeredCount"],
                "exit_refused": exit_run.payload["refusedCount"],
            },
        )
        pipeline_run = self._record_pipeline_run(
            environment=environment,
            run_id=run_id,
            trigger="manual",
            started_at=now,
            completed_at=now,
            market_data_pulls=market_data_pulls,
            scanner_run=scanner_run.payload,
            reasoning_run=reasoning_run.payload,
            strategy_run=strategy_run.payload,
            execution_run=execution_run.payload,
            exit_run=exit_run.payload,
            actor=username,
            requested_mode=requested_mode,
        )
        return {
            "environment": environment.value,
            "runId": run_id,
            "status": "accepted",
            "requestedMode": requested_mode,
            "triggeredBy": username,
            "triggeredAt": now.isoformat(),
            "auditEventId": audit_event["id"],
            "message": (
                f"Manual {requested_mode.replace('_', ' ')} run accepted. "
                "Live order submission still depends on all configured gates."
            ),
            "marketDataPull": market_data_pull,
            "marketDataPulls": market_data_pulls,
            "scannerRun": scanner_run.payload,
            "reasoningRun": reasoning_run.payload,
            "strategyRun": strategy_run.payload,
            "executionRun": execution_run.payload,
            "exitRun": exit_run.payload,
            "pipelineRun": pipeline_run,
        }

    def _skipped_scanner_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        started_at: datetime,
        reason: str,
        source_pull_ids: list[str],
    ) -> ScannerRunResult:
        row = self.registry.shared().record_scanner_run(
            environment=environment,
            pipeline_run_id=pipeline_run_id,
            trigger="manual",
            status="skipped",
            config={"skip_reason": reason},
            source_pull_ids=source_pull_ids,
            accepted_count=0,
            rejected_count=0,
            started_at=started_at,
            completed_at=started_at,
        )
        payload = scanner_run_payload(row, [])
        payload["message"] = reason
        return ScannerRunResult(row=row, candidates=(), payload=payload)

    def _skipped_reasoning_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        scanner_run_id: str | None,
        started_at: datetime,
        reason: str,
    ) -> ReasoningRunResult:
        row = self.registry.shared().record_reasoning_run(
            environment=environment,
            pipeline_run_id=pipeline_run_id,
            scanner_run_id=scanner_run_id,
            trigger="manual",
            status="skipped",
            config={"skip_reason": reason},
            provider_count=0,
            prompt_count=0,
            scored_count=0,
            skipped_count=0,
            failed_count=0,
            started_at=started_at,
            completed_at=started_at,
        )
        payload = reasoning_run_payload(row, [])
        payload["message"] = reason
        return ReasoningRunResult(payload=payload)

    def _skipped_strategy_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        reasoning_run_id: str | None,
        started_at: datetime,
        reason: str,
    ) -> StrategyConsensusRunResult:
        row = self.registry.shared().record_strategy_consensus_run(
            environment=environment,
            pipeline_run_id=pipeline_run_id,
            reasoning_run_id=reasoning_run_id,
            trigger="manual",
            status="skipped",
            config={"skip_reason": reason},
            vote_count=0,
            approved_count=0,
            refused_count=0,
            started_at=started_at,
            completed_at=started_at,
        )
        payload = strategy_consensus_run_payload(row, [], [])
        payload["message"] = reason
        return StrategyConsensusRunResult(payload=payload)

    def _skipped_execution_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        strategy_consensus_run_id: str | None,
        started_at: datetime,
        reason: str,
    ) -> LifecycleRunResult:
        row = self.registry.shared().record_execution_run(
            environment=environment,
            pipeline_run_id=pipeline_run_id,
            strategy_consensus_run_id=strategy_consensus_run_id,
            trigger="manual",
            status="skipped",
            config={"skip_reason": reason},
            intent_count=0,
            submitted_count=0,
            simulated_count=0,
            refused_count=0,
            reconciliation_count=0,
            started_at=started_at,
            completed_at=started_at,
        )
        payload = execution_run_payload(row, [])
        payload["message"] = reason
        return LifecycleRunResult(payload=payload)

    def _skipped_exit_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        started_at: datetime,
        reason: str,
    ) -> LifecycleRunResult:
        row = self.registry.shared().record_exit_run(
            environment=environment,
            pipeline_run_id=pipeline_run_id,
            trigger="manual",
            status="skipped",
            config={"skip_reason": reason},
            open_position_count=0,
            triggered_count=0,
            simulated_count=0,
            submitted_count=0,
            refused_count=0,
            started_at=started_at,
            completed_at=started_at,
        )
        payload = exit_run_payload(row, [])
        payload["message"] = reason
        return LifecycleRunResult(payload=payload)

    def trigger_scheduled_run(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Run scheduled provider market-data ingestion and record the heartbeat."""

        now = datetime.now(UTC)
        run_id = str(uuid4())
        stock_universe_refresh = self.stock_universe_refresher.refresh(
            environment=environment,
            config_payload=config_payload,
            trigger="scheduled",
            now=now,
        )
        config_payload = self._with_latest_stock_universe(
            environment=environment,
            config_payload=config_payload,
        )
        market_data_pulls = []
        for venue in self._scheduled_market_data_fetch_order(config_payload):
            market_data_pulls.append(
                self._fetch_and_record_market_data_pull(
                    environment=environment,
                    venue=venue,
                    trigger="scheduled",
                    config_payload=config_payload,
                    created_at=datetime.now(UTC),
                    run_id=run_id,
                )
            )
        scanner_started_at = datetime.now(UTC)
        scanner_run = self.scanner.run(
            environment=environment,
            pipeline_run_id=run_id,
            trigger="scheduled",
            market_data_pulls=market_data_pulls,
            config_payload=config_payload,
            started_at=scanner_started_at,
            completed_at=None,
        )
        reasoning_started_at = datetime.now(UTC)
        reasoning_run = self.brain.run(
            environment=environment,
            pipeline_run_id=run_id,
            trigger="scheduled",
            scanner_run=scanner_run.payload,
            config_payload=config_payload,
            started_at=reasoning_started_at,
            completed_at=None,
        )
        strategy_started_at = datetime.now(UTC)
        strategy_run = self.strategy_consensus.run(
            environment=environment,
            pipeline_run_id=run_id,
            trigger="scheduled",
            scanner_run=scanner_run.payload,
            reasoning_run=reasoning_run.payload,
            config_payload=config_payload,
            started_at=strategy_started_at,
            completed_at=strategy_started_at,
        )
        execution_started_at = datetime.now(UTC)
        execution_run = self.lifecycle.run_execution(
            environment=environment,
            pipeline_run_id=run_id,
            trigger="scheduled",
            strategy_run=strategy_run.payload,
            market_data_pulls=market_data_pulls,
            config_payload=config_payload,
            credential_status=self._venue_credential_status(environment),
            started_at=execution_started_at,
            completed_at=execution_started_at,
        )
        exit_started_at = datetime.now(UTC)
        exit_run = self.lifecycle.run_exit(
            environment=environment,
            pipeline_run_id=run_id,
            trigger="scheduled",
            market_data_pulls=market_data_pulls,
            config_payload=config_payload,
            started_at=exit_started_at,
            completed_at=exit_started_at,
        )
        completed_at = datetime.now(UTC)
        status = _aggregate_market_data_pull_status([pull["status"] for pull in market_data_pulls])
        try:
            self.registry.state.insert(
                f"{SHARED_SCHEMA}.job_runs",
                {
                    "id": run_id,
                    "job_name": self.WORKER_JOB_NAME,
                    "status": status,
                    "heartbeat_at": completed_at,
                    "metadata": {
                        "message": "scheduled provider market data ingestion",
                        "scheduled": True,
                        "environment": environment.value,
                        "stock_universe_refresh": stock_universe_refresh.payload,
                        "market_data_pull_ids": [pull["id"] for pull in market_data_pulls],
                        "venues": [pull["venue"] for pull in market_data_pulls],
                        "scanner_run_id": scanner_run.payload.get("id"),
                        "scanner_accepted": scanner_run.payload["acceptedCount"],
                        "scanner_rejected": scanner_run.payload["rejectedCount"],
                        "reasoning_run_id": reasoning_run.payload.get("id"),
                        "reasoning_scored": reasoning_run.payload["scoredCount"],
                        "reasoning_skipped": reasoning_run.payload["skippedCount"],
                        "reasoning_failed": reasoning_run.payload["failedCount"],
                        "strategy_consensus_run_id": strategy_run.payload.get("id"),
                        "strategy_votes": strategy_run.payload["voteCount"],
                        "strategy_approved": strategy_run.payload["approvedCount"],
                        "strategy_refused": strategy_run.payload["refusedCount"],
                        "execution_run_id": execution_run.payload.get("id"),
                        "order_intents": execution_run.payload["intentCount"],
                        "order_simulated": execution_run.payload["simulatedCount"],
                        "order_submitted": execution_run.payload["submittedCount"],
                        "order_refused": execution_run.payload["refusedCount"],
                        "exit_run_id": exit_run.payload.get("id"),
                        "exit_open_positions": exit_run.payload["openPositionCount"],
                        "exit_triggered": exit_run.payload["triggeredCount"],
                        "exit_refused": exit_run.payload["refusedCount"],
                    },
                    "created_at": completed_at,
                },
            )
        except PersistenceUnavailableError:
            pass
        pipeline_run = self._record_pipeline_run(
            environment=environment,
            run_id=run_id,
            trigger="scheduled",
            started_at=now,
            completed_at=completed_at,
            market_data_pulls=market_data_pulls,
            scanner_run=scanner_run.payload,
            reasoning_run=reasoning_run.payload,
            strategy_run=strategy_run.payload,
            execution_run=execution_run.payload,
            exit_run=exit_run.payload,
            actor="scheduler",
        )
        return {
            "environment": environment.value,
            "runId": run_id,
            "status": status,
            "triggeredAt": now.isoformat(),
            "stockUniverseRefresh": stock_universe_refresh.payload,
            "marketDataPull": self.market_data_pull(
                environment=environment,
                config_payload=config_payload,
            ),
            "marketDataPulls": market_data_pulls,
            "scannerRun": scanner_run.payload,
            "reasoningRun": reasoning_run.payload,
            "strategyRun": strategy_run.payload,
            "executionRun": execution_run.payload,
            "exitRun": exit_run.payload,
            "pipelineRun": pipeline_run,
        }

    def worker_status(self) -> dict[str, Any]:
        """Return latest worker heartbeat status.

        REQ: REQ-DAT-008, REQ-OBS-005
        """

        try:
            rows = self.registry.state.rows(
                f"{SHARED_SCHEMA}.job_runs",
                limit=1,
                newest_first=True,
                filters={"job_name": self.WORKER_JOB_NAME},
            )
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
        heartbeat_status = str(latest["status"])
        state, value = _worker_heartbeat_state(
            status=heartbeat_status,
            age_seconds=age_seconds,
        )
        metadata = latest.get("metadata")
        heartbeat_message = (
            str(metadata.get("message", "")).strip()
            if isinstance(metadata, dict)
            else ""
        )
        if heartbeat_status == "failed" and heartbeat_message.startswith(
            "scheduler tick failed:"
        ):
            value = heartbeat_message
        return {
            "state": state,
            "value": value,
            "lastHeartbeatAt": heartbeat.isoformat(),
            "ageSeconds": age_seconds,
            "heartbeatStatus": heartbeat_status,
        }

    def credential_rows(self, environment: Environment) -> list[dict[str, Any]]:
        """Return safe credential readiness rows for wallet/account UI.

        REQ: REQ-UI-009, REQ-WAL-005, REQ-WAL-006
        """

        rows = [
            *(
                self._credential_row(
                    credential_id=f"{Venue.POLYMARKET_US.value}-{provider.value}-wallet",
                    label=f"Polymarket US / {_provider_label(provider)}",
                    venue=Venue.POLYMARKET_US.value,
                    provider=provider.value,
                    reference=resolve_credential_ref(
                        CredentialTarget(
                            environment,
                            Venue.POLYMARKET_US,
                            provider,
                            "wallet",
                        )
                    ),
                    required_names=(f"POLYMARKET_{provider.value.upper()}_KEY_ID",),
                    alternative_required_names=(
                        f"POLYMARKET_{provider.value.upper()}_SECRET_KEY",
                        f"POLYMARKET_{provider.value.upper()}_PRIVATE_KEY",
                    ),
                    public_identifier=f"pm-{provider.value}-{environment.value}",
                    enabled=self.settings.polymarket_us_enabled,
                    purpose="live Polymarket US orders for model performance comparison",
                )
                for provider in TRADING_MODEL_PROVIDERS
            ),
            *(
                self._credential_row(
                    credential_id=f"{Venue.ALPACA.value}-{provider.value}-account",
                    label=f"Alpaca / {_provider_label(provider)}",
                    venue=Venue.ALPACA.value,
                    provider=provider.value,
                    reference=resolve_credential_ref(
                        CredentialTarget(
                            environment,
                            Venue.ALPACA,
                            provider,
                            "api-key",
                        )
                    ),
                    required_names=(
                        f"ALPACA_{provider.value.upper()}_KEY_ID",
                        f"ALPACA_{provider.value.upper()}_SECRET_KEY",
                    ),
                    public_identifier=f"alpaca-{provider.value}-{self.settings.trading_account_mode}",
                    enabled=self.settings.alpaca_enabled,
                    account_status=self.settings.alpaca_account_status,
                    purpose="live Alpaca account reads and order submission for model performance comparison",
                )
                for provider in TRADING_MODEL_PROVIDERS
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

    def send_test_notification(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        requested_by: str,
        message: str = "",
    ) -> dict[str, Any]:
        """Send a harmless operator notification through the configured adapter."""

        now = datetime.now(UTC)
        notification_config = config_payload.get("notifications", {})
        settings = NotificationSettings.from_config(notification_config)
        recipients = settings.recipient_emails
        subject = f"Codex Poly Bot test notification: {environment.value}"
        body = "\n".join(
            line
            for line in (
                "This is a test notification from Codex Poly Bot.",
                f"Environment: {environment.value}",
                f"Requested by: {requested_by}",
                f"Message: {message.strip()}" if message.strip() else "",
            )
            if line
        )
        email = EmailMessage(recipients=recipients, subject=subject, body=body)
        adapter = self.lifecycle.notification_adapter
        if adapter is None:
            delivery = None
            sent = False
            attempt_recorded = False
            message_id = None
            retryable = False
            skipped_reason = "notification adapter not configured"
            error_summary = None
        else:
            delivery = adapter.send_alert(email)
            sent = delivery.sent
            attempt_recorded = delivery.attempt_recorded
            message_id = delivery.message_id
            retryable = delivery.retryable
            skipped_reason = delivery.skipped_reason
            error_summary = delivery.error_summary
        next_retry_at = (
            now + timedelta(seconds=settings.retry_delay_seconds)
            if retryable
            else None
        )
        self.notification_ledger.record(
            NotificationDeliveryRecord(
                notification_type="test_notification",
                recipients=recipients,
                subject=subject,
                attempted_at=now,
                sent=sent,
                message_id=message_id,
                skipped_reason=skipped_reason,
                retryable=retryable,
                next_retry_at=next_retry_at,
                error_summary=error_summary,
            )
        )
        return {
            "environment": environment.value,
            "notificationType": "test_notification",
            "sent": sent,
            "attemptRecorded": attempt_recorded,
            "recipientCount": len(recipients),
            "messageId": message_id,
            "retryable": retryable,
            "skippedReason": skipped_reason,
            "errorSummary": error_summary,
            "attemptedAt": now.isoformat(),
            "nextRetryAt": next_retry_at.isoformat() if next_retry_at else None,
        }

    def tick_schedule(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        worker_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the latest completed tick and the next expected tick time."""

        now = datetime.now(UTC)
        interval_seconds = _positive_int(
            config_payload.get("trading_loop_interval_seconds"),
            default=900,
        )
        worker = worker_status or self.worker_status()
        try:
            latest_rows = self.registry.state.rows(
                self.PIPELINE_RUNS_TABLE,
                limit=1,
                newest_first=True,
                filters={"environment": environment.value},
            )
        except PersistenceUnavailableError:
            latest_rows = []
        latest_run = latest_rows[0] if latest_rows else None
        run_time = None
        if latest_run is not None:
            run_time = (
                _parse_datetime(latest_run.get("completed_at"))
                or _parse_datetime(latest_run.get("started_at"))
            )
        heartbeat_time = _parse_datetime(worker.get("lastHeartbeatAt"))
        last_tick_at = run_time or heartbeat_time
        last_tick_source = (
            "pipeline_run"
            if run_time is not None
            else ("worker_heartbeat" if heartbeat_time is not None else "none")
        )
        next_tick_at = (
            last_tick_at + timedelta(seconds=interval_seconds)
            if last_tick_at is not None
            else now + timedelta(seconds=interval_seconds)
        )
        seconds_until_next_tick = max(0, int((next_tick_at - now).total_seconds()))
        return {
            "environment": environment.value,
            "generatedAt": now.isoformat(),
            "intervalSeconds": interval_seconds,
            "lastTickAt": _isoformat_or_none(last_tick_at),
            "lastTickStatus": latest_run.get("status") if latest_run else worker.get("heartbeatStatus"),
            "lastTickRunId": latest_run.get("id") if latest_run else None,
            "lastTickSource": last_tick_source,
            "lastHeartbeatAt": worker.get("lastHeartbeatAt"),
            "heartbeatStatus": worker.get("heartbeatStatus"),
            "ageSeconds": worker.get("ageSeconds"),
            "nextTickAt": next_tick_at.isoformat(),
            "secondsUntilNextTick": seconds_until_next_tick,
            "due": seconds_until_next_tick == 0,
            "source": worker.get("value"),
        }

    def data_explorer(self, environment: Environment) -> dict[str, Any]:
        """Return read-only dashboard datasets for the data explorer."""

        datasets = []
        for alias, metadata in DATA_EXPLORER_DATASETS.items():
            datasets.append(
                {
                    "id": alias,
                    "label": metadata["label"],
                    "table": metadata["table"],
                    "description": metadata["description"],
                    "rowCount": 0,
                    "columns": list(metadata["columns"]),
                    "sampleRows": [],
                }
            )
        return {
            "environment": environment.value,
            "generatedAt": datetime.now(UTC).isoformat(),
            "datasets": datasets,
            "defaultQuery": "select * from market_data_pulls limit 25",
        }

    def query_data(
        self,
        *,
        environment: Environment,
        query: str,
        default_limit: int = 100,
    ) -> dict[str, Any]:
        """Run a restricted read-only SQL-like query against dashboard datasets."""

        parsed = _parse_explorer_query(query)
        dataset_id = parsed["dataset"]
        limit = min(max(1, int(parsed["limit"] or default_limit)), DASHBOARD_DATA_EXPLORER_ROW_LIMIT)
        rows = self._explorer_rows_for_query(environment, parsed, row_limit=limit)
        filtered_rows = [
            row
            for row in rows
            if all(_matches_explorer_condition(row, condition) for condition in parsed["conditions"])
        ]
        if parsed["orderBy"]:
            filtered_rows.sort(
                key=lambda row: _sortable_explorer_value(_nested_explorer_value(row, parsed["orderBy"])),
                reverse=parsed["orderDirection"] == "desc",
            )
        selected_rows = filtered_rows[:limit]
        columns = (
            _explorer_columns(selected_rows, ())
            if parsed["columns"] == ["*"]
            else parsed["columns"]
        )
        projected_rows = [_project_explorer_row(row, columns) for row in selected_rows]
        dataset = DATA_EXPLORER_DATASETS[dataset_id]
        joined_dataset_ids = [join["dataset"] for join in parsed.get("joins", [])]
        dataset_label = (
            "Joined datasets"
            if joined_dataset_ids
            else str(dataset["label"])
        )
        dataset_table = (
            " + ".join([str(dataset["table"])] + [str(DATA_EXPLORER_DATASETS[item]["table"]) for item in joined_dataset_ids])
            if joined_dataset_ids
            else str(dataset["table"])
        )
        return {
            "environment": environment.value,
            "generatedAt": datetime.now(UTC).isoformat(),
            "query": parsed["normalizedQuery"],
            "dataset": {
                "id": dataset_id,
                "label": dataset_label,
                "table": dataset_table,
            },
            "columns": columns,
            "rows": projected_rows,
            "rowCount": len(projected_rows),
            "totalMatched": len(filtered_rows),
            "limit": limit,
            "message": f"Returned {len(projected_rows)} of {len(filtered_rows)} matching rows.",
        }

    def generate_data_query(self, *, environment: Environment, prompt: str) -> dict[str, Any]:
        """Generate a read-only dashboard query from a natural-language prompt."""

        generated = _generate_explorer_query(prompt)
        return {
            "environment": environment.value,
            "generatedAt": datetime.now(UTC).isoformat(),
            "model": "local-data-query-helper",
            "modelMode": "local_rules",
            "prompt": prompt,
            **generated,
        }

    def scenario_analysis(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        run_id: str | None = None,
        step_key: str | None = None,
        prompt: str | None = None,
        config_overrides: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Explain a tick step-by-step and suggest safe next tests."""

        runs = self.pipeline_runs(environment, limit=20)
        selected_run = next((run for run in runs if run["id"] == run_id), runs[0] if runs else None)
        hydrate_records = bool(run_id or step_key or prompt or config_overrides)
        detail = (
            self.pipeline_run_detail(environment, selected_run["id"])
            if selected_run and hydrate_records
            else None
        )
        record_groups = detail.get("records", []) if detail else []
        record_lookup = {
            group["stepKey"]: group
            for group in record_groups
            if isinstance(group, dict) and group.get("stepKey")
        }
        step_analyses = [
            _scenario_step_analysis(
                step=step,
                record_group=record_lookup.get(step.get("key"), {}),
                config_payload=config_payload,
            )
            for step in (selected_run.get("steps", []) if selected_run else [])
        ]
        selected_step = (
            next((step for step in step_analyses if step["key"] == step_key), None)
            or next((step for step in step_analyses if step["state"] in {"blocked", "idle"}), None)
            or (step_analyses[0] if step_analyses else None)
        )
        recommended_config_set = _scenario_config_plan(
            run=selected_run,
            steps=step_analyses,
            selected_step=selected_step,
            config_payload=config_payload,
        )
        override_results = [
            _scenario_override_result(
                override,
                selected_step,
                config_payload=config_payload,
            )
            for override in (config_overrides or [])
            if isinstance(override, dict)
        ]
        answer = _scenario_prompt_answer(
            prompt=prompt or "",
            run=selected_run,
            step=selected_step,
            steps=step_analyses,
            overrides=override_results,
            recommended_config_set=recommended_config_set,
        )
        return {
            "environment": environment.value,
            "generatedAt": datetime.now(UTC).isoformat(),
            "model": "local-scenario-helper",
            "modelMode": "local_rules",
            "run": selected_run,
            "runs": runs,
            "selectedStepKey": selected_step["key"] if selected_step else None,
            "steps": step_analyses,
            "records": record_groups,
            "configTests": override_results,
            "recommendedConfigSet": recommended_config_set,
            "answer": answer,
            "prompt": prompt or "",
            "message": (
                "Scenario analysis is based on recorded tick data, current config, and safe local rules."
                if selected_run
                else "No tick has been recorded yet. Run a manual data import or dry run to create a walkthrough."
            ),
        }

    def operations_summary(
        self,
        environment: Environment,
        *,
        include_history: bool = False,
        include_details: bool = False,
        include_runs: bool = False,
    ) -> dict[str, Any]:
        """Return operational status and latest order rows.

        REQ: REQ-EXE-014, REQ-EXE-016, REQ-OBS-005
        """

        order_items = self.order_events() if include_details else []
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
            "pipelineRuns": (
                self.pipeline_runs(
                    environment,
                    include_steps=include_details,
                )
                if include_details or include_runs
                else []
            ),
            "scanner": (
                self.scanner_summary(environment)
                if include_details
                else (
                    self._deferred_scanner_summary()
                    if include_runs
                    else self.scanner_overview(environment)
                )
            ),
            "reasoning": (
                self.reasoning_summary(environment)
                if include_details
                else self._deferred_reasoning_summary()
            ),
            "strategyConsensus": (
                self.strategy_consensus_summary(environment)
                if include_details
                else self._deferred_strategy_consensus_summary()
            ),
            "execution": (
                self.execution_summary(environment)
                if include_details
                else self._deferred_execution_summary()
            ),
            "exit": (
                self.exit_summary(environment)
                if include_details
                else self._deferred_exit_summary()
            ),
            "historicalImport": (
                self.historical_import_summary(environment)
                if include_history
                else self._deferred_historical_import_summary()
            ),
            "brokerHistory": (
                self.broker_history_summary(environment)
                if include_history
                else self._deferred_broker_history_summary()
            ),
        }

    def _deferred_scanner_summary(self) -> dict[str, Any]:
        return {
            "status": "deferred",
            "message": "Scanner details are deferred from the run-summary response.",
            "latestRun": None,
            "candidateCount": 0,
            "acceptedCount": 0,
            "rejectedCount": 0,
            "rejectionBreakdown": [],
            "candidates": [],
            "detailsDeferred": True,
        }

    def _deferred_reasoning_summary(self) -> dict[str, Any]:
        return {
            "status": "deferred",
            "message": "Reasoning details are deferred from the default operations summary.",
            "latestRun": None,
            "promptCount": 0,
            "scoredCount": 0,
            "skippedCount": 0,
            "failedCount": 0,
            "outputs": [],
        }

    def _deferred_strategy_consensus_summary(self) -> dict[str, Any]:
        return {
            "status": "deferred",
            "message": "Strategy consensus details are deferred from the default operations summary.",
            "latestRun": None,
            "voteCount": 0,
            "approvedCount": 0,
            "refusedCount": 0,
            "votes": [],
            "outputs": [],
        }

    def _deferred_execution_summary(self) -> dict[str, Any]:
        return {
            "status": "deferred",
            "message": "Execution details are deferred from the default operations summary.",
            "latestRun": None,
            "intentCount": 0,
            "submittedCount": 0,
            "simulatedCount": 0,
            "refusedCount": 0,
            "intents": [],
        }

    def _deferred_exit_summary(self) -> dict[str, Any]:
        return {
            "status": "deferred",
            "message": "Exit details are deferred from the default operations summary.",
            "latestRun": None,
            "openPositionCount": 0,
            "triggeredCount": 0,
            "simulatedCount": 0,
            "submittedCount": 0,
            "refusedCount": 0,
            "intents": [],
        }

    def _deferred_historical_import_summary(self) -> dict[str, Any]:
        return {
            "status": "deferred",
            "message": (
                "Historical Polymarket import details are deferred from the default "
                "operations summary to keep dashboard polling bounded."
            ),
            "counts": _empty_historical_import_counts(),
            "checkpoints": [],
            "lastUpdatedAt": None,
        }

    def _deferred_broker_history_summary(self) -> dict[str, Any]:
        return {
            "status": "deferred",
            "message": (
                "Broker history details are deferred from the default operations summary "
                "to keep dashboard polling bounded."
            ),
            "counts": _empty_broker_history_counts(),
            "checkpoints": [],
            "lastUpdatedAt": None,
        }

    def scanner_summary(self, environment: Environment) -> dict[str, Any]:
        """Return latest scanner aggregates without loading historical candidates.

        REQ: REQ-STR-003, REQ-UI-004, REQ-OBS-005
        """

        try:
            latest = self.registry.shared().latest_scanner_run(environment=environment)
            rejection_breakdown = (
                self.registry.shared().scanner_rejection_breakdown(
                    environment=environment,
                    pipeline_run_id=latest["pipeline_run_id"],
                )
                if latest is not None
                else []
            )
        except PersistenceUnavailableError:
            return {
                "status": "unavailable",
                "message": "Scanner status is unavailable because persistence is offline.",
                "latestRun": None,
                "candidateCount": 0,
                "acceptedCount": 0,
                "rejectedCount": 0,
                "candidates": [],
                "detailsDeferred": True,
            }
        if latest is None:
            return {
                "status": "idle",
                "message": "No scanner run has been recorded yet.",
                "latestRun": None,
                "candidateCount": 0,
                "acceptedCount": 0,
                "rejectedCount": 0,
                "candidates": [],
                "detailsDeferred": True,
            }
        payload = scanner_run_payload(latest, [])
        candidate_count = payload["acceptedCount"] + payload["rejectedCount"]
        payload["candidateCount"] = candidate_count
        return {
            "status": payload["status"],
            "message": _scanner_summary_message({**payload, "rejectionBreakdown": rejection_breakdown}),
            "latestRun": payload,
            "candidateCount": candidate_count,
            "acceptedCount": payload["acceptedCount"],
            "rejectedCount": payload["rejectedCount"],
            "rejectionBreakdown": rejection_breakdown,
            "candidates": [],
            "detailsDeferred": True,
        }

    def scanner_overview(self, environment: Environment) -> dict[str, Any]:
        """Return persisted scanner aggregates without loading candidate detail rows.

        REQ: REQ-UI-004, REQ-OBS-005
        """

        try:
            shared = self.registry.shared()
            latest = shared.latest_scanner_run(environment=environment)
            rejection_breakdown = (
                shared.scanner_rejection_breakdown(
                    environment=environment,
                    pipeline_run_id=latest["pipeline_run_id"],
                )
                if latest is not None
                else []
            )
        except PersistenceUnavailableError:
            return {
                "status": "unavailable",
                "message": "Scanner status is unavailable because persistence is offline.",
                "latestRun": None,
                "candidateCount": 0,
                "acceptedCount": 0,
                "rejectedCount": 0,
                "rejectionBreakdown": [],
                "candidates": [],
                "detailsDeferred": True,
            }
        if latest is None:
            return {
                "status": "idle",
                "message": "No scanner run has been recorded yet.",
                "latestRun": None,
                "candidateCount": 0,
                "acceptedCount": 0,
                "rejectedCount": 0,
                "rejectionBreakdown": [],
                "candidates": [],
                "detailsDeferred": True,
            }
        payload = scanner_run_payload(latest, [])
        candidate_count = payload["acceptedCount"] + payload["rejectedCount"]
        payload["candidateCount"] = candidate_count
        return {
            "status": payload["status"],
            "message": _scanner_summary_message(
                {**payload, "rejectionBreakdown": rejection_breakdown}
            ),
            "latestRun": payload,
            "candidateCount": candidate_count,
            "acceptedCount": payload["acceptedCount"],
            "rejectedCount": payload["rejectedCount"],
            "rejectionBreakdown": rejection_breakdown,
            "candidates": [],
            "detailsDeferred": True,
        }

    def reasoning_summary(self, environment: Environment) -> dict[str, Any]:
        """Return latest reasoning status and scored rows for operations UI.

        REQ: REQ-LLM-001, REQ-LLM-003, REQ-UI-004, REQ-OBS-005
        """

        try:
            runs = self.registry.state.rows(
                self.REASONING_RUNS_TABLE,
                limit=1,
                newest_first=True,
                filters={"environment": environment.value},
            )
            outputs = (
                self.registry.state.rows(
                    self.REASONING_OUTPUTS_TABLE,
                    limit=DASHBOARD_REASONING_OUTPUT_ROW_LIMIT,
                    newest_first=True,
                    filters={
                        "environment": environment.value,
                        "reasoning_run_id": runs[0]["id"],
                    },
                )
                if runs
                else []
            )
        except PersistenceUnavailableError:
            return {
                "status": "unavailable",
                "message": "Reasoning status is unavailable because persistence is offline.",
                "latestRun": None,
                "promptCount": 0,
                "scoredCount": 0,
                "skippedCount": 0,
                "failedCount": 0,
                "outputs": [],
            }
        if not runs:
            return {
                "status": "idle",
                "message": "No reasoning run has been recorded yet.",
                "latestRun": None,
                "promptCount": 0,
                "scoredCount": 0,
                "skippedCount": 0,
                "failedCount": 0,
                "outputs": [],
            }
        runs.sort(key=lambda row: row.get("started_at") or row.get("created_at"), reverse=True)
        latest = runs[0]
        latest_outputs = [
            output for output in outputs if output["reasoning_run_id"] == latest["id"]
        ]
        latest_outputs.sort(key=lambda row: row.get("created_at"), reverse=True)
        payload = reasoning_run_payload(latest, latest_outputs[:100])
        return {
            "status": payload["status"],
            "message": _reasoning_summary_message(payload),
            "latestRun": payload,
            "promptCount": payload["promptCount"],
            "scoredCount": payload["scoredCount"],
            "skippedCount": payload["skippedCount"],
            "failedCount": payload["failedCount"],
            "outputs": payload["outputs"],
        }

    def strategy_consensus_summary(self, environment: Environment) -> dict[str, Any]:
        """Return latest strategy vote and consensus status for operations UI.

        REQ: REQ-STR-007, REQ-STR-008, REQ-UI-004, REQ-OBS-005
        """

        try:
            runs = self.registry.state.rows(
                self.STRATEGY_CONSENSUS_RUNS_TABLE,
                limit=1,
                newest_first=True,
                filters={"environment": environment.value},
            )
            votes = (
                self.registry.state.rows(
                    self.STRATEGY_VOTES_TABLE,
                    limit=DASHBOARD_STRATEGY_VOTE_ROW_LIMIT,
                    newest_first=True,
                    filters={
                        "environment": environment.value,
                        "consensus_run_id": runs[0]["id"],
                    },
                )
                if runs
                else []
            )
            outputs = (
                self.registry.state.rows(
                    self.STRATEGY_CONSENSUS_OUTPUTS_TABLE,
                    limit=DASHBOARD_STRATEGY_OUTPUT_ROW_LIMIT,
                    newest_first=True,
                    filters={
                        "environment": environment.value,
                        "consensus_run_id": runs[0]["id"],
                    },
                )
                if runs
                else []
            )
        except PersistenceUnavailableError:
            return {
                "status": "unavailable",
                "message": "Strategy consensus status is unavailable because persistence is offline.",
                "latestRun": None,
                "voteCount": 0,
                "approvedCount": 0,
                "refusedCount": 0,
                "votes": [],
                "outputs": [],
            }
        if not runs:
            return {
                "status": "idle",
                "message": "No strategy consensus run has been recorded yet.",
                "latestRun": None,
                "voteCount": 0,
                "approvedCount": 0,
                "refusedCount": 0,
                "votes": [],
                "outputs": [],
            }
        runs.sort(key=lambda row: row.get("started_at") or row.get("created_at"), reverse=True)
        latest = runs[0]
        latest_votes = [vote for vote in votes if vote["consensus_run_id"] == latest["id"]]
        latest_outputs = [output for output in outputs if output["consensus_run_id"] == latest["id"]]
        latest_votes.sort(key=lambda row: row.get("created_at"), reverse=True)
        latest_outputs.sort(key=lambda row: row.get("created_at"), reverse=True)
        payload = strategy_consensus_run_payload(latest, latest_votes[:200], latest_outputs[:100])
        return {
            "status": payload["status"],
            "message": _strategy_consensus_summary_message(payload),
            "latestRun": payload,
            "voteCount": payload["voteCount"],
            "approvedCount": payload["approvedCount"],
            "refusedCount": payload["refusedCount"],
            "votes": payload["votes"],
            "outputs": payload["outputs"],
        }

    def execution_summary(self, environment: Environment) -> dict[str, Any]:
        """Return latest order-intent execution status for operations UI."""

        try:
            runs = self.registry.state.rows(
                self.EXECUTION_RUNS_TABLE,
                limit=1,
                newest_first=True,
                filters={"environment": environment.value},
            )
            intents = (
                self.registry.state.rows(
                    self.ORDER_INTENTS_TABLE,
                    limit=DASHBOARD_EXECUTION_INTENT_ROW_LIMIT,
                    newest_first=True,
                    filters={
                        "environment": environment.value,
                        "execution_run_id": runs[0]["id"],
                    },
                )
                if runs
                else []
            )
        except PersistenceUnavailableError:
            return {
                "status": "unavailable",
                "message": "Execution status is unavailable because persistence is offline.",
                "latestRun": None,
                "intentCount": 0,
                "submittedCount": 0,
                "simulatedCount": 0,
                "refusedCount": 0,
                "intents": [],
            }
        if not runs:
            return {
                "status": "idle",
                "message": "No execution run has been recorded yet.",
                "latestRun": None,
                "intentCount": 0,
                "submittedCount": 0,
                "simulatedCount": 0,
                "refusedCount": 0,
                "intents": [],
            }
        runs.sort(key=lambda row: row.get("started_at") or row.get("created_at"), reverse=True)
        latest = runs[0]
        latest_intents = [intent for intent in intents if intent["execution_run_id"] == latest["id"]]
        latest_intents.sort(key=lambda row: row.get("created_at"), reverse=True)
        payload = execution_run_payload(latest, latest_intents[:100])
        return {
            "status": payload["status"],
            "message": _execution_summary_message(payload),
            "latestRun": payload,
            "intentCount": payload["intentCount"],
            "submittedCount": payload["submittedCount"],
            "simulatedCount": payload["simulatedCount"],
            "refusedCount": payload["refusedCount"],
            "intents": payload["intents"],
        }

    def exit_summary(self, environment: Environment) -> dict[str, Any]:
        """Return latest open-position exit status for operations UI."""

        try:
            runs = self.registry.state.rows(
                self.EXIT_RUNS_TABLE,
                limit=1,
                newest_first=True,
                filters={"environment": environment.value},
            )
            intents = (
                self.registry.state.rows(
                    self.EXIT_INTENTS_TABLE,
                    limit=DASHBOARD_EXIT_INTENT_ROW_LIMIT,
                    newest_first=True,
                    filters={
                        "environment": environment.value,
                        "exit_run_id": runs[0]["id"],
                    },
                )
                if runs
                else []
            )
        except PersistenceUnavailableError:
            return {
                "status": "unavailable",
                "message": "Exit status is unavailable because persistence is offline.",
                "latestRun": None,
                "openPositionCount": 0,
                "triggeredCount": 0,
                "simulatedCount": 0,
                "submittedCount": 0,
                "refusedCount": 0,
                "intents": [],
            }
        if not runs:
            return {
                "status": "idle",
                "message": "No exit run has been recorded yet.",
                "latestRun": None,
                "openPositionCount": 0,
                "triggeredCount": 0,
                "simulatedCount": 0,
                "submittedCount": 0,
                "refusedCount": 0,
                "intents": [],
            }
        runs.sort(key=lambda row: row.get("started_at") or row.get("created_at"), reverse=True)
        latest = runs[0]
        latest_intents = [intent for intent in intents if intent["exit_run_id"] == latest["id"]]
        latest_intents.sort(key=lambda row: row.get("created_at"), reverse=True)
        payload = exit_run_payload(latest, latest_intents[:100])
        return {
            "status": payload["status"],
            "message": _exit_summary_message(payload),
            "latestRun": payload,
            "openPositionCount": payload["openPositionCount"],
            "triggeredCount": payload["triggeredCount"],
            "simulatedCount": payload["simulatedCount"],
            "submittedCount": payload["submittedCount"],
            "refusedCount": payload["refusedCount"],
            "intents": payload["intents"],
        }

    def historical_import_summary(self, environment: Environment) -> dict[str, Any]:
        """Return historical Polymarket import status for operations UI.

        REQ: REQ-DAT-009, REQ-UI-004, REQ-OBS-005
        """

        try:
            gamma_markets = self.registry.shared().polymarket_gamma_markets(environment=environment)
            chain_fills = self.registry.shared().polymarket_chain_fill_events(environment=environment)
            trades = self.registry.shared().polymarket_trades(environment=environment)
            wallet_stats = self.registry.shared().polymarket_wallet_performance_stats(
                environment=environment
            )
            target_snapshots = self.registry.shared().polymarket_target_wallet_snapshots(
                environment=environment
            )
            checkpoints = self.registry.shared().historical_import_checkpoints(
                environment=environment
            )
            checkpoints = [
                row for row in checkpoints if _polymarket_history_checkpoint(row.get("source"))
            ]
            wallet_positions = [
                row
                for row in self.registry.state.rows(f"{SHARED_SCHEMA}.polymarket_wallet_positions")
                if row["environment"] == environment.value
            ]
        except PersistenceUnavailableError:
            return {
                "status": "unavailable",
                "message": "Historical import status is unavailable because persistence is offline.",
                "counts": _empty_historical_import_counts(),
                "checkpoints": [],
                "lastUpdatedAt": None,
            }

        checkpoints.sort(key=_historical_checkpoint_sort_key, reverse=True)
        counts = {
            "gammaMarkets": len(gamma_markets),
            "chainFills": len(chain_fills),
            "trades": len(trades),
            "walletPositions": len(wallet_positions),
            "walletStats": len(wallet_stats),
            "targetWalletSnapshots": len(target_snapshots),
            "checkpoints": len(checkpoints),
        }
        status = _historical_import_status(checkpoints=checkpoints, counts=counts)
        latest = checkpoints[0] if checkpoints else None
        return {
            "status": status,
            "message": _historical_import_message(status=status, counts=counts, latest=latest),
            "counts": counts,
            "checkpoints": [
                {
                    "id": row["id"],
                    "source": row["source"],
                    "cursorType": row["cursor_type"],
                    "cursorValue": row["cursor_value"],
                    "status": row["status"],
                    "lastSuccessAt": _isoformat_or_none(row.get("last_success_at")),
                    "updatedAt": _isoformat_or_none(row.get("updated_at")),
                    "metadata": row.get("metadata", {}),
                }
                for row in checkpoints[:10]
            ],
            "lastUpdatedAt": _isoformat_or_none(
                latest.get("updated_at") if latest else None
            ),
        }

    def broker_history_summary(self, environment: Environment) -> dict[str, Any]:
        """Return Alpaca broker history import status for operations UI.

        REQ: REQ-ALP-017, REQ-DAT-008, REQ-UI-004, REQ-OBS-005
        """

        try:
            orders = self.registry.shared().alpaca_historical_orders(environment=environment)
            fills = self.registry.shared().alpaca_historical_fills(environment=environment)
            positions = self.registry.shared().alpaca_historical_positions(environment=environment)
            account_snapshots = self.registry.shared().alpaca_broker_account_snapshots(
                environment=environment
            )
            bars = self.registry.shared().stock_bars(environment=environment)
            pnl_snapshots = self.registry.shared().alpaca_symbol_pnl_snapshots(
                environment=environment
            )
            checkpoints = [
                row
                for row in self.registry.shared().historical_import_checkpoints(
                    environment=environment
                )
                if _alpaca_history_checkpoint(row.get("source"))
            ]
        except PersistenceUnavailableError:
            return {
                "status": "unavailable",
                "message": "Broker history status is unavailable because persistence is offline.",
                "counts": _empty_broker_history_counts(),
                "checkpoints": [],
                "lastUpdatedAt": None,
            }

        checkpoints.sort(key=_historical_checkpoint_sort_key, reverse=True)
        counts = {
            "orders": len(orders),
            "fills": len(fills),
            "positions": len(positions),
            "accountSnapshots": len(account_snapshots),
            "bars": len(bars),
            "pnlSnapshots": len(pnl_snapshots),
            "checkpoints": len(checkpoints),
        }
        status = _historical_import_status(checkpoints=checkpoints, counts=counts)
        latest = checkpoints[0] if checkpoints else None
        return {
            "status": status,
            "message": _broker_history_message(status=status, counts=counts, latest=latest),
            "counts": counts,
            "checkpoints": [
                {
                    "id": row["id"],
                    "source": row["source"],
                    "cursorType": row["cursor_type"],
                    "cursorValue": row["cursor_value"],
                    "status": row["status"],
                    "lastSuccessAt": _isoformat_or_none(row.get("last_success_at")),
                    "updatedAt": _isoformat_or_none(row.get("updated_at")),
                    "metadata": row.get("metadata", {}),
                }
                for row in checkpoints[:10]
            ],
            "lastUpdatedAt": _isoformat_or_none(
                latest.get("updated_at") if latest else None
            ),
        }

    def pipeline_runs(
        self,
        environment: Environment,
        *,
        limit: int = 10,
        include_steps: bool = True,
    ) -> list[dict[str, Any]]:
        """Return recent loop runs with the user-visible processing stages.

        REQ: REQ-UI-008, REQ-DAT-008, REQ-OBS-005
        """

        try:
            run_row_limit = min(
                DASHBOARD_PIPELINE_RUN_ROW_LIMIT,
                max(1, int(limit)),
            )
            step_row_limit = min(
                DASHBOARD_PIPELINE_STEP_ROW_LIMIT,
                max(1, run_row_limit * 10),
            )
            rows = [
                row
                for row in self.registry.state.rows(
                    self.PIPELINE_RUNS_TABLE,
                    limit=run_row_limit,
                    newest_first=True,
                    filters={"environment": environment.value},
                )
                if row["environment"] == environment.value
            ]
            step_rows = (
                [
                    row
                    for row in self.registry.state.rows(
                        self.PIPELINE_STEPS_TABLE,
                        limit=step_row_limit,
                        newest_first=True,
                        filters={"environment": environment.value},
                    )
                    if row["environment"] == environment.value
                ]
                if include_steps
                else []
            )
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

    def pipeline_run_detail(
        self,
        environment: Environment,
        run_id: str,
    ) -> dict[str, Any] | None:
        """Return one pipeline run and the records created by each step."""

        try:
            run_rows = self.registry.state.rows(
                self.PIPELINE_RUNS_TABLE,
                limit=1,
                newest_first=True,
                filters={"environment": environment.value, "id": run_id},
            )
            step_rows = self.registry.state.rows(
                self.PIPELINE_STEPS_TABLE,
                limit=DASHBOARD_PIPELINE_STEP_ROW_LIMIT,
                newest_first=True,
                filters={"environment": environment.value, "run_id": run_id},
            )
        except PersistenceUnavailableError:
            return None
        if not run_rows:
            return None
        step_rows.sort(key=lambda step: step.get("step_order", 0))
        record_ids = list(
            dict.fromkeys(
                record_id
                for step in step_rows
                for record_id in step.get("record_ids", [])
            )
        )
        hydrated_records = self._pipeline_step_records(
            environment=environment,
            record_ids=record_ids,
        )
        records_by_id: dict[str, list[dict[str, Any]]] = {}
        for record in hydrated_records:
            records_by_id.setdefault(record["id"], []).append(record)
        return {
            "environment": environment.value,
            "run": self._pipeline_run_payload(run_rows[0], step_rows),
            "records": [
                {
                    "stepKey": step["step_key"],
                    "stepLabel": step["label"],
                    "recordIds": step.get("record_ids", []),
                    "recordCount": len(step.get("record_ids", [])),
                    "items": [
                        record
                        for record_id in step.get("record_ids", [])
                        for record in records_by_id.get(record_id, [])
                    ],
                }
                for step in step_rows
            ],
        }

    def tick_summary(
        self,
        environment: Environment,
        *,
        window_minutes: int = DEFAULT_TICK_SUMMARY_WINDOW_MINUTES,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return a cached AI summary of recent pipeline ticks."""

        now = datetime.now(UTC)
        window_minutes = max(1, min(24 * 60, int(window_minutes)))
        window_started_at = now - timedelta(minutes=window_minutes)
        recent_runs = self._recent_pipeline_runs(
            environment=environment,
            since=window_started_at,
        )
        latest_run_id = recent_runs[-1]["id"] if recent_runs else None
        if not force_refresh:
            cached = self._cached_tick_summary(
                environment=environment,
                window_minutes=window_minutes,
                latest_run_id=latest_run_id,
                run_count=len(recent_runs),
                now=now,
            )
            if cached is not None:
                return self._tick_summary_payload(cached)

        result = TickSummaryService(
            registry=self.registry,
            environ=getattr(self.settings, "runtime_env", {}),
        ).summarize(
            TickSummaryRequest(
                environment=environment,
                runs=recent_runs,
                window_minutes=window_minutes,
                generated_at=now,
            )
        )
        row = {
            "id": str(uuid4()),
            "environment": environment.value,
            "window_minutes": window_minutes,
            "window_started_at": window_started_at,
            "window_ended_at": now,
            "latest_run_id": latest_run_id,
            "run_count": len(recent_runs),
            "status": result.status,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "input_hash": result.input_hash,
            "summary_markdown": result.summary_markdown,
            "key_events": result.key_events,
            "warnings": result.warnings,
            "usage": result.usage,
            "error_code": result.error_code,
            "message": result.message,
            "created_at": now,
        }
        try:
            self.registry.state.insert(self.TICK_SUMMARIES_TABLE, row)
        except PersistenceUnavailableError:
            pass
        return self._tick_summary_payload(row)

    def market_data_pull(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        candidate_limit: int | None = None,
    ) -> dict[str, Any]:
        """Return the latest dashboard-visible market-data pull.

        REQ: REQ-DAT-001, REQ-DAT-008, REQ-OBS-005
        """

        selected_venue = str(config_payload.get("default_selected_venue", "unknown"))
        try:
            rows = self._market_data_rows(
                environment,
                venues=self._market_data_venues(config_payload),
            )
        except PersistenceUnavailableError:
            rows = []
        return self._market_data_summary_payload(
            environment=environment,
            config_payload=config_payload,
            rows=rows,
            selected_venue=selected_venue,
            candidate_limit=(
                self.MARKET_DATA_DASHBOARD_CANDIDATE_LIMIT
                if candidate_limit is None
                else candidate_limit
            ),
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

        now = datetime.now(UTC)
        ai_usage = self._ai_usage_summary(environment, config_payload)
        trading = self._trading_pnl_summary()
        aws_cost = self._aws_cost_summary(environment=environment, preferences=preferences)
        daily_aws = _as_money(aws_cost["dailyInfraCostEstimateUsd"])
        recorded_costs = _as_money(ai_usage["totalCostUsd"]) + daily_aws
        trading_total = _as_money(trading["totalPnlUsd"])
        net = trading_total - recorded_costs
        payload = {
            "environment": environment.value,
            "generatedAt": now.isoformat(),
            "trading": trading,
            "ai": ai_usage,
            "aws": aws_cost,
            "profitability": {
                "netAfterRecordedCostsUsd": _money(net),
                "status": "profitable" if net > 0 else ("losing" if net < 0 else "flat"),
                "costBasis": "trading P&L minus recorded AI cost and one day of AWS infrastructure cost",
            },
        }
        month_key = _month_key(now)
        month_rows = self._economics_snapshot_rows(environment, month_key=month_key)
        latest_snapshot = month_rows[0] if month_rows else None
        snapshot = latest_snapshot
        stored_message = "Recent economics snapshot reused for monthly cost history."
        if _economics_snapshot_due(latest_snapshot, now):
            recorded = self._record_economics_snapshot(
                environment=environment,
                payload=payload,
                created_at=now,
            )
            if recorded is not None:
                snapshot = recorded
                month_rows = [recorded, *month_rows]
                stored_message = "Economics snapshot stored for monthly cost history."
            else:
                snapshot = None
                stored_message = "Economics snapshot storage is unavailable."
        month_rows.sort(key=lambda row: row.get("created_at"), reverse=True)
        payload["history"] = {
            "source": self.ECONOMICS_SNAPSHOTS_TABLE,
            "stored": snapshot is not None,
            "latestSnapshotId": snapshot.get("id") if snapshot else None,
            "monthKey": month_key,
            "snapshotsThisMonth": len(month_rows),
            "snapshots": [self._economics_snapshot_payload(row) for row in month_rows[:31]],
            "message": stored_message,
        }
        return payload

    def economics_history(
        self,
        *,
        environment: Environment,
        month_key: str | None = None,
        limit: int = 31,
    ) -> dict[str, Any]:
        """Return stored economics snapshots for a month.

        REQ: REQ-UI-010, REQ-OBS-005
        """

        selected_month = _normalize_month_key(month_key)
        rows = self._economics_snapshot_rows(environment, month_key=selected_month)
        rows.sort(key=lambda row: row.get("created_at"), reverse=True)
        capped_limit = min(max(1, int(limit)), 366)
        snapshots = [
            self._economics_snapshot_payload(row)
            for row in rows[:capped_limit]
        ]
        return {
            "environment": environment.value,
            "source": self.ECONOMICS_SNAPSHOTS_TABLE,
            "monthKey": selected_month,
            "count": len(snapshots),
            "snapshots": snapshots,
        }

    def trigger_ai_usage_import(
        self,
        *,
        username: str,
        ip_address: str,
        environment: Environment,
        provider: ModelProvider,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]:
        """Run provider-side token usage import for one provider and period."""

        result = self.ai_usage_importer.import_provider_usage(
            environment=environment,
            provider=provider,
            period_start=period_start,
            period_end=period_end,
            triggered_by=username,
        )
        audit_event = self.registry.shared().record_audit_event(
            event_type="ai_usage_import_trigger",
            actor=username,
            action="economics.ai_usage_import",
            environment=environment,
            entity_id=result.payload["id"],
            success=result.payload["status"] == "completed",
            metadata={
                "ip_address": ip_address,
                "provider": provider.value,
                "status": result.payload["status"],
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "imported_count": result.payload["importedCount"],
                "error_code": result.payload["errorCode"],
            },
        )
        payload = dict(result.payload)
        payload["auditEventId"] = audit_event["id"]
        return payload

    def loop_observability(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        config_degraded: bool = False,
        kill_switch_active: bool = False,
        market_data: dict[str, Any] | None = None,
        order_events: list[dict[str, Any]] | None = None,
        worker_status: dict[str, Any] | None = None,
        tick_schedule: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a dashboard-safe view of loop timing, inputs, gates, and logic.

        REQ: REQ-UI-004, REQ-OBS-005
        """

        now = datetime.now(UTC)
        worker = worker_status or self.worker_status()
        interval_seconds = _positive_int(
            config_payload.get("trading_loop_interval_seconds"),
            default=900,
        )
        resolved_tick_schedule = tick_schedule or self.tick_schedule(
            environment=environment,
            config_payload=config_payload,
            worker_status=worker,
        )
        next_run_at = _parse_datetime(resolved_tick_schedule.get("nextTickAt")) or now
        seconds_until_next_run = _as_int(resolved_tick_schedule.get("secondsUntilNextTick"))
        selected_venue = str(config_payload.get("default_selected_venue", "unknown"))
        venues = config_payload.get("venues", {})
        enabled_venues = self._enabled_config_venues(config_payload)
        enabled_venues_ready = bool(enabled_venues)
        enabled_venue_names = ", ".join(enabled_venues) or "none"
        live_enabled = bool(config_payload.get("live_enabled", False))
        credentials = self.credential_rows(environment)
        credential_blockers = self._loop_credential_blockers(credentials, enabled_venues)
        if order_events is None:
            order_events = self.order_events()
        open_orders = [
            item
            for item in order_events
            if item["state"] not in {"filled", "canceled", "failed", "refused"}
        ]
        status = self._loop_status(
            worker_state=str(worker["state"]),
            live_enabled=live_enabled,
            enabled_venues_ready=enabled_venues_ready,
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
        if market_data is None:
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
                "lastTickAt": resolved_tick_schedule.get("lastTickAt"),
                "lastTickStatus": resolved_tick_schedule.get("lastTickStatus"),
                "lastTickRunId": resolved_tick_schedule.get("lastTickRunId"),
                "lastTickSource": resolved_tick_schedule.get("lastTickSource"),
                "nextRunAt": next_run_at.isoformat(),
                "nextTickAt": resolved_tick_schedule.get("nextTickAt"),
                "secondsUntilNextRun": seconds_until_next_run,
                "secondsUntilNextTick": seconds_until_next_run,
                "due": resolved_tick_schedule.get("due", False),
                "source": worker.get("value"),
            },
            "currentPhase": self._current_loop_phase(
                worker_state=str(worker["state"]),
                live_enabled=live_enabled,
                enabled_venues_ready=enabled_venues_ready,
                credential_blockers=len(credential_blockers),
                kill_switch_active=kill_switch_active,
            ),
            "stages": self._loop_stages(
                worker_state=str(worker["state"]),
                config_degraded=config_degraded,
                live_enabled=live_enabled,
                enabled_venues_ready=enabled_venues_ready,
                credential_blockers=len(credential_blockers),
                kill_switch_active=kill_switch_active,
                order_count=len(order_events),
            ),
            "dataInputs": [
                {
                    "label": "Active venues",
                    "value": enabled_venue_names,
                    "state": "ok" if enabled_venues_ready else "blocked",
                    "detail": (
                        f"Default venue is {selected_venue}. Enabled venues are scanned and scored."
                    ),
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
                    "Active venues",
                    enabled_venues_ready,
                    enabled_venue_names,
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
                "auditEvents": self._audit_event_count(environment),
            },
        }

    def _loop_status(
        self,
        *,
        worker_state: str,
        live_enabled: bool,
        enabled_venues_ready: bool,
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
        if not enabled_venues_ready or credential_blockers:
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
        enabled_venues_ready: bool,
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
        if live_enabled and (not enabled_venues_ready or credential_blockers):
            return {
                "id": "gates",
                "label": "Pre-trade gates blocked",
                "state": "blocked",
                "detail": "Resolve active venue and credential blockers before live order submission.",
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
        enabled_venues_ready: bool,
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
                    enabled_venues_ready=enabled_venues_ready,
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
        enabled_venues_ready: bool,
        credential_blockers: int,
        kill_switch_active: bool,
    ) -> str:
        if kill_switch_active or (live_enabled and (not enabled_venues_ready or credential_blockers)):
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
        enabled_venues: list[str],
    ) -> list[dict[str, Any]]:
        required_venues = {item for item in enabled_venues}
        required_venues.add("llm")
        return [
            credential
            for credential in credentials
            if credential["requiredForLive"]
            and credential["venue"] in required_venues
            and not credential["present"]
        ]

    def _venue_credential_status(self, environment: Environment) -> dict[str, bool]:
        credentials = self.credential_rows(environment)
        status: dict[str, bool] = {}
        for venue in (Venue.POLYMARKET_US.value, Venue.POLYMARKET_INTERNATIONAL.value, Venue.ALPACA.value):
            required = [
                credential
                for credential in credentials
                if credential["venue"] == venue and credential["requiredForLive"]
            ]
            status[venue] = bool(required) and all(credential["present"] for credential in required)
            for credential in required:
                status[f"{venue}:{credential['provider']}"] = credential["present"]
        return status

    def _risk_value(self, risk_config: dict[str, Any], venue: str, field_name: str) -> str:
        value = risk_config.get(venue, {}).get(field_name)
        return str(value) if value is not None else "not configured"

    def _gate(self, label: str, passed: bool, value: str) -> dict[str, str]:
        return {"label": label, "state": "ok" if passed else "blocked", "value": value}

    def _audit_event_count(self, environment: Environment) -> int:
        try:
            return self.registry.state.count(
                f"{SHARED_SCHEMA}.audit_events",
                filters={"environment": environment.value},
            )
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
        scanner_run: dict[str, Any],
        reasoning_run: dict[str, Any],
        strategy_run: dict[str, Any],
        execution_run: dict[str, Any],
        exit_run: dict[str, Any],
        actor: str,
        requested_mode: str | None = None,
    ) -> dict[str, Any]:
        pull_status = _aggregate_market_data_pull_status([pull["status"] for pull in market_data_pulls])
        candidate_count = sum(_as_int(pull.get("candidateCount")) for pull in market_data_pulls)
        pipeline_status = _pipeline_run_status(pull_status)
        venue_names = [pull["venue"] for pull in market_data_pulls]
        end_result = {
            "status": pipeline_status,
            "marketDataStatus": pull_status,
            "candidateCount": candidate_count,
            "scannerAcceptedCount": scanner_run["acceptedCount"],
            "reasoningScoredCount": reasoning_run["scoredCount"],
            "strategyApprovedCount": strategy_run["approvedCount"],
            "orderIntentCount": execution_run["intentCount"],
            "orderSubmittedCount": execution_run["submittedCount"],
            "orderSimulatedCount": execution_run["simulatedCount"],
            "orderRefusedCount": execution_run["refusedCount"],
            "exitTriggeredCount": exit_run["triggeredCount"],
            "exitRefusedCount": exit_run["refusedCount"],
            "venues": venue_names,
        }
        run_row = {
            "id": run_id,
            "environment": environment.value,
            "trigger": trigger,
            "status": pipeline_status,
            "started_at": started_at,
            "completed_at": completed_at,
            "metadata": {
                "actor": actor,
                "requestedMode": requested_mode or trigger,
                "marketDataStatus": pull_status,
                "candidateCount": candidate_count,
                "scannerAcceptedCount": scanner_run["acceptedCount"],
                "scannerRejectedCount": scanner_run["rejectedCount"],
                "reasoningScoredCount": reasoning_run["scoredCount"],
                "reasoningSkippedCount": reasoning_run["skippedCount"],
                "reasoningFailedCount": reasoning_run["failedCount"],
                "strategyVoteCount": strategy_run["voteCount"],
                "strategyApprovedCount": strategy_run["approvedCount"],
                "strategyRefusedCount": strategy_run["refusedCount"],
                "orderIntentCount": execution_run["intentCount"],
                "orderSubmittedCount": execution_run["submittedCount"],
                "orderSimulatedCount": execution_run["simulatedCount"],
                "orderRefusedCount": execution_run["refusedCount"],
                "exitOpenPositionCount": exit_run["openPositionCount"],
                "exitTriggeredCount": exit_run["triggeredCount"],
                "exitRefusedCount": exit_run["refusedCount"],
                "venues": venue_names,
                "endResult": end_result,
            },
            "created_at": completed_at,
        }
        step_rows = self._pipeline_step_rows(
            environment=environment,
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            market_data_pulls=market_data_pulls,
            scanner_run=scanner_run,
            reasoning_run=reasoning_run,
            strategy_run=strategy_run,
            execution_run=execution_run,
            exit_run=exit_run,
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
        scanner_run: dict[str, Any],
        reasoning_run: dict[str, Any],
        strategy_run: dict[str, Any],
        execution_run: dict[str, Any],
        exit_run: dict[str, Any],
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
        scanner_status = _pipeline_scanner_status(str(scanner_run.get("status", "empty")))
        scanner_record_ids = [
            value
            for value in (
                [scanner_run.get("id")]
                + [candidate.get("id") for candidate in scanner_run.get("candidates", [])]
            )
            if value
        ]
        scanner_rejection_breakdown = _scanner_rejection_breakdown(scanner_run.get("candidates", []))
        scanner_message = str(
            scanner_run.get("message")
            or _scanner_step_message(scanner_run, scanner_rejection_breakdown)
        )
        reasoning_record_ids = [
            value
            for value in (
                [reasoning_run.get("id")]
                + [output.get("id") for output in reasoning_run.get("outputs", [])]
            )
            if value
        ]
        reasoning_message = _pipeline_reasoning_message(reasoning_run)
        strategy_record_ids = [
            value
            for value in (
                [strategy_run.get("id")]
                + [vote.get("id") for vote in strategy_run.get("votes", [])]
                + [output.get("id") for output in strategy_run.get("outputs", [])]
            )
            if value
        ]
        strategy_message = _pipeline_strategy_consensus_message(strategy_run)
        execution_record_ids = [
            value
            for value in (
                [execution_run.get("id")]
                + [intent.get("id") for intent in execution_run.get("intents", [])]
            )
            if value
        ]
        execution_message = _pipeline_execution_message(execution_run)
        exit_record_ids = [
            value
            for value in (
                [exit_run.get("id")]
                + [intent.get("id") for intent in exit_run.get("intents", [])]
            )
            if value
        ]
        exit_message = _pipeline_exit_message(exit_run)
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
                "inputs": {
                    "venues": venue_names,
                    "runId": run_id,
                },
                "outputs": {
                    "candidateCount": candidate_count,
                    "pulls": [
                        {
                            "id": pull.get("id"),
                            "venue": pull.get("venue"),
                            "status": pull.get("status"),
                            "candidateCount": pull.get("candidateCount", 0),
                            "errorCode": pull.get("errorCode"),
                        }
                        for pull in market_data_pulls
                    ],
                },
                "decisions": {
                    "accepted": market_data_status in {"pulled", "partial"},
                    "status": market_data_status,
                    "messages": [
                        pull.get("message")
                        for pull in market_data_pulls
                        if pull.get("message")
                    ][:10],
                },
            },
            "scanner": {
                "status": scanner_status,
                "message": scanner_message,
                "metrics": {
                    "candidateCount": scanner_run.get("candidateCount", candidate_count),
                    "acceptedCount": scanner_run["acceptedCount"],
                    "rejectedCount": scanner_run["rejectedCount"],
                    "rejectionBreakdown": scanner_rejection_breakdown,
                },
                "record_ids": scanner_record_ids,
                "inputs": {
                    "sourcePullIds": scanner_run.get("sourcePullIds", pull_ids),
                    "candidateCount": scanner_run.get("candidateCount", candidate_count),
                },
                "outputs": {
                    "scannerRunId": scanner_run.get("id"),
                    "acceptedCount": scanner_run.get("acceptedCount", 0),
                    "rejectedCount": scanner_run.get("rejectedCount", 0),
                    "rejectionBreakdown": scanner_rejection_breakdown,
                },
                "decisions": {
                    "status": scanner_run.get("status"),
                    "rejectionBreakdown": scanner_rejection_breakdown,
                    "candidates": _compact_candidate_decisions(scanner_run.get("candidates", [])),
                },
            },
            "brain": {
                "status": _pipeline_reasoning_status(str(reasoning_run.get("status", "idle"))),
                "message": reasoning_message,
                "metrics": {
                    "providerCount": reasoning_run.get("providerCount", 0),
                    "promptCount": reasoning_run.get("promptCount", 0),
                    "scoredCount": reasoning_run.get("scoredCount", 0),
                    "skippedCount": reasoning_run.get("skippedCount", 0),
                    "failedCount": reasoning_run.get("failedCount", 0),
                },
                "record_ids": reasoning_record_ids,
                "inputs": {
                    "scannerRunId": reasoning_run.get("scannerRunId"),
                    "providerCount": reasoning_run.get("providerCount", 0),
                    "promptCount": reasoning_run.get("promptCount", 0),
                },
                "outputs": {
                    "reasoningRunId": reasoning_run.get("id"),
                    "scoredCount": reasoning_run.get("scoredCount", 0),
                    "skippedCount": reasoning_run.get("skippedCount", 0),
                    "failedCount": reasoning_run.get("failedCount", 0),
                },
                "decisions": {
                    "status": reasoning_run.get("status"),
                    "outputs": _compact_reasoning_decisions(reasoning_run.get("outputs", [])),
                },
            },
            "execution": {
                "status": _pipeline_lifecycle_status(str(execution_run.get("status", "idle"))),
                "message": execution_message,
                "metrics": {
                    "voteCount": strategy_run.get("voteCount", 0),
                    "approvedCount": strategy_run.get("approvedCount", 0),
                    "refusedCount": strategy_run.get("refusedCount", 0),
                    "orderIntentCount": execution_run.get("intentCount", 0),
                    "submittedCount": execution_run.get("submittedCount", 0),
                    "simulatedCount": execution_run.get("simulatedCount", 0),
                    "orderRefusedCount": execution_run.get("refusedCount", 0),
                },
                "record_ids": strategy_record_ids + execution_record_ids,
                "inputs": {
                    "strategyConsensusRunId": strategy_run.get("id"),
                    "executionRunId": execution_run.get("id"),
                    "approvedCount": strategy_run.get("approvedCount", 0),
                    "voteCount": strategy_run.get("voteCount", 0),
                },
                "outputs": {
                    "intentCount": execution_run.get("intentCount", 0),
                    "submittedCount": execution_run.get("submittedCount", 0),
                    "simulatedCount": execution_run.get("simulatedCount", 0),
                    "refusedCount": execution_run.get("refusedCount", 0),
                },
                "decisions": {
                    "strategyStatus": strategy_run.get("status"),
                    "executionStatus": execution_run.get("status"),
                    "consensus": _compact_strategy_decisions(strategy_run.get("outputs", [])),
                    "intents": _compact_intent_decisions(execution_run.get("intents", [])),
                },
            },
            "exit": {
                "status": _pipeline_exit_status(str(exit_run.get("status", "idle"))),
                "message": exit_message,
                "metrics": {
                    "openPositionCount": exit_run.get("openPositionCount", 0),
                    "triggeredCount": exit_run.get("triggeredCount", 0),
                    "simulatedCount": exit_run.get("simulatedCount", 0),
                    "submittedCount": exit_run.get("submittedCount", 0),
                    "exitRefusedCount": exit_run.get("refusedCount", 0),
                },
                "record_ids": exit_record_ids,
                "inputs": {
                    "exitRunId": exit_run.get("id"),
                    "openPositionCount": exit_run.get("openPositionCount", 0),
                },
                "outputs": {
                    "triggeredCount": exit_run.get("triggeredCount", 0),
                    "submittedCount": exit_run.get("submittedCount", 0),
                    "simulatedCount": exit_run.get("simulatedCount", 0),
                    "refusedCount": exit_run.get("refusedCount", 0),
                },
                "decisions": {
                    "status": exit_run.get("status"),
                    "intents": _compact_intent_decisions(exit_run.get("intents", [])),
                },
            },
        }
        rows = []
        for key, order, label in self.PIPELINE_STAGES:
            payload = stage_payloads[key]
            metrics = dict(payload["metrics"])
            metrics["trace"] = {
                "inputs": payload["inputs"],
                "outputs": payload["outputs"],
                "decisions": payload["decisions"],
            }
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
                    "metrics": metrics,
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
        metadata = dict(row.get("metadata", {}))
        if "endResult" not in metadata:
            metadata["endResult"] = _pipeline_end_result(metadata, row.get("status"))
        return {
            "id": row["id"],
            "environment": row["environment"],
            "trigger": row["trigger"],
            "status": row["status"],
            "startedAt": _isoformat_or_none(row.get("started_at")),
            "completedAt": _isoformat_or_none(row.get("completed_at")),
            "metadata": metadata,
            "steps": [
                self._pipeline_step_payload(step)
                for step in steps
            ],
        }

    def _pipeline_step_payload(self, step: dict[str, Any]) -> dict[str, Any]:
        metrics = step.get("metrics", {})
        trace = metrics.get("trace", {}) if isinstance(metrics, dict) else {}
        return {
            "id": step["id"],
            "key": step["step_key"],
            "order": step["step_order"],
            "label": step["label"],
            "status": step["status"],
            "startedAt": _isoformat_or_none(step.get("started_at")),
            "completedAt": _isoformat_or_none(step.get("completed_at")),
            "message": step.get("message"),
            "metrics": _metrics_without_trace(metrics),
            "inputs": trace.get("inputs", {}) if isinstance(trace, dict) else {},
            "outputs": trace.get("outputs", {}) if isinstance(trace, dict) else {},
            "decisions": trace.get("decisions", {}) if isinstance(trace, dict) else {},
            "recordIds": step.get("record_ids", []),
        }

    def _recent_pipeline_runs(
        self,
        *,
        environment: Environment,
        since: datetime,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        runs = self.pipeline_runs(environment, limit=limit)
        recent: list[dict[str, Any]] = []
        for run in runs:
            started_at = _parse_datetime(run.get("startedAt"))
            completed_at = _parse_datetime(run.get("completedAt"))
            observed_at = started_at or completed_at
            if observed_at is None or observed_at >= since:
                recent.append(run)
        recent.sort(key=lambda run: _parse_datetime(run.get("startedAt")) or datetime.min.replace(tzinfo=UTC))
        return recent

    def _cached_tick_summary(
        self,
        *,
        environment: Environment,
        window_minutes: int,
        latest_run_id: str | None,
        run_count: int,
        now: datetime,
    ) -> dict[str, Any] | None:
        try:
            rows = [
                row
                for row in self.registry.state.rows(
                    self.TICK_SUMMARIES_TABLE,
                    limit=DASHBOARD_TICK_SUMMARY_ROW_LIMIT,
                    newest_first=True,
                    filters={"environment": environment.value},
                )
                if row.get("environment") == environment.value
                and row.get("window_minutes") == window_minutes
                and row.get("latest_run_id") == latest_run_id
                and row.get("run_count") == run_count
            ]
        except PersistenceUnavailableError:
            return None
        default_cache_seconds = (
            24 * 60 * 60
            if window_minutes >= 24 * 60
            else DEFAULT_TICK_SUMMARY_CACHE_SECONDS
        )
        cache_seconds = _positive_int(
            getattr(self.settings, "runtime_env", {}).get("OPENAI_TICK_SUMMARY_CACHE_SECONDS"),
            default_cache_seconds,
        )
        fresh_rows = []
        for row in rows:
            created_at = _parse_datetime(row.get("created_at"))
            if created_at is not None and (now - created_at).total_seconds() <= cache_seconds:
                fresh_rows.append(row)
        if not fresh_rows:
            return None
        fresh_rows.sort(key=lambda row: _parse_datetime(row.get("created_at")) or datetime.min.replace(tzinfo=UTC), reverse=True)
        return fresh_rows[0]

    def _tick_summary_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "environment": row.get("environment"),
            "status": row.get("status"),
            "windowMinutes": row.get("window_minutes"),
            "windowStartedAt": _isoformat_or_none(row.get("window_started_at")),
            "windowEndedAt": _isoformat_or_none(row.get("window_ended_at")),
            "latestRunId": row.get("latest_run_id"),
            "runCount": row.get("run_count", 0),
            "model": row.get("model"),
            "promptVersion": row.get("prompt_version"),
            "inputHash": row.get("input_hash"),
            "summaryMarkdown": row.get("summary_markdown", ""),
            "keyEvents": row.get("key_events", []),
            "warnings": row.get("warnings", []),
            "usage": row.get("usage", {}),
            "errorCode": row.get("error_code"),
            "message": row.get("message", ""),
            "generatedAt": _isoformat_or_none(row.get("created_at")),
        }

    def _pipeline_step_records(
        self,
        *,
        environment: Environment,
        record_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not record_ids:
            return []
        wanted = set(record_ids)
        tables = [
            self.MARKET_DATA_PULLS_TABLE,
            self.SCANNER_RUNS_TABLE,
            self.SCANNER_CANDIDATES_TABLE,
            self.REASONING_RUNS_TABLE,
            self.REASONING_OUTPUTS_TABLE,
            self.STRATEGY_CONSENSUS_RUNS_TABLE,
            self.STRATEGY_VOTES_TABLE,
            self.STRATEGY_CONSENSUS_OUTPUTS_TABLE,
            self.EXECUTION_RUNS_TABLE,
            self.ORDER_INTENTS_TABLE,
            self.EXIT_RUNS_TABLE,
            self.EXIT_INTENTS_TABLE,
            self.AI_USAGE_EVENTS_TABLE,
            self.ECONOMICS_SNAPSHOTS_TABLE,
        ]
        records: list[dict[str, Any]] = []
        for table in tables:
            try:
                rows = self.registry.state.rows(
                    table,
                    limit=DASHBOARD_PIPELINE_RECORD_ROW_LIMIT,
                    newest_first=True,
                    filters={"environment": environment.value},
                    ids=wanted,
                )
            except PersistenceUnavailableError:
                continue
            for row in rows:
                if row.get("id") in wanted and row.get("environment", environment.value) == environment.value:
                    records.append(
                        {
                            "table": table,
                            "id": row.get("id"),
                            "record": _safe_record_payload(row),
                        }
                    )
        records.sort(key=lambda row: record_ids.index(row["id"]) if row["id"] in wanted else len(record_ids))
        return records

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

    def _market_data_rows(
        self,
        environment: Environment,
        *,
        venues: list[str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        missing_venues: list[str] = []
        for venue in venues:
            venue_rows = self.registry.state.rows(
                self.MARKET_DATA_PULLS_TABLE,
                limit=1,
                newest_first=True,
                filters={"environment": environment.value, "venue": venue},
            )
            if venue_rows:
                rows.extend(venue_rows)
            else:
                missing_venues.append(venue)

        for venue in missing_venues:
            rows.extend(
                self.registry.state.rows(
                    self.LEGACY_MARKET_DATA_PULLS_TABLE,
                    limit=1,
                    newest_first=True,
                    filters={"environment": environment.value, "venue": venue},
                )
            )
        return rows

    def _data_explorer_rows(
        self,
        environment: Environment,
        dataset_id: str,
        *,
        limit: int = DASHBOARD_DATA_EXPLORER_ROW_LIMIT,
    ) -> list[dict[str, Any]]:
        metadata = DATA_EXPLORER_DATASETS.get(dataset_id)
        if metadata is None:
            raise ValueError(f"unsupported dataset: {dataset_id}")
        bounded_limit = min(max(1, int(limit)), DASHBOARD_DATA_EXPLORER_ROW_LIMIT)
        try:
            rows = [
                row
                for row in self.registry.state.rows(
                    metadata["table"],
                    limit=bounded_limit,
                    newest_first=True,
                    filters={"environment": environment.value},
                )
                if row.get("environment", environment.value) == environment.value
            ]
            if dataset_id == "market_data_pulls" and not rows:
                rows = [
                    row
                    for row in self.registry.state.rows(
                        self.LEGACY_MARKET_DATA_PULLS_TABLE,
                        limit=bounded_limit,
                        newest_first=True,
                        filters={"environment": environment.value},
                    )
                    if row.get("environment", environment.value) == environment.value
                ]
        except PersistenceUnavailableError:
            return []
        rows.sort(key=_row_datetime_sort_key, reverse=True)
        return rows

    def _explorer_rows_for_query(
        self,
        environment: Environment,
        parsed: dict[str, Any],
        *,
        row_limit: int = DASHBOARD_DATA_EXPLORER_ROW_LIMIT,
    ) -> list[dict[str, Any]]:
        dataset_id = str(parsed["dataset"])
        base_alias = str(parsed.get("alias") or dataset_id)
        rows = [
            _explorer_row_payload(row)
            for row in self._data_explorer_rows(environment, dataset_id, limit=row_limit)
        ]
        joins = parsed.get("joins", [])
        if not joins:
            return rows

        joined_rows = [{base_alias: row} for row in rows]
        for join in joins:
            join_alias = str(join["alias"])
            join_rows = [
                _explorer_row_payload(row)
                for row in self._data_explorer_rows(
                    environment,
                    str(join["dataset"]),
                    limit=row_limit,
                )
            ]
            next_rows: list[dict[str, Any]] = []
            for current_row in joined_rows:
                for join_row in join_rows:
                    candidate = {**current_row, join_alias: join_row}
                    if _nested_explorer_value(candidate, join["left"]) == _nested_explorer_value(candidate, join["right"]):
                        next_rows.append(candidate)
            joined_rows = next_rows
        return joined_rows

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

    def _scheduled_market_data_fetch_order(self, config_payload: dict[str, Any]) -> list[str]:
        venues = self._market_data_venues(config_payload)
        selected_venue = str(
            config_payload.get("default_selected_venue")
            or self.settings.default_selected_venue.value
        )
        if selected_venue not in venues or len(venues) < 2:
            return venues
        return [venue for venue in venues if venue != selected_venue] + [selected_venue]

    def _enabled_config_venues(self, config_payload: dict[str, Any]) -> list[str]:
        supported = [
            Venue.POLYMARKET_US.value,
            Venue.POLYMARKET_INTERNATIONAL.value,
            Venue.ALPACA.value,
        ]
        return [venue for venue in supported if self._venue_enabled(venue, config_payload)]

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
        candidate_limit: int | None = None,
    ) -> dict[str, Any]:
        venues = self._market_data_venues(config_payload)
        venue_payloads = []
        for venue in venues:
            venue_rows = [row for row in rows if row["venue"] == venue]
            if venue_rows:
                venue_payloads.append(
                    self._market_data_payload(
                        max(venue_rows, key=lambda row: row["created_at"]),
                        candidate_limit=candidate_limit,
                    )
                )
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
            summary = self._market_data_payload(latest, candidate_limit=candidate_limit)
            summary["message"] = (
                f"Latest market data pull records are shown for {len(venue_payloads)} enabled venue"
                f"{'' if len(venue_payloads) == 1 else 's'}."
            )

        all_candidates = [
            candidate
            for venue_payload in venue_payloads
            for candidate in venue_payload["candidates"]
        ]
        total_candidate_count = sum(
            venue_payload["candidateCount"] for venue_payload in venue_payloads
        )
        summary["status"] = _aggregate_market_data_pull_status(
            [venue_payload["status"] for venue_payload in venue_payloads]
        )
        summary["candidateCount"] = total_candidate_count
        summary["candidates"] = (
            all_candidates[:candidate_limit]
            if candidate_limit is not None
            else all_candidates
        )
        summary["venues"] = venue_payloads
        return summary

    def _market_data_payload(
        self,
        row: dict[str, Any],
        *,
        candidate_limit: int | None = None,
    ) -> dict[str, Any]:
        raw_candidates = row.get("candidates", [])
        limited_candidates = (
            raw_candidates[:candidate_limit]
            if candidate_limit is not None
            else raw_candidates
        )
        candidates = [_safe_candidate_payload(candidate) for candidate in limited_candidates]
        return {
            "id": row["id"],
            "environment": row["environment"],
            "venue": row["venue"],
            "status": row["status"],
            "trigger": row.get("trigger", "unknown"),
            "source": row.get("source", "dashboard store"),
            "lastPulledAt": row["created_at"].isoformat(),
            "candidateCount": len(raw_candidates),
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

    def _record_economics_snapshot(
        self,
        *,
        environment: Environment,
        payload: dict[str, Any],
        created_at: datetime,
    ) -> dict[str, Any] | None:
        try:
            return self.registry.shared().record_economics_snapshot(
                environment=environment,
                month_key=_month_key(created_at),
                trading_realized_pnl_usd=_as_money(payload["trading"]["realizedPnlUsd"]),
                trading_unrealized_pnl_usd=_as_money(payload["trading"]["unrealizedPnlUsd"]),
                trading_total_pnl_usd=_as_money(payload["trading"]["totalPnlUsd"]),
                ai_cost_usd=_as_money(payload["ai"]["totalCostUsd"]),
                ai_prompt_tokens=_as_int(payload["ai"]["promptTokens"]),
                ai_completion_tokens=_as_int(payload["ai"]["completionTokens"]),
                ai_total_tokens=_as_int(payload["ai"]["totalTokens"]),
                aws_daily_cost_usd=_as_money(payload["aws"]["dailyInfraCostEstimateUsd"]),
                aws_month_to_date_cost_usd=_as_money(payload["aws"]["monthToDateCostUsd"]),
                aws_source=str(payload["aws"]["source"]),
                aws_scope=str(payload["aws"]["scope"]),
                aws_estimated=bool(payload["aws"]["estimated"]),
                net_after_costs_usd=_as_money(payload["profitability"]["netAfterRecordedCostsUsd"]),
                profitability_status=str(payload["profitability"]["status"]),
                payload=payload,
                created_at=created_at,
            )
        except PersistenceUnavailableError:
            return None

    def _economics_snapshot_rows(
        self,
        environment: Environment,
        *,
        month_key: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            rows = [
                row
                for row in self.registry.state.rows(
                    self.ECONOMICS_SNAPSHOTS_TABLE,
                    limit=DASHBOARD_ECONOMICS_SNAPSHOT_ROW_LIMIT,
                    newest_first=True,
                    filters={"environment": environment.value},
                )
                if row["environment"] == environment.value
            ]
            if month_key is not None:
                rows = [row for row in rows if row["month_key"] == month_key]
            return rows
        except PersistenceUnavailableError:
            return []

    def _economics_snapshot_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "environment": row["environment"],
            "monthKey": row["month_key"],
            "createdAt": _isoformat_or_none(row.get("created_at")),
            "tradingPnlUsd": _money(_as_money(row.get("trading_total_pnl_usd", "0"))),
            "aiCostUsd": _money(_as_money(row.get("ai_cost_usd", "0"))),
            "aiPromptTokens": _as_int(row.get("ai_prompt_tokens")),
            "aiCompletionTokens": _as_int(row.get("ai_completion_tokens")),
            "aiTotalTokens": _as_int(row.get("ai_total_tokens")),
            "awsDailyCostUsd": _money(_as_money(row.get("aws_daily_cost_usd", "0"))),
            "awsMonthToDateCostUsd": _money(_as_money(row.get("aws_month_to_date_cost_usd", "0"))),
            "awsSource": row.get("aws_source", "unknown"),
            "awsScope": row.get("aws_scope", "unknown"),
            "awsEstimated": bool(row.get("aws_estimated", True)),
            "netAfterRecordedCostsUsd": _money(_as_money(row.get("net_after_costs_usd", "0"))),
            "status": row.get("profitability_status", "unknown"),
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
        all_usage_rows: list[dict[str, Any]] = []
        import_runs = self._ai_usage_import_rows(environment)
        for provider in ModelProvider:
            rows = self._ai_usage_rows(environment, provider)
            all_usage_rows.extend(rows)
            prompt_tokens = sum(_as_int(row.get("prompt_tokens")) for row in rows)
            completion_tokens = sum(_as_int(row.get("completion_tokens")) for row in rows)
            provider_cost = sum((_as_money(row.get("cost_usd", "0")) for row in rows), Decimal("0"))
            total_prompt_tokens += prompt_tokens
            total_completion_tokens += completion_tokens
            total_cost += provider_cost
            budget = config_payload.get("llm", {}).get(provider.value, {}).get("budget_usd", "0.00")
            provider_imports = [row for row in import_runs if row.get("provider") == provider.value]
            provider_imports.sort(key=_row_datetime_sort_key, reverse=True)
            providers.append(
                {
                    "provider": provider.value,
                    "models": sorted({str(row.get("model")) for row in rows if row.get("model")}),
                    "promptTokens": prompt_tokens,
                    "completionTokens": completion_tokens,
                    "totalTokens": prompt_tokens + completion_tokens,
                    "costUsd": _money(provider_cost),
                    "budgetUsd": _money(_as_money(budget)),
                    "events": len(rows),
                    "importedEvents": len(
                        [row for row in rows if row.get("usage_source") == "provider_backfill"]
                    ),
                    "estimatedEvents": len(
                        [row for row in rows if str(row.get("usage_source", "")).startswith("estimated")]
                    ),
                    "usageSources": sorted(
                        {str(row.get("usage_source", "recorded")) for row in rows}
                    ),
                    "costSources": sorted(
                        {str(row.get("cost_source", "recorded")) for row in rows}
                    ),
                    "latestAt": _isoformat_or_none(
                        max(
                            (row.get("created_at") for row in rows if row.get("created_at")),
                            default=None,
                        )
                    ),
                    "latestImportStatus": provider_imports[0]["status"] if provider_imports else "not_configured",
                    "latestImportMessage": provider_imports[0]["message"] if provider_imports else None,
                }
            )
        all_usage_rows.sort(key=_row_datetime_sort_key, reverse=True)
        import_runs.sort(key=_row_datetime_sort_key, reverse=True)
        latest_usage = all_usage_rows[0] if all_usage_rows else None
        latest_import = import_runs[0] if import_runs else None
        return {
            "providers": providers,
            "promptTokens": total_prompt_tokens,
            "completionTokens": total_completion_tokens,
            "totalTokens": total_prompt_tokens + total_completion_tokens,
            "totalCostUsd": _money(total_cost),
            "source": self.AI_USAGE_EVENTS_TABLE,
            "freshness": {
                "latestUsageAt": _isoformat_or_none(latest_usage.get("created_at") if latest_usage else None),
                "latestImportAt": _isoformat_or_none(
                    latest_import.get("completed_at") if latest_import else None
                ),
                "status": "current" if latest_usage or latest_import else "empty",
            },
            "imports": {
                "source": self.AI_USAGE_IMPORT_RUNS_TABLE,
                "count": len(import_runs),
                "runs": [self._ai_usage_import_payload(row) for row in import_runs[:25]],
            },
            "errorState": _ai_usage_error_state(import_runs),
        }

    def _ai_usage_rows(self, environment: Environment, provider: ModelProvider) -> list[dict[str, Any]]:
        try:
            rows = [
                row
                for row in self.registry.state.rows(
                    self.AI_USAGE_EVENTS_TABLE,
                    limit=DASHBOARD_AI_USAGE_ROW_LIMIT,
                    newest_first=True,
                    filters={"environment": environment.value},
                )
                if row["environment"] == environment.value
            ]
        except PersistenceUnavailableError:
            return []
        return [row for row in rows if row["provider"] == provider.value]

    def _ai_usage_import_rows(self, environment: Environment) -> list[dict[str, Any]]:
        try:
            return [
                row
                for row in self.registry.state.rows(
                    self.AI_USAGE_IMPORT_RUNS_TABLE,
                    limit=DASHBOARD_AI_USAGE_IMPORT_ROW_LIMIT,
                    newest_first=True,
                    filters={"environment": environment.value},
                )
                if row["environment"] == environment.value
            ]
        except PersistenceUnavailableError:
            return []

    def _ai_usage_import_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "environment": row["environment"],
            "provider": row["provider"],
            "status": row["status"],
            "source": row["source"],
            "periodStart": _isoformat_or_none(row.get("period_start")),
            "periodEnd": _isoformat_or_none(row.get("period_end")),
            "importedCount": _as_int(row.get("imported_count")),
            "errorCode": row.get("error_code"),
            "message": row.get("message"),
            "startedAt": _isoformat_or_none(row.get("started_at")),
            "completedAt": _isoformat_or_none(row.get("completed_at")),
            "createdAt": _isoformat_or_none(row.get("created_at")),
        }

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
                rows = self.registry.state.rows(
                    f"{provider.value}.positions",
                    limit=DASHBOARD_PNL_POSITION_ROW_LIMIT,
                    newest_first=True,
                )
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
                rows = self.registry.state.rows(
                    table,
                    limit=DASHBOARD_ORDER_EVENT_ROW_LIMIT,
                    newest_first=True,
                )
            except PersistenceUnavailableError:
                continue
            for row in rows:
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

    # REQ: REQ-EXE-016
    def order_history(
        self,
        environment: Environment,
        *,
        limit: int = DASHBOARD_ORDER_HISTORY_PAGE_SIZE,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Return durable order intents for the selected environment.

        Traces: REQ-EXE-016
        Tests: TST-REQ-EXE-016-11, TST-REQ-EXE-016-12
        """

        bounded_limit = min(max(1, int(limit)), DASHBOARD_ORDER_HISTORY_ROW_LIMIT)
        before = _decode_order_history_cursor(cursor)
        rows = self.registry.state.rows(
            f"{SHARED_SCHEMA}.order_intents",
            filters={"environment": environment.value},
            limit=bounded_limit + 1,
            before=before,
            newest_first=True,
        )
        has_more = len(rows) > bounded_limit
        items = [
            {
                "id": str(row.get("id", "")),
                "state": str(row.get("status", "unknown")),
                "venue": str(row.get("venue", "")),
                "provider": str(row.get("model_provider", "")),
                "side": str(row.get("side", "")),
                "instrumentId": str(row.get("instrument_id", "")),
                "orderType": str(row.get("order_type", "")),
                "notionalUsd": _fixed_decimal_or_none(row.get("notional_usd")),
                "venueOrderId": row.get("venue_order_id"),
                "message": _order_history_message(row),
                "createdAt": _isoformat_or_none(row.get("created_at")),
                "updatedAt": _isoformat_or_none(row.get("updated_at")),
            }
            for row in rows[:bounded_limit]
        ]
        next_cursor = (
            _encode_order_history_cursor(rows[bounded_limit - 1])
            if has_more
            else None
        )
        return items, next_cursor

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
        alternative_required_names: tuple[str, ...] = (),
        account_status: str = "active",
        purpose: str | None = None,
    ) -> RuntimeCredentialView:
        required_present = all(_configured(self.settings.runtime_env.get(name, "")) for name in required_names)
        alternative_present = (
            True
            if not alternative_required_names
            else any(_configured(self.settings.runtime_env.get(name, "")) for name in alternative_required_names)
        )
        present = enabled and required_present and alternative_present
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
            missing = _missing_credential_message(
                runtime_env=self.settings.runtime_env,
                required_names=required_names,
                alternative_required_names=alternative_required_names,
            )
            message = f"{missing} for {purpose}" if purpose else missing
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


def _polymarket_historical_import_config(settings: Any) -> dict[str, Any]:
    rpc_url = str(getattr(settings, "polygon_rpc_url", "") or "").strip()
    return {
        "source": "clean_room_polygon_order_filled",
        "polygon_rpc_configured": _configured(rpc_url),
        "max_block_range": max(1, int(getattr(settings, "polygon_order_filled_max_block_range", 500))),
        "max_windows": max(1, int(getattr(settings, "polygon_order_filled_max_windows", 1))),
        "import_cadence_minutes": max(
            1,
            int(getattr(settings, "polygon_order_filled_import_cadence_minutes", 60)),
        ),
        "retry_policy": {
            "split_oversized_windows": bool(getattr(settings, "polygon_order_filled_retry_split", True)),
            "rate_limits_record_checkpoint": True,
        },
    }


def _alpaca_submitters_from_settings(settings: Any) -> dict[ModelProvider, Any]:
    runtime_env = getattr(settings, "runtime_env", {})
    if not bool(getattr(settings, "live_enabled", False)):
        return {}
    if not bool(getattr(settings, "alpaca_enabled", False)):
        return {}
    if str(getattr(settings, "alpaca_account_status", "active")).strip().lower() != "active":
        return {}
    submitters: dict[ModelProvider, Any] = {}
    for provider in TRADING_MODEL_PROVIDERS:
        provider_env = _provider_runtime_env(runtime_env, venue=Venue.ALPACA, provider=provider)
        if not _configured(provider_env.get("ALPACA_KEY_ID")):
            continue
        if not _configured(provider_env.get("ALPACA_SECRET_KEY")):
            continue
        try:
            submitters[provider] = alpaca_live_order_adapter_from_env(provider_env)
        except ValueError:
            continue
    return submitters


def _polymarket_submitters_from_settings(settings: Any) -> dict[ModelProvider, Any]:
    runtime_env = getattr(settings, "runtime_env", {})
    if not bool(getattr(settings, "live_enabled", False)):
        return {}
    if not bool(getattr(settings, "polymarket_us_enabled", False)):
        return {}
    submitters: dict[ModelProvider, Any] = {}
    for provider in TRADING_MODEL_PROVIDERS:
        provider_env = _provider_runtime_env(runtime_env, venue=Venue.POLYMARKET_US, provider=provider)
        if not _configured(provider_env.get("POLYMARKET_KEY_ID")):
            continue
        if not (
            _configured(provider_env.get("POLYMARKET_SECRET_KEY"))
            or _configured(provider_env.get("POLYMARKET_PRIVATE_KEY"))
        ):
            continue
        submitters[provider] = polymarket_us_live_adapter_from_env(provider_env)
    return submitters


def _provider_runtime_env(
    runtime_env: dict[str, str],
    *,
    venue: Venue,
    provider: ModelProvider,
) -> dict[str, str]:
    provider_key = provider.value.upper()
    provider_env = dict(runtime_env)
    if venue == Venue.ALPACA:
        provider_env["ALPACA_KEY_ID"] = runtime_env.get(f"ALPACA_{provider_key}_KEY_ID", "").strip()
        provider_env["ALPACA_SECRET_KEY"] = runtime_env.get(f"ALPACA_{provider_key}_SECRET_KEY", "").strip()
        return provider_env
    if venue == Venue.POLYMARKET_US:
        provider_env["POLYMARKET_KEY_ID"] = runtime_env.get(f"POLYMARKET_{provider_key}_KEY_ID", "").strip()
        provider_env["POLYMARKET_SECRET_KEY"] = runtime_env.get(
            f"POLYMARKET_{provider_key}_SECRET_KEY",
            "",
        ).strip()
        provider_env["POLYMARKET_PRIVATE_KEY"] = runtime_env.get(
            f"POLYMARKET_{provider_key}_PRIVATE_KEY",
            "",
        ).strip()
        provider_env["POLYMARKET_CREDENTIAL_REF"] = resolve_credential_ref(
            CredentialTarget(
                _environment_from_runtime_env(runtime_env),
                Venue.POLYMARKET_US,
                provider,
                "wallet",
            )
        )
    return provider_env


def _first_submitter(submitters: dict[ModelProvider, Any]) -> Any | None:
    for provider in TRADING_MODEL_PROVIDERS:
        if provider in submitters:
            return submitters[provider]
    return None


def _environment_from_runtime_env(runtime_env: dict[str, str]) -> Environment:
    raw = runtime_env.get("APP_ENV", Environment.LOCAL.value)
    try:
        return Environment(raw)
    except ValueError:
        return Environment.LOCAL


def _provider_label(provider: ModelProvider) -> str:
    if provider == ModelProvider.OPENAI:
        return "OpenAI"
    return "Claude"


def _missing_credential_message(
    *,
    runtime_env: dict[str, str],
    required_names: tuple[str, ...],
    alternative_required_names: tuple[str, ...],
) -> str:
    missing_required = [name for name in required_names if not _configured(runtime_env.get(name, ""))]
    if alternative_required_names and not any(
        _configured(runtime_env.get(name, "")) for name in alternative_required_names
    ):
        missing_required.append(" or ".join(alternative_required_names))
    if not missing_required:
        return "required credential value missing"
    return "missing " + ", ".join(missing_required)


def _manual_run_mode(value: str | None) -> str:
    normalized = str(value or "full_dry_run").strip().lower().replace("-", "_")
    allowed = {"data_import", "scanner_only", "full_dry_run", "full_live_gated"}
    return normalized if normalized in allowed else "full_dry_run"


def _config_for_manual_mode(config_payload: dict[str, Any], run_mode: str) -> dict[str, Any]:
    payload = deepcopy(config_payload)
    if run_mode != "full_live_gated":
        payload["live_enabled"] = False
        scanner = dict(payload.get("scanner") if isinstance(payload.get("scanner"), dict) else {})
        polymarket_scanner = dict(
            scanner.get("polymarket") if isinstance(scanner.get("polymarket"), dict) else {}
        )
        configured_market_limit = _positive_int(
            polymarket_scanner.get("market_data_limit"),
            default=MANUAL_NON_LIVE_POLYMARKET_MARKET_DATA_LIMIT,
        )
        polymarket_scanner["market_data_limit"] = min(
            configured_market_limit,
            MANUAL_NON_LIVE_POLYMARKET_MARKET_DATA_LIMIT,
        )
        scanner["polymarket"] = polymarket_scanner
        payload["scanner"] = scanner

        alpaca = dict(payload.get("alpaca") if isinstance(payload.get("alpaca"), dict) else {})
        resolved_symbols = resolve_alpaca_symbol_universe(payload) or list(DEFAULT_ALPACA_SYMBOL_UNIVERSE)
        limited_symbols = normalize_symbol_list(resolved_symbols[:MANUAL_NON_LIVE_ALPACA_SYMBOL_LIMIT])
        alpaca["symbol_presets"] = []
        alpaca["custom_symbols"] = limited_symbols
        alpaca["symbol_universe"] = limited_symbols
        payload["alpaca"] = alpaca
    return payload


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


def _month_key(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m")


def _economics_snapshot_due(latest_snapshot: dict[str, Any] | None, now: datetime) -> bool:
    if latest_snapshot is None:
        return True
    created_at = latest_snapshot.get("created_at")
    if not isinstance(created_at, datetime):
        return True
    return now - created_at.astimezone(UTC) >= timedelta(
        seconds=DASHBOARD_ECONOMICS_SNAPSHOT_MIN_INTERVAL_SECONDS
    )


def _normalize_month_key(value: str | None) -> str:
    if value is None:
        return _month_key(datetime.now(UTC))
    candidate = value.strip()
    parts = candidate.split("-")
    if len(parts) != 2:
        return _month_key(datetime.now(UTC))
    try:
        normalized = datetime(int(parts[0]), int(parts[1]), 1, tzinfo=UTC)
    except ValueError:
        return _month_key(datetime.now(UTC))
    return _month_key(normalized)


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
        "latestOpen": _optional_text(candidate.get("latestOpen")),
        "latestHigh": _optional_text(candidate.get("latestHigh")),
        "latestLow": _optional_text(candidate.get("latestLow")),
        "latestClose": _optional_text(candidate.get("latestClose")),
        "latestVolume": _optional_text(candidate.get("latestVolume")),
        "averageVolume": _optional_text(candidate.get("averageVolume")),
        "historyStart": _optional_text(candidate.get("historyStart")),
        "historyEnd": _optional_text(candidate.get("historyEnd")),
        "tokenId": _optional_text(candidate.get("tokenId")),
        "outcome": _optional_text(candidate.get("outcome")),
        "marketId": _optional_text(candidate.get("marketId")),
        "marketSlug": _optional_text(candidate.get("marketSlug") or candidate.get("market_slug")),
        "midpoint": _optional_text(candidate.get("midpoint")),
        "bestBid": _optional_text(candidate.get("bestBid")),
        "bestAsk": _optional_text(candidate.get("bestAsk")),
        "bidDepth": _optional_text(candidate.get("bidDepth")),
        "askDepth": _optional_text(candidate.get("askDepth")),
        "category": _optional_text(candidate.get("category")),
        "endDate": _optional_text(candidate.get("endDate")),
        "volume": _optional_text(candidate.get("volume")),
        "active": bool(candidate.get("active", True)),
        "closed": bool(candidate.get("closed", False)),
    }


def _safe_record_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            payload[key] = str(value)
        elif isinstance(value, datetime):
            payload[key] = value.isoformat()
        elif isinstance(value, dict):
            payload[key] = _safe_record_payload(value)
        elif isinstance(value, list):
            payload[key] = [
                _safe_record_payload(item)
                if isinstance(item, dict)
                else str(item)
                if isinstance(item, Decimal)
                else item
                for item in value
            ]
        else:
            payload[key] = value
    return payload


def _explorer_row_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = _safe_record_payload(row)
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        payload["candidate_count"] = len(candidates)
    return payload


def _explorer_columns(rows: list[dict[str, Any]], preferred: tuple[str, ...]) -> list[str]:
    columns = list(preferred)
    for row in rows:
        if _is_joined_explorer_row(row):
            for alias, payload in row.items():
                if not isinstance(payload, dict):
                    continue
                for key in payload:
                    column = f"{alias}.{key}"
                    if column not in columns:
                        columns.append(column)
            continue
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def _project_explorer_row(row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    return {column: _nested_explorer_value(row, column) for column in columns}


def _generate_explorer_query(prompt: str) -> dict[str, Any]:
    prompt_text = " ".join((prompt or "").strip().split())
    lower_prompt = prompt_text.lower()
    warnings = [
        "Generated SQL is limited to known dashboard datasets and read-only SELECT statements."
    ]
    if not prompt_text:
        query = "select * from market_data_pulls limit 25"
        explanation = "I generated the default market-data query because the prompt was empty."
        datasets = ["market_data_pulls"]
    elif "reasoning" in lower_prompt and "scanner" in lower_prompt:
        query = (
            "select sc.display_name, sc.status, sc.refusal_reason, ro.model_provider, "
            "ro.status, ro.confidence, ro.estimated_probability "
            "from scanner_candidates sc join reasoning_outputs ro on sc.id = ro.scanner_candidate_id "
            "order by ro.created_at desc limit 50"
        )
        explanation = "This joins scanner candidates to reasoning outputs so you can see what reached model scoring."
        datasets = ["scanner_candidates", "reasoning_outputs"]
    elif any(term in lower_prompt for term in ("scanner", "rejected", "refusal", "pass scanner", "passed scanner")):
        query = (
            "select display_name, venue, status, refusal_reason, spread, liquidity, hours_to_resolution "
            "from scanner_candidates order by created_at desc limit 50"
        )
        explanation = "This shows the scanner candidates and refusal reasons that decide whether a candidate moves forward."
        datasets = ["scanner_candidates"]
    elif any(term in lower_prompt for term in ("order", "trade", "execution", "intent")):
        query = (
            "select p.id, p.status, o.venue, o.instrument_id, o.side, o.status, o.notional_usd, o.refusal_reason "
            "from pipeline_runs p join order_intents o on p.id = o.pipeline_run_id "
            "order by o.created_at desc limit 50"
        )
        explanation = "This joins pipeline runs to order intents so you can inspect execution decisions."
        datasets = ["pipeline_runs", "order_intents"]
    elif any(term in lower_prompt for term in ("market data", "data pull", "provider", "venue")):
        query = (
            "select p.id, p.status, m.venue, m.status, m.candidate_count, m.message "
            "from pipeline_runs p join market_data_pulls m on p.id = m.run_id "
            "order by m.created_at desc limit 50"
        )
        explanation = "This joins market data pulls to their pipeline runs so provider data can be tied back to ticks."
        datasets = ["pipeline_runs", "market_data_pulls"]
    elif any(term in lower_prompt for term in ("step", "stage", "tick", "run")):
        query = (
            "select p.id, p.trigger, p.status, s.step_key, s.status, s.message "
            "from pipeline_runs p join pipeline_steps s on p.id = s.run_id "
            "order by s.created_at desc limit 50"
        )
        explanation = "This joins runs to their five pipeline steps so you can trace each tick."
        datasets = ["pipeline_runs", "pipeline_steps"]
    elif "summary" in lower_prompt:
        query = (
            "select latest_run_id, status, model, message, run_count, created_at "
            "from tick_summaries order by created_at desc limit 25"
        )
        explanation = "This shows recent tick summaries and the run window each summary covered."
        datasets = ["tick_summaries"]
    else:
        query = "select * from market_data_pulls limit 25"
        explanation = "I started with provider pulls because they are the first records created by each tick."
        datasets = ["market_data_pulls"]
    _parse_explorer_query(query)
    return {
        "query": query,
        "explanation": explanation,
        "datasets": datasets,
        "warnings": warnings,
    }


def _parse_explorer_query(query: str) -> dict[str, Any]:
    raw_query = (query or "").strip() or "select * from market_data_pulls limit 25"
    if ";" in raw_query.rstrip(";"):
        raise ValueError("only one read-only SELECT statement is allowed")
    normalized = raw_query.rstrip(";").strip()
    match = re.match(
        r"^select\s+(?P<columns>.+?)\s+from\s+(?P<body>.+)$",
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise ValueError("query must use SELECT columns FROM dataset")

    columns_text = match.group("columns").strip()
    columns = ["*"] if columns_text == "*" else [column.strip() for column in columns_text.split(",")]
    if columns != ["*"] and not all(_valid_explorer_identifier(column) for column in columns):
        raise ValueError("selected columns must be simple field names")

    rest = " ".join(match.group("body").split())
    limit = None
    order_by = None
    order_direction = "asc"

    limit_match = re.search(r"(?:^|\s+)limit\s+(?P<limit>\d+)\s*$", rest, flags=re.IGNORECASE)
    if limit_match:
        limit = int(limit_match.group("limit"))
        rest = rest[: limit_match.start()].strip()

    order_match = re.search(
        r"(?:^|\s+)order\s+by\s+(?P<field>[A-Za-z0-9_.]+)(?:\s+(?P<direction>asc|desc))?\s*$",
        rest,
        flags=re.IGNORECASE,
    )
    if order_match:
        order_by = order_match.group("field")
        order_direction = (order_match.group("direction") or "asc").lower()
        rest = rest[: order_match.start()].strip()

    conditions: list[dict[str, Any]] = []
    where_match = re.search(r"(?:^|\s+)where\s+", rest, flags=re.IGNORECASE)
    source_clause = rest
    if rest:
        if where_match:
            source_clause = rest[: where_match.start()].strip()
            where_clause = rest[where_match.end() :].strip()
            conditions = _parse_explorer_conditions(where_clause)
        elif re.search(r"(?:^|\s+)(join|on)\s+", rest, flags=re.IGNORECASE) is None:
            source_clause = rest
        else:
            source_clause = rest

    source = _parse_explorer_source_clause(source_clause)

    return {
        "columns": columns,
        "dataset": source["dataset"],
        "alias": source["alias"],
        "joins": source["joins"],
        "conditions": conditions,
        "orderBy": order_by,
        "orderDirection": order_direction,
        "limit": limit,
        "normalizedQuery": normalized,
    }


def _parse_explorer_source_clause(source_clause: str) -> dict[str, Any]:
    normalized = re.sub(r"\s*=\s*", " = ", source_clause.strip())
    tokens = normalized.split()
    dataset, alias, index = _parse_explorer_table_ref(tokens, 0)
    aliases = {alias}
    joins: list[dict[str, str]] = []
    while index < len(tokens):
        if tokens[index].lower() != "join":
            raise ValueError("only JOIN clauses may appear between FROM and WHERE")
        join_dataset, join_alias, index = _parse_explorer_table_ref(tokens, index + 1)
        if join_alias in aliases:
            raise ValueError(f"duplicate dataset alias: {join_alias}")
        aliases.add(join_alias)
        if index >= len(tokens) or tokens[index].lower() != "on":
            raise ValueError("JOIN clauses must include ON left_field = right_field")
        if index + 3 >= len(tokens) or tokens[index + 2] != "=":
            raise ValueError("JOIN clauses must use ON left_field = right_field")
        left = tokens[index + 1]
        right = tokens[index + 3]
        if not _valid_explorer_identifier(left) or not _valid_explorer_identifier(right):
            raise ValueError("JOIN fields must be simple field names")
        joins.append(
            {
                "dataset": join_dataset,
                "alias": join_alias,
                "left": left,
                "right": right,
            }
        )
        index += 4
    return {"dataset": dataset, "alias": alias, "joins": joins}


def _parse_explorer_table_ref(tokens: list[str], index: int) -> tuple[str, str, int]:
    if index >= len(tokens):
        raise ValueError("query must include a dataset after FROM or JOIN")
    dataset = _resolve_explorer_dataset(tokens[index])
    index += 1
    alias = dataset
    if index < len(tokens) and tokens[index].lower() == "as":
        if index + 1 >= len(tokens):
            raise ValueError("AS must be followed by an alias")
        alias = tokens[index + 1]
        index += 2
    elif index < len(tokens) and tokens[index].lower() not in {"join", "on"}:
        alias = tokens[index]
        index += 1
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", alias):
        raise ValueError(f"invalid dataset alias: {alias}")
    if alias.lower() in {"join", "on", "where", "order", "limit"}:
        raise ValueError(f"invalid dataset alias: {alias}")
    return dataset, alias, index


def _resolve_explorer_dataset(raw_dataset: str) -> str:
    normalized = raw_dataset.strip()
    if normalized in DATA_EXPLORER_DATASETS:
        return normalized
    for alias, metadata in DATA_EXPLORER_DATASETS.items():
        table = str(metadata["table"])
        if normalized == table or normalized == table.split(".", 1)[-1]:
            return alias
    raise ValueError(f"unsupported dataset: {raw_dataset}")


def _parse_explorer_conditions(where_clause: str) -> list[dict[str, Any]]:
    if not where_clause:
        return []
    conditions: list[dict[str, Any]] = []
    for raw_condition in re.split(r"\s+and\s+", where_clause, flags=re.IGNORECASE):
        condition = raw_condition.strip()
        null_match = re.match(
            r"^(?P<field>[A-Za-z0-9_.]+)\s+is\s+(?P<not>not\s+)?null$",
            condition,
            flags=re.IGNORECASE,
        )
        if null_match:
            conditions.append(
                {
                    "field": null_match.group("field"),
                    "operator": "is_not_null" if null_match.group("not") else "is_null",
                    "value": None,
                }
            )
            continue
        match = re.match(
            r"^(?P<field>[A-Za-z0-9_.]+)\s*(?P<operator>!=|=|>=|<=|>|<|like|contains)\s*(?P<value>.+)$",
            condition,
            flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError(f"unsupported WHERE condition: {condition}")
        conditions.append(
            {
                "field": match.group("field"),
                "operator": match.group("operator").lower(),
                "value": _parse_explorer_value(match.group("value")),
            }
        )
    return conditions


def _parse_explorer_value(raw_value: str) -> Any:
    value = raw_value.strip()
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1]
    lower_value = value.lower()
    if lower_value == "true":
        return True
    if lower_value == "false":
        return False
    try:
        if "." in value:
            return Decimal(value)
        return int(value)
    except (InvalidOperation, ValueError):
        return value


def _matches_explorer_condition(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    current = _nested_explorer_value(row, str(condition["field"]))
    operator = str(condition["operator"])
    expected = condition.get("value")
    if operator == "is_null":
        return current is None or current == ""
    if operator == "is_not_null":
        return current is not None and current != ""
    if operator in {"like", "contains"}:
        needle = str(expected).strip("%").lower()
        return needle in str(current or "").lower()
    if operator == "=":
        return _normalized_explorer_value(current) == _normalized_explorer_value(expected)
    if operator == "!=":
        return _normalized_explorer_value(current) != _normalized_explorer_value(expected)
    return _compare_explorer_values(current, expected, operator)


def _nested_explorer_value(row: dict[str, Any], field: str) -> Any:
    if _is_joined_explorer_row(row) and "." not in field:
        matches = [
            payload.get(field)
            for payload in row.values()
            if isinstance(payload, dict) and field in payload
        ]
        return matches[0] if len(matches) == 1 else None
    current: Any = row
    for part in field.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _is_joined_explorer_row(row: dict[str, Any]) -> bool:
    return bool(row) and all(isinstance(value, dict) for value in row.values())


def _normalized_explorer_value(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    return str(value).strip().lower()


def _compare_explorer_values(left: Any, right: Any, operator: str) -> bool:
    left_number = _decimal_or_none(left)
    right_number = _decimal_or_none(right)
    if left_number is not None and right_number is not None:
        left_value: Any = left_number
        right_value: Any = right_number
    else:
        left_value = str(left or "")
        right_value = str(right or "")
    if operator == ">":
        return left_value > right_value
    if operator == ">=":
        return left_value >= right_value
    if operator == "<":
        return left_value < right_value
    if operator == "<=":
        return left_value <= right_value
    return False


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _sortable_explorer_value(value: Any) -> Any:
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed
    decimal = _decimal_or_none(value)
    if decimal is not None:
        return decimal
    return str(value or "")


def _valid_explorer_identifier(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", value))


def _scenario_step_analysis(
    *,
    step: dict[str, Any],
    record_group: dict[str, Any],
    config_payload: dict[str, Any],
) -> dict[str, Any]:
    key = str(step.get("key") or "unknown")
    status = str(step.get("status") or "unknown")
    metrics = step.get("metrics", {}) if isinstance(step.get("metrics"), dict) else {}
    records = record_group.get("items", []) if isinstance(record_group, dict) else []
    state = _scenario_state(status)
    facts = _scenario_facts(key=key, status=status, metrics=metrics, step=step, records=records)
    suggestions = _scenario_suggestions(
        key=key,
        status=status,
        metrics=metrics,
        config_payload=config_payload,
    )
    return {
        "key": key,
        "label": step.get("label") or key,
        "status": status,
        "state": state,
        "message": step.get("message") or "",
        "metrics": metrics,
        "inputs": step.get("inputs", {}),
        "outputs": step.get("outputs", {}),
        "decisions": step.get("decisions", {}),
        "recordCount": len(records),
        "records": records[:25],
        "facts": facts,
        "suggestions": suggestions,
        "nextStage": _scenario_next_stage(key, status, metrics),
    }


def _scenario_state(status: str) -> str:
    if status in {"blocked", "failed", "rate_limited", "refused", "error"}:
        return "blocked"
    if status in {
        "waiting",
        "idle",
        "skipped",
        "empty",
        "no_candidates",
        "no_candidates_passed",
        "no_scores",
        "no_votes",
        "no_consensus",
        "no_intents",
        "no_positions",
        "no_triggers",
    }:
        return "idle"
    return "ok"


def _scenario_facts(
    *,
    key: str,
    status: str,
    metrics: dict[str, Any],
    step: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[str]:
    facts = [f"Step status is {status}."]
    if step.get("message"):
        facts.append(str(step["message"]))
    for metric_key in (
        "candidateCount",
        "acceptedCount",
        "rejectedCount",
        "scoredCount",
        "approvedCount",
        "orderIntentCount",
        "submittedCount",
        "simulatedCount",
        "openPositionCount",
        "triggeredCount",
    ):
        if metric_key in metrics:
            facts.append(f"{metric_key}: {metrics[metric_key]}")
    if records:
        facts.append(f"{len(records)} linked records are available for inspection.")
    if key == "data_fetch" and not metrics.get("candidateCount"):
        facts.append("No provider candidates reached the pipeline.")
    return facts[:8]


def _scenario_suggestions(
    *,
    key: str,
    status: str,
    metrics: dict[str, Any],
    config_payload: dict[str, Any],
) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    if key == "data_fetch":
        enabled_venues = [
            venue
            for venue, payload in config_payload.get("venues", {}).items()
            if isinstance(payload, dict) and payload.get("enabled")
        ]
        if not metrics.get("candidateCount"):
            suggestions.extend(
                [
                    {
                        "title": "Check active venue selection",
                        "body": f"Enabled venues are {', '.join(enabled_venues) or 'none'}. Run data import after changing venue flags.",
                        "configPath": "venues",
                    },
                    {
                        "title": "Inspect raw provider rows",
                        "body": "Open the Data tab and query market_data_pulls to see provider messages and candidate payloads.",
                        "configPath": "market_data_pulls",
                    },
                ]
            )
    if key == "scanner":
        accepted = _as_int(metrics.get("acceptedCount"))
        rejected = _as_int(metrics.get("rejectedCount"))
        if accepted == 0 and rejected > 0:
            suggestions.extend(
                [
                    {
                        "title": "Review scanner thresholds",
                        "body": "Rejected candidates usually mean spread, liquidity, resolution window, or symbol filters blocked the run.",
                        "configPath": "scanner",
                    },
                    {
                        "title": "Query refusal reasons",
                        "body": "Use select display_name, refusal_reason, spread, liquidity from scanner_candidates where status = 'rejected'.",
                        "configPath": "scanner_candidates",
                    },
                ]
            )
    if key == "brain":
        if not metrics.get("scoredCount"):
            suggestions.append(
                {
                    "title": "Confirm accepted scanner input",
                    "body": "Reasoning only scores accepted scanner candidates. If scanner accepted zero, fix scanner input first.",
                    "configPath": "scanner",
                }
            )
        if metrics.get("failedCount"):
            suggestions.append(
                {
                    "title": "Check model settings",
                    "body": "Failures in this step usually point to model credentials, budgets, prompt payload validation, or provider timeouts.",
                    "configPath": "llm",
                }
            )
    if key == "execution":
        if not metrics.get("approvedCount"):
            suggestions.append(
                {
                    "title": "Review strategy consensus",
                    "body": "Execution cannot create intents without approved consensus output.",
                    "configPath": "strategy_consensus",
                }
            )
        if not metrics.get("orderIntentCount"):
            suggestions.append(
                {
                    "title": "Check risk and live gates",
                    "body": "If consensus approved candidates but no intents appeared, review notional limits, credentials, live mode, and kill switch state.",
                    "configPath": "risk",
                }
            )
    if key == "exit" and not metrics.get("openPositionCount"):
        suggestions.append(
            {
                "title": "No open positions to close",
                "body": "This is expected when there are no persisted open positions for the configured venue and provider.",
                "configPath": "positions",
            }
        )
    if not suggestions:
        suggestions.append(
            {
                "title": "Use the linked records",
                "body": "Open the record payloads for this step and compare inputs, outputs, and decisions before changing config.",
                "configPath": key,
            }
        )
    return suggestions[:4]


def _scenario_next_stage(key: str, status: str, metrics: dict[str, Any]) -> dict[str, str]:
    if _scenario_state(status) == "ok":
        return {"state": "ok", "label": "Stage passed", "body": "The next stage had enough input to continue."}
    if key == "scanner" and _as_int(metrics.get("acceptedCount")) == 0:
        return {
            "state": "blocked",
            "label": "Needs accepted candidates",
            "body": "At least one scanner candidate must pass before reasoning can score it.",
        }
    if key == "brain" and _as_int(metrics.get("scoredCount")) == 0:
        return {
            "state": "blocked",
            "label": "Needs scored output",
            "body": "Strategy consensus needs model output with a usable signal.",
        }
    if key == "execution" and _as_int(metrics.get("orderIntentCount")) == 0:
        return {
            "state": "blocked",
            "label": "Needs order intent",
            "body": "Live submission or simulation needs an approved intent after risk gates.",
        }
    return {
        "state": "idle",
        "label": "Review before retry",
        "body": "Use data, records, and config tests to decide what to change before the next dry run.",
    }


def _scenario_config_plan(
    *,
    run: dict[str, Any] | None,
    steps: list[dict[str, Any]],
    selected_step: dict[str, Any] | None,
    config_payload: dict[str, Any],
) -> dict[str, Any]:
    if run is None or not steps:
        return _scenario_empty_config_plan(
            title="No scenario to tune",
            body="Run a manual data import, scanner-only run, or full dry run before testing settings.",
        )

    target_step = _scenario_target_step(steps, selected_step)
    if target_step is None:
        return _scenario_empty_config_plan(
            title="No blocked stage found",
            body="Every recorded stage had enough input for the next step. Review execution and exit records before changing settings.",
        )

    key = str(target_step.get("key"))
    if key == "scanner":
        return _scenario_scanner_config_plan(
            run=run,
            steps=steps,
            step=target_step,
            config_payload=config_payload,
        )
    if key == "data_fetch":
        return _scenario_empty_config_plan(
            title="Fix data before scanner settings",
            body="The run did not provide enough provider candidates for scanner tuning. Check enabled venues and provider pull records first.",
            next_step_key="scanner",
            run_mode="data_import",
        )
    if key == "brain":
        return _scenario_static_config_plan(
            title="Reasoning copilot plan",
            body="The next gate is reasoning. These settings make the next dry run send accepted scanner candidates to model scoring.",
            next_step_key="execution",
            run_mode="full_dry_run",
            patches=[
                _scenario_config_patch(
                    path="reasoning.max_prompts_per_provider_per_run",
                    value="10",
                    reason="Allow a small batch of accepted scanner candidates to be scored.",
                    expected_impact="Reasoning can create scored outputs for strategy consensus if model credentials and budgets are available.",
                    config_payload=config_payload,
                    stage="brain",
                )
            ],
        )
    if key == "execution":
        return _scenario_static_config_plan(
            title="Execution copilot plan",
            body="The next gate is execution. These settings only help after reasoning and strategy consensus produce an approved signal.",
            next_step_key="exit",
            run_mode="full_dry_run",
            patches=[
                _scenario_config_patch(
                    path="risk.polymarket.max_open_positions",
                    value="3",
                    reason="Keep a small dry-run position allowance available for approved Polymarket candidates.",
                    expected_impact="Execution can create an intent if consensus approves and the remaining risk gates pass.",
                    config_payload=config_payload,
                    stage="execution",
                )
            ],
        )
    return _scenario_empty_config_plan(
        title="No config change recommended",
        body="This stage is not blocked by a primary scanner, reasoning, consensus, or risk setting.",
        next_step_key=key,
    )


def _scenario_target_step(
    steps: list[dict[str, Any]],
    selected_step: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if selected_step is not None and selected_step.get("state") in {"blocked", "idle"}:
        return selected_step
    for key in ("data_fetch", "scanner", "brain", "execution"):
        step = _scenario_step_by_key(steps, key)
        if step is not None and step.get("state") in {"blocked", "idle"}:
            return step
    return selected_step or (steps[0] if steps else None)


def _scenario_step_by_key(steps: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((step for step in steps if step.get("key") == key), None)


def _scenario_scanner_config_plan(
    *,
    run: dict[str, Any],
    steps: list[dict[str, Any]],
    step: dict[str, Any],
    config_payload: dict[str, Any],
) -> dict[str, Any]:
    patches = _scenario_scanner_patches_from_records(
        step.get("records", []),
        config_payload=config_payload,
    )
    warnings: list[str] = []
    if not patches:
        patches = _scenario_scanner_patches_from_provider_records(
            run=run,
            records=_scenario_step_by_key(steps, "data_fetch").get("records", [])
            if _scenario_step_by_key(steps, "data_fetch") is not None
            else [],
            config_payload=config_payload,
        )
    if step.get("status") == "skipped":
        warnings.append(
            "This run stopped before scanner evaluation. Use scanner-only or full dry run after testing settings."
        )
    if not patches:
        return _scenario_empty_config_plan(
            title="Run scanner before changing thresholds",
            body="I do not see scanner refusal records yet. Start with a scanner-only run so the helper can compare candidates against thresholds.",
            next_step_key="brain",
            run_mode="scanner_only",
            warnings=warnings,
        )
    return {
        "title": "Scanner copilot plan",
        "body": (
            "The next gate is scanner. This setting set is designed to let at least one recorded candidate "
            "reach reasoning in a scanner-only dry run."
        ),
        "nextStepKey": "brain",
        "runMode": "scanner_only",
        "patches": patches[:5],
        "warnings": [
            *warnings,
            "Use this for dry-run diagnosis. It does not approve live trading or bypass risk controls.",
        ],
        "canApply": True,
    }


def _scenario_scanner_patches_from_records(
    records: Any,
    *,
    config_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    scanner_records = [
        item.get("record", {})
        for item in _first_dict_items(records, limit=50)
        if str(item.get("table", "")).endswith(".scanner_candidates")
        and isinstance(item.get("record"), dict)
    ]
    patches: dict[str, dict[str, Any]] = {}
    for record in scanner_records:
        if str(record.get("status")) != "rejected":
            continue
        reason = str(record.get("refusal_reason") or record.get("refusalReason") or "").lower()
        patch = _scenario_scanner_patch_for_rejection(
            reason=reason,
            source=record,
            config_payload=config_payload,
        )
        if patch is not None:
            _scenario_merge_patch(patches, patch)
    return list(patches.values())


def _scenario_scanner_patches_from_provider_records(
    *,
    run: dict[str, Any],
    records: Any,
    config_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    completed_at = _parse_datetime(run.get("completedAt") or run.get("completed_at") or run.get("startedAt"))
    patches: dict[str, dict[str, Any]] = {}
    for item in _first_dict_items(records, limit=20):
        record = item.get("record", {}) if isinstance(item, dict) else {}
        candidates = record.get("candidates", []) if isinstance(record, dict) else []
        for candidate in _first_dict_items(candidates, limit=50):
            for patch in _scenario_scanner_patches_for_provider_candidate(
                candidate=candidate,
                completed_at=completed_at,
                config_payload=config_payload,
            ):
                _scenario_merge_patch(patches, patch)
    return list(patches.values())


def _scenario_scanner_patches_for_provider_candidate(
    *,
    candidate: dict[str, Any],
    completed_at: datetime | None,
    config_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    venue = str(candidate.get("venue") or "")
    if not venue.startswith("polymarket"):
        return []
    config = _scenario_scanner_polymarket_config(config_payload)
    patches: list[dict[str, Any]] = []
    liquidity = _decimal_or_none(candidate.get("liquidity"))
    if liquidity is not None and liquidity < _decimal_or_none(config.get("min_liquidity")):
        patches.append(
            _scenario_config_patch(
                path="scanner.polymarket.min_liquidity",
                value=_scenario_floor_decimal(liquidity),
                reason="The recorded provider candidate has liquidity below the current scanner minimum.",
                expected_impact="Lowering the liquidity threshold lets this candidate reach the next scanner checks.",
                config_payload=config_payload,
                stage="scanner",
            )
        )
    bid_depth = _decimal_or_none(candidate.get("bidDepth"))
    ask_depth = _decimal_or_none(candidate.get("askDepth"))
    min_side_depth = min(
        [value for value in (bid_depth, ask_depth) if value is not None],
        default=None,
    )
    if min_side_depth is not None and min_side_depth < _decimal_or_none(config.get("min_depth")):
        patches.append(
            _scenario_config_patch(
                path="scanner.polymarket.min_depth",
                value=_scenario_floor_decimal(min_side_depth),
                reason="The recorded provider candidate has one side of the book below the current depth minimum.",
                expected_impact="Lowering depth lets this candidate pass the order-book depth check.",
                config_payload=config_payload,
                stage="scanner",
            )
        )
    spread = _decimal_or_none(candidate.get("spread"))
    if spread is not None and spread > _decimal_or_none(config.get("max_spread")):
        patches.append(
            _scenario_config_patch(
                path="scanner.polymarket.max_spread",
                value=_scenario_ratio_above(spread),
                reason="The recorded provider candidate has a wider spread than the scanner allows.",
                expected_impact="Raising max spread lets this candidate pass the spread check before reasoning.",
                config_payload=config_payload,
                stage="scanner",
            )
        )
    hours_to_resolution = _scenario_hours_to_resolution(candidate, completed_at)
    if hours_to_resolution is not None:
        if hours_to_resolution > _decimal_or_none(config.get("max_hours_to_resolution")):
            patches.append(
                _scenario_config_patch(
                    path="scanner.polymarket.max_hours_to_resolution",
                    value=_scenario_hours_above(hours_to_resolution),
                    reason="The recorded provider candidate resolves later than the current scanner window.",
                    expected_impact="Widening the maximum resolution window lets this candidate reach reasoning.",
                    config_payload=config_payload,
                    stage="scanner",
                )
            )
        if hours_to_resolution < _decimal_or_none(config.get("min_hours_to_resolution")):
            patches.append(
                _scenario_config_patch(
                    path="scanner.polymarket.min_hours_to_resolution",
                    value=_scenario_floor_decimal(hours_to_resolution),
                    reason="The recorded provider candidate is closer to resolution than the scanner allows.",
                    expected_impact="Lowering the minimum resolution window lets near-term candidates reach reasoning.",
                    config_payload=config_payload,
                    stage="scanner",
                )
            )
    volume = _decimal_or_none(candidate.get("volume"))
    if volume is not None and volume < _decimal_or_none(config.get("min_volume")):
        patches.append(
            _scenario_config_patch(
                path="scanner.polymarket.min_volume",
                value=_scenario_floor_decimal(volume),
                reason="The recorded provider candidate has volume below the current scanner minimum.",
                expected_impact="Lowering volume lets this candidate pass the volume check.",
                config_payload=config_payload,
                stage="scanner",
            )
        )
    return patches


def _scenario_scanner_patch_for_rejection(
    *,
    reason: str,
    source: dict[str, Any],
    config_payload: dict[str, Any],
) -> dict[str, Any] | None:
    metrics = source.get("metrics", {}) if isinstance(source.get("metrics"), dict) else {}
    if reason == "liquidity below minimum":
        liquidity = _decimal_or_none(source.get("liquidity"))
        return _scenario_config_patch(
            path="scanner.polymarket.min_liquidity",
            value=_scenario_floor_decimal(liquidity),
            reason="Rejected scanner records show liquidity below the configured minimum.",
            expected_impact="Lowering this threshold lets those candidates move to the next scanner checks.",
            config_payload=config_payload,
            stage="scanner",
        )
    if reason in {"bid depth below minimum", "ask depth below minimum"}:
        min_depth = _decimal_or_none(metrics.get("minSideDepth"))
        return _scenario_config_patch(
            path="scanner.polymarket.min_depth",
            value=_scenario_floor_decimal(min_depth),
            reason=f"Rejected scanner records show {reason}.",
            expected_impact="Lowering min depth lets candidates with thinner books continue to spread and resolution checks.",
            config_payload=config_payload,
            stage="scanner",
        )
    if reason == "spread too wide":
        spread = _decimal_or_none(source.get("spread"))
        return _scenario_config_patch(
            path="scanner.polymarket.max_spread",
            value=_scenario_ratio_above(spread),
            reason="Rejected scanner records show the spread is above the configured maximum.",
            expected_impact="Raising max spread lets wider markets reach reasoning for diagnosis.",
            config_payload=config_payload,
            stage="scanner",
        )
    if reason == "resolution too far":
        hours = _decimal_or_none(source.get("hours_to_resolution") or metrics.get("hoursToResolution"))
        return _scenario_config_patch(
            path="scanner.polymarket.max_hours_to_resolution",
            value=_scenario_hours_above(hours),
            reason="Rejected scanner records show the market resolves after the configured maximum window.",
            expected_impact="Widening the maximum resolution window lets farther-out markets reach reasoning.",
            config_payload=config_payload,
            stage="scanner",
        )
    if reason == "resolution too near":
        hours = _decimal_or_none(source.get("hours_to_resolution") or metrics.get("hoursToResolution"))
        return _scenario_config_patch(
            path="scanner.polymarket.min_hours_to_resolution",
            value=_scenario_floor_decimal(hours),
            reason="Rejected scanner records show the market resolves before the configured minimum window.",
            expected_impact="Lowering the minimum resolution window lets near-term markets reach reasoning.",
            config_payload=config_payload,
            stage="scanner",
        )
    if reason == "volume below minimum":
        volume = _decimal_or_none(metrics.get("volume"))
        return _scenario_config_patch(
            path="scanner.polymarket.min_volume",
            value=_scenario_floor_decimal(volume),
            reason="Rejected scanner records show volume below the configured minimum.",
            expected_impact="Lowering volume lets those candidates pass the volume check.",
            config_payload=config_payload,
            stage="scanner",
        )
    return None


def _scenario_static_config_plan(
    *,
    title: str,
    body: str,
    next_step_key: str,
    run_mode: str,
    patches: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "title": title,
        "body": body,
        "nextStepKey": next_step_key,
        "runMode": run_mode,
        "patches": patches,
        "warnings": ["Use this for dry-run diagnosis. It does not approve live trading."],
        "canApply": bool(patches),
    }


def _scenario_empty_config_plan(
    *,
    title: str,
    body: str,
    next_step_key: str | None = None,
    run_mode: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "body": body,
        "nextStepKey": next_step_key,
        "runMode": run_mode,
        "patches": [],
        "warnings": warnings or [],
        "canApply": False,
    }


def _scenario_config_patch(
    *,
    path: str,
    value: Any,
    reason: str,
    expected_impact: str,
    config_payload: dict[str, Any],
    stage: str,
) -> dict[str, Any]:
    return {
        "path": path,
        "value": str(value),
        "currentValue": _scenario_config_value(config_payload, path),
        "reason": reason,
        "expectedImpact": expected_impact,
        "stage": stage,
    }


def _scenario_merge_patch(
    patches: dict[str, dict[str, Any]],
    patch: dict[str, Any],
) -> None:
    path = str(patch.get("path", ""))
    if not path:
        return
    prior = patches.get(path)
    if prior is None:
        patches[path] = patch
        return
    prior_value = _decimal_or_none(prior.get("value"))
    next_value = _decimal_or_none(patch.get("value"))
    if prior_value is None or next_value is None:
        return
    if path.endswith(("max_spread", "max_hours_to_resolution")) and next_value > prior_value:
        patches[path] = patch
    if path.endswith(("min_depth", "min_liquidity", "min_volume", "min_hours_to_resolution")) and next_value < prior_value:
        patches[path] = patch


def _scenario_scanner_polymarket_config(config_payload: dict[str, Any]) -> dict[str, Any]:
    configured = config_payload.get("scanner", {})
    polymarket = configured.get("polymarket") if isinstance(configured, dict) else {}
    return {
        **DEFAULT_SCANNER_CONFIG["polymarket"],
        **(polymarket if isinstance(polymarket, dict) else {}),
    }


def _scenario_config_value(config_payload: dict[str, Any], path: str) -> Any:
    value: Any = config_payload
    for segment in path.split("."):
        if not isinstance(value, dict) or segment not in value:
            if path.startswith("scanner.polymarket."):
                return _scenario_scanner_polymarket_config(config_payload).get(path.split(".")[-1])
            return None
        value = value[segment]
    return value


def _scenario_hours_to_resolution(
    candidate: dict[str, Any],
    completed_at: datetime | None,
) -> Decimal | None:
    end_at = _parse_datetime(candidate.get("endDate"))
    if end_at is None or completed_at is None:
        return None
    return Decimal(str((end_at - completed_at).total_seconds())) / Decimal("3600")


def _scenario_floor_decimal(value: Decimal | None) -> str:
    if value is None:
        return "1"
    if value <= 0:
        return "1"
    if value < 1:
        return str(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize())
    return str(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _scenario_ratio_above(value: Decimal | None) -> str:
    if value is None:
        return "0.08"
    adjusted = value + Decimal("0.01")
    return str(adjusted.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize())


def _scenario_hours_above(value: Decimal | None) -> str:
    if value is None:
        return "336"
    adjusted = value + Decimal("24")
    return str(adjusted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _scenario_override_result(
    override: dict[str, Any],
    selected_step: dict[str, Any] | None,
    *,
    config_payload: dict[str, Any],
) -> dict[str, str]:
    path = str(override.get("path") or "").strip()
    value = str(override.get("value") or "").strip()
    step_key = selected_step.get("key") if selected_step else "pipeline"
    if not path:
        return {
            "path": "",
            "value": value,
            "impact": "No config path was provided.",
            "recommendation": "Enter a path such as scanner.polymarket.max_spread.",
        }
    if path.startswith("scanner"):
        impact = "This would be tested at the scanner step before any model call."
    elif path.startswith("reasoning") or path.startswith("llm"):
        impact = "This would be tested after scanner candidates are accepted."
    elif path.startswith("strategy_consensus"):
        impact = "This would affect whether scored candidates become approved consensus output."
    elif path.startswith("risk") or path.startswith("execution") or path == "live_enabled":
        impact = "This would affect order intent sizing, simulation, or live submission gates."
    else:
        impact = f"This may affect the {step_key} step, but it is not one of the primary tick gates."
    current_value = _scenario_config_value(config_payload, path)
    return {
        "path": path,
        "value": value,
        "currentValue": "unknown" if current_value is None else str(current_value),
        "impact": impact,
        "recommendation": "Run a scanner-only or full dry run after saving a config change to verify behavior.",
    }


def _scenario_prompt_answer(
    *,
    prompt: str,
    run: dict[str, Any] | None,
    step: dict[str, Any] | None,
    steps: list[dict[str, Any]],
    overrides: list[dict[str, str]],
    recommended_config_set: dict[str, Any],
) -> dict[str, Any]:
    if run is None:
        return {
            "title": "No tick to analyze",
            "body": "Run a manual data import or full dry run first. The scenario helper needs recorded steps and records.",
            "bullets": [],
        }
    if step is None:
        return {
            "title": "No step selected",
            "body": "Select a tick step, then ask what blocked it or which config setting to test.",
            "bullets": [],
        }
    target_step = _scenario_target_step(steps, step) or step
    suggestions = [suggestion["body"] for suggestion in target_step.get("suggestions", [])]
    facts = target_step.get("facts", [])
    stage_path = ", ".join(
        f"{item['label']}: {item['status']}"
        for item in steps[:5]
        if item.get("label")
    )
    prompt_text = prompt.strip()
    body = (
        f"The run is currently gated at {target_step['label']}: {target_step['status']}."
        if not prompt_text
        else f"For your question, I would start with {target_step['label']} because its status is {target_step['status']}."
    )
    bullets = [
        f"Run path: {stage_path}.",
        *facts[:3],
        *suggestions[:2],
    ]
    for patch in recommended_config_set.get("patches", [])[:3]:
        bullets.append(
            f"Try {patch['path']} = {patch['value']}: {patch['expectedImpact']}"
        )
    if overrides:
        bullets.append(f"Testing {len(overrides)} config setting{'s' if len(overrides) != 1 else ''} as a set.")
    return {
        "title": "Scenario help",
        "body": body,
        "bullets": bullets[:6],
    }


def _row_datetime_sort_key(row: dict[str, Any]) -> datetime:
    for key in ("completed_at", "created_at", "started_at", "imported_at"):
        parsed = _parse_datetime(row.get(key))
        if parsed is not None:
            return parsed
    return datetime.min.replace(tzinfo=UTC)


def _ai_usage_error_state(import_runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not import_runs:
        return {
            "status": "not_configured",
            "message": "No provider-side usage import has run yet.",
            "latestRunId": None,
            "errorCode": None,
        }
    latest = max(import_runs, key=_row_datetime_sort_key)
    if latest.get("status") in {"failed", "unsupported"}:
        return {
            "status": latest.get("status"),
            "message": latest.get("message"),
            "latestRunId": latest.get("id"),
            "errorCode": latest.get("error_code"),
        }
    return {
        "status": "ok",
        "message": latest.get("message"),
        "latestRunId": latest.get("id"),
        "errorCode": None,
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


def _worker_heartbeat_state(*, status: str, age_seconds: int) -> tuple[str, str]:
    if age_seconds > 180:
        return "blocked", "Worker heartbeat stale"
    if status in CURRENT_WORKER_HEARTBEAT_STATUSES:
        return "ok", "Scheduler heartbeat current"
    return "blocked", f"Scheduler heartbeat {status}"


def _empty_historical_import_counts() -> dict[str, int]:
    return {
        "gammaMarkets": 0,
        "chainFills": 0,
        "trades": 0,
        "walletPositions": 0,
        "walletStats": 0,
        "targetWalletSnapshots": 0,
        "checkpoints": 0,
    }


def _empty_broker_history_counts() -> dict[str, int]:
    return {
        "orders": 0,
        "fills": 0,
        "positions": 0,
        "accountSnapshots": 0,
        "bars": 0,
        "pnlSnapshots": 0,
        "checkpoints": 0,
    }


def _polymarket_history_checkpoint(source: Any) -> bool:
    text = str(source or "")
    return text.startswith("polymarket_") or text.startswith("polygon_")


def _alpaca_history_checkpoint(source: Any) -> bool:
    text = str(source or "")
    return text.startswith("alpaca_broker_history") or text.startswith("alpaca_stock_bars")


def _historical_checkpoint_sort_key(row: dict[str, Any]) -> datetime:
    for key in ("updated_at", "last_success_at"):
        value = row.get(key)
        if isinstance(value, datetime):
            return value
    return datetime.min.replace(tzinfo=UTC)


def _historical_import_status(
    *,
    checkpoints: list[dict[str, Any]],
    counts: dict[str, int],
) -> str:
    statuses = {str(row.get("status", "")) for row in checkpoints}
    if "failed" in statuses:
        return "failed"
    if "rate_limited" in statuses:
        return "rate_limited"
    if any(value > 0 for key, value in counts.items() if key != "checkpoints"):
        return "complete" if statuses and statuses <= {"complete"} else "stored"
    return "idle"


def _historical_import_message(
    *,
    status: str,
    counts: dict[str, int],
    latest: dict[str, Any] | None,
) -> str:
    if status == "idle":
        return "No historical Polymarket import records have been stored yet."
    if status == "failed" and latest is not None:
        return f"Latest historical import failed for {latest.get('source', 'unknown source')}."
    if status == "rate_limited" and latest is not None:
        return f"Latest historical import was rate limited for {latest.get('source', 'unknown source')}."
    return (
        f"Historical import has {counts['gammaMarkets']} Gamma market"
        f"{'' if counts['gammaMarkets'] == 1 else 's'}, {counts['chainFills']} chain fill"
        f"{'' if counts['chainFills'] == 1 else 's'}, and {counts['walletStats']} wallet stat"
        f"{'' if counts['walletStats'] == 1 else 's'} stored."
    )


def _broker_history_message(
    *,
    status: str,
    counts: dict[str, int],
    latest: dict[str, Any] | None,
) -> str:
    if status == "idle":
        return "No Alpaca broker history import records have been stored yet."
    if status == "failed" and latest is not None:
        return f"Latest broker history import failed for {latest.get('source', 'unknown source')}."
    if status == "rate_limited" and latest is not None:
        return f"Latest broker history import was rate limited for {latest.get('source', 'unknown source')}."
    return (
        f"Broker history has {counts['orders']} order"
        f"{'' if counts['orders'] == 1 else 's'}, {counts['fills']} fill"
        f"{'' if counts['fills'] == 1 else 's'}, {counts['positions']} position"
        f"{'' if counts['positions'] == 1 else 's'}, and {counts['bars']} stock bar"
        f"{'' if counts['bars'] == 1 else 's'} stored."
    )


def _scanner_summary_message(payload: dict[str, Any]) -> str:
    status = str(payload.get("status", "idle"))
    if status == "idle":
        return "No scanner run has been recorded yet."
    if status == "blocked":
        return "Latest scanner run was blocked before candidate evaluation completed."
    if status == "empty":
        return "Latest scanner run had no provider candidates to evaluate."
    base = (
        f"Latest scanner run accepted {payload.get('acceptedCount', 0)} and rejected "
        f"{payload.get('rejectedCount', 0)} candidate"
        f"{'' if payload.get('rejectedCount', 0) == 1 else 's'}."
    )
    formatted = _format_scanner_breakdown(payload.get("rejectionBreakdown"))
    return f"{base} Top rejections: {formatted}." if formatted else base


def _reasoning_summary_message(payload: dict[str, Any]) -> str:
    status = str(payload.get("status", "idle"))
    if status == "idle":
        return "No reasoning run has been recorded yet."
    if status == "no_candidates":
        return "Latest reasoning run had no accepted scanner candidates to score."
    if status == "skipped":
        return "Latest reasoning run skipped all prompts because provider credentials or budgets were unavailable."
    if status == "failed":
        return "Latest reasoning run failed before any candidate could be scored."
    return (
        f"Latest reasoning run scored {payload.get('scoredCount', 0)}, skipped "
        f"{payload.get('skippedCount', 0)}, and failed {payload.get('failedCount', 0)} prompt"
        f"{'' if payload.get('failedCount', 0) == 1 else 's'}."
    )


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


def _pipeline_scanner_status(scanner_status: str) -> str:
    if scanner_status == "skipped":
        return "skipped"
    if scanner_status == "completed":
        return "completed"
    if scanner_status in {"blocked", "failed", "rate_limited"}:
        return "blocked"
    if scanner_status == "no_candidates_passed":
        return "waiting"
    return "waiting"


def _pipeline_reasoning_status(reasoning_status: str) -> str:
    if reasoning_status == "skipped":
        return "skipped"
    if reasoning_status == "completed":
        return "completed"
    if reasoning_status == "partial":
        return "partial"
    if reasoning_status in {"failed", "blocked"}:
        return "blocked"
    return "waiting"


def _pipeline_strategy_consensus_status(strategy_status: str) -> str:
    if strategy_status == "skipped":
        return "skipped"
    if strategy_status in {"approved", "refused", "partial"}:
        return "completed" if strategy_status != "partial" else "partial"
    if strategy_status in {"failed", "blocked", "unavailable"}:
        return "blocked"
    return "waiting"


def _pipeline_lifecycle_status(execution_status: str) -> str:
    if execution_status == "skipped":
        return "skipped"
    if execution_status in {"completed", "refused"}:
        return "completed"
    if execution_status == "partial":
        return "partial"
    if execution_status in {"failed", "blocked", "unavailable"}:
        return "blocked"
    return "waiting"


def _pipeline_exit_status(exit_status: str) -> str:
    if exit_status == "skipped":
        return "skipped"
    if exit_status in {"completed", "no_positions", "no_triggers", "refused"}:
        return "completed"
    if exit_status == "partial":
        return "partial"
    if exit_status in {"failed", "blocked", "unavailable"}:
        return "blocked"
    return "waiting"


def _compact_candidate_decisions(candidates: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": candidate.get("id"),
            "venue": candidate.get("venue"),
            "instrumentId": candidate.get("instrumentId"),
            "displayName": candidate.get("displayName"),
            "status": candidate.get("status"),
            "refusalReason": candidate.get("refusalReason"),
            "strategyNames": candidate.get("strategyNames", []),
            "price": candidate.get("price"),
            "liquidity": candidate.get("liquidity"),
            "spread": candidate.get("spread"),
        }
        for candidate in _balanced_scanner_candidate_items(candidates)
    ]


def _balanced_scanner_candidate_items(items: Any, limit: int = 20) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    candidates = [item for item in items if isinstance(item, dict)]
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()

    def add(candidate: dict[str, Any]) -> None:
        if len(selected) >= limit:
            return
        key = _scanner_candidate_key(candidate)
        if key in selected_keys:
            return
        selected.append(candidate)
        selected_keys.add(key)

    for candidate in candidates:
        if _scanner_candidate_status(candidate) == "accepted":
            add(candidate)

    seen_buckets: set[tuple[str, str]] = set()
    for candidate in candidates:
        bucket = (_scanner_candidate_venue(candidate), _scanner_candidate_reason(candidate))
        if bucket in seen_buckets:
            continue
        seen_buckets.add(bucket)
        add(candidate)

    for candidate in candidates:
        add(candidate)
        if len(selected) >= limit:
            break
    return selected


def _scanner_candidate_key(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("id")
        or candidate.get("instrumentId")
        or candidate.get("instrument_id")
        or candidate.get("displayName")
        or candidate.get("display_name")
        or id(candidate)
    )


def _scanner_candidate_status(candidate: dict[str, Any]) -> str:
    return str(candidate.get("status") or "unknown")


def _scanner_candidate_venue(candidate: dict[str, Any]) -> str:
    return str(candidate.get("venue") or "unknown")


def _scanner_candidate_reason(candidate: dict[str, Any]) -> str:
    return str(candidate.get("refusalReason") or candidate.get("refusal_reason") or "accepted")


def _scanner_rejection_breakdown(candidates: Any, limit: int = 12) -> list[dict[str, Any]]:
    if not isinstance(candidates, list):
        return []
    counts: dict[tuple[str, str], int] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if _scanner_candidate_status(candidate) != "rejected":
            continue
        bucket = (_scanner_candidate_venue(candidate), _scanner_candidate_reason(candidate))
        counts[bucket] = counts.get(bucket, 0) + 1
    rows = [
        {"venue": venue, "reason": reason, "count": count}
        for (venue, reason), count in counts.items()
    ]
    rows.sort(key=lambda row: (-int(row["count"]), str(row["venue"]), str(row["reason"])))
    return rows[:limit]


def _scanner_step_message(scanner_run: dict[str, Any], breakdown: list[dict[str, Any]]) -> str:
    if not scanner_run.get("candidateCount"):
        return "No priced candidates reached the scanner from provider data."
    base = (
        f"Scanner accepted {scanner_run['acceptedCount']} and rejected "
        f"{scanner_run['rejectedCount']} candidate"
        f"{'' if scanner_run['rejectedCount'] == 1 else 's'}."
    )
    formatted = _format_scanner_breakdown(breakdown)
    return f"{base} Top rejections: {formatted}." if formatted else base


def _format_scanner_breakdown(breakdown: Any) -> str:
    if not isinstance(breakdown, list):
        return ""
    rows = [row for row in breakdown if isinstance(row, dict)]
    if not rows:
        return ""
    return "; ".join(
        f"{row.get('venue', 'unknown')}: {row.get('reason', 'rejected')} ({row.get('count', 0)})"
        for row in rows[:6]
    )


def _compact_reasoning_decisions(outputs: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": output.get("id"),
            "instrumentId": output.get("instrumentId"),
            "modelProvider": output.get("modelProvider"),
            "status": output.get("status"),
            "refusalReason": output.get("refusalReason"),
            "directionalSignal": output.get("directionalSignal"),
            "confidence": output.get("confidence"),
            "estimatedProbability": output.get("estimatedProbability"),
            "costUsd": output.get("costUsd"),
            "thesis": _truncate_text(output.get("thesis")),
        }
        for output in _first_dict_items(outputs)
    ]


def _compact_strategy_decisions(outputs: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": output.get("id"),
            "instrumentId": output.get("instrumentId"),
            "modelProvider": output.get("modelProvider"),
            "status": output.get("status"),
            "side": output.get("side"),
            "sizeMultiplier": output.get("sizeMultiplier"),
            "signalCount": output.get("signalCount"),
            "strategyNames": output.get("strategyNames", []),
            "refusalReason": output.get("refusalReason"),
        }
        for output in _first_dict_items(outputs)
    ]


def _compact_intent_decisions(intents: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": intent.get("id"),
            "venue": intent.get("venue"),
            "instrumentId": intent.get("instrumentId"),
            "modelProvider": intent.get("modelProvider"),
            "status": intent.get("status"),
            "side": intent.get("side"),
            "orderType": intent.get("orderType"),
            "notionalUsd": intent.get("notionalUsd"),
            "triggerType": intent.get("triggerType"),
            "positionId": intent.get("positionId"),
            "refusalReason": intent.get("refusalReason"),
            "venueOrderId": intent.get("venueOrderId"),
        }
        for intent in _first_dict_items(intents)
    ]


def _first_dict_items(items: Any, limit: int = 20) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)][:limit]


def _truncate_text(value: Any, limit: int = 280) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _metrics_without_trace(metrics: Any) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    return {key: value for key, value in metrics.items() if key != "trace"}


def _pipeline_end_result(metadata: dict[str, Any], status: Any) -> dict[str, Any]:
    return {
        "status": str(status or "unknown"),
        "marketDataStatus": metadata.get("marketDataStatus"),
        "candidateCount": metadata.get("candidateCount", 0),
        "scannerAcceptedCount": metadata.get("scannerAcceptedCount", 0),
        "reasoningScoredCount": metadata.get("reasoningScoredCount", 0),
        "strategyApprovedCount": metadata.get("strategyApprovedCount", 0),
        "orderIntentCount": metadata.get("orderIntentCount", 0),
        "orderSubmittedCount": metadata.get("orderSubmittedCount", 0),
        "orderSimulatedCount": metadata.get("orderSimulatedCount", 0),
        "orderRefusedCount": metadata.get("orderRefusedCount", 0),
        "exitTriggeredCount": metadata.get("exitTriggeredCount", 0),
        "exitRefusedCount": metadata.get("exitRefusedCount", 0),
        "venues": metadata.get("venues", []),
    }


def _pipeline_reasoning_message(reasoning_run: dict[str, Any]) -> str:
    status = str(reasoning_run.get("status", "idle"))
    if status == "no_candidates":
        return "Reasoning had no accepted scanner candidates to score."
    if status == "skipped":
        return str(reasoning_run.get("message") or "Reasoning skipped for the requested run mode.")
    if status == "failed":
        return "Reasoning failed before any candidate was scored."
    scored = int(reasoning_run.get("scoredCount", 0))
    skipped = int(reasoning_run.get("skippedCount", 0))
    failed = int(reasoning_run.get("failedCount", 0))
    if scored or skipped or failed:
        return (
            f"Reasoning scored {scored}, skipped {skipped}, and failed "
            f"{failed} prompt{'' if failed == 1 else 's'}."
        )
    return "Reasoning is waiting for scanner survivors."


def _pipeline_strategy_consensus_message(strategy_run: dict[str, Any]) -> str:
    status = str(strategy_run.get("status", "idle"))
    if status == "skipped":
        return str(strategy_run.get("message") or "Strategy consensus skipped for the requested run mode.")
    if status == "no_scores":
        return "Strategy consensus had no scored reasoning outputs to evaluate."
    if status == "no_votes":
        return "Strategy consensus ran, but no strategy produced a directional vote."
    votes = int(strategy_run.get("voteCount", 0))
    approved = int(strategy_run.get("approvedCount", 0))
    refused = int(strategy_run.get("refusedCount", 0))
    if status in {"approved", "refused", "partial"}:
        return (
            f"Strategy consensus recorded {votes} vote{'' if votes == 1 else 's'}, "
            f"approved {approved}, and refused {refused}."
        )
    return "Strategy consensus is waiting for scored reasoning output."


def _pipeline_execution_message(execution_run: dict[str, Any]) -> str:
    status = str(execution_run.get("status", "idle"))
    if status == "skipped":
        return str(execution_run.get("message") or "Execution skipped for the requested run mode.")
    if status == "no_consensus":
        return "Execution had no approved strategy consensus output to size."
    if status == "no_intents":
        return "Execution ran but no order intents were created."
    intents = int(execution_run.get("intentCount", 0))
    simulated = int(execution_run.get("simulatedCount", 0))
    submitted = int(execution_run.get("submittedCount", 0))
    refused = int(execution_run.get("refusedCount", 0))
    if intents:
        return (
            f"Execution recorded {intents} order intent{'' if intents == 1 else 's'}, "
            f"simulated {simulated}, submitted {submitted}, and refused {refused}."
        )
    return "Execution is waiting for approved consensus output."


def _pipeline_exit_message(exit_run: dict[str, Any]) -> str:
    status = str(exit_run.get("status", "idle"))
    if status == "skipped":
        return str(exit_run.get("message") or "Exit monitoring skipped for the requested run mode.")
    if status == "no_positions":
        return "Exit monitor found no open positions."
    if status == "no_triggers":
        return "Exit monitor found open positions, but no exit trigger fired."
    triggered = int(exit_run.get("triggeredCount", 0))
    simulated = int(exit_run.get("simulatedCount", 0))
    submitted = int(exit_run.get("submittedCount", 0))
    refused = int(exit_run.get("refusedCount", 0))
    if triggered:
        return (
            f"Exit monitor recorded {triggered} exit intent{'' if triggered == 1 else 's'}, "
            f"simulated {simulated}, submitted {submitted}, and refused {refused}."
        )
    return "Exit monitor is waiting for open-position data."


def _strategy_consensus_summary_message(strategy_run: dict[str, Any]) -> str:
    status = str(strategy_run.get("status", "idle"))
    if status == "no_scores":
        return "No scored reasoning outputs were available for strategy consensus."
    if status == "no_votes":
        return "No strategy produced a directional vote for the latest scored candidates."
    votes = int(strategy_run.get("voteCount", 0))
    approved = int(strategy_run.get("approvedCount", 0))
    refused = int(strategy_run.get("refusedCount", 0))
    return (
        f"Latest strategy consensus recorded {votes} vote{'' if votes == 1 else 's'}, "
        f"approved {approved}, and refused {refused} before risk sizing."
    )


def _execution_summary_message(execution_run: dict[str, Any]) -> str:
    status = str(execution_run.get("status", "idle"))
    if status == "idle":
        return "No execution run has been recorded yet."
    return _pipeline_execution_message(execution_run)


def _exit_summary_message(exit_run: dict[str, Any]) -> str:
    status = str(exit_run.get("status", "idle"))
    if status == "idle":
        return "No exit run has been recorded yet."
    return _pipeline_exit_message(exit_run)


def _order_history_message(row: dict[str, Any]) -> str:
    refusal_reason = str(row.get("refusal_reason") or "").strip()
    if refusal_reason:
        return refusal_reason
    state = str(row.get("status") or "unknown").strip().lower()
    return {
        "submitted": "Submitted to venue; fill not yet confirmed.",
        "filled": "Venue fill confirmed.",
        "simulated": "Simulation only; no venue order submitted.",
        "canceled": "Order canceled.",
        "cancelled": "Order canceled.",
        "failed": "Order failed.",
        "reconcile_first": "Reconciliation required before retry.",
    }.get(state, "Current order state is unknown.")


def _decode_order_history_cursor(value: str | None) -> tuple[datetime, str] | None:
    if value is None:
        return None
    timestamp_text, separator, row_id = value.rpartition("|")
    if not separator or not timestamp_text or not row_id:
        raise ValueError("invalid order history cursor")
    try:
        created_at = datetime.fromisoformat(timestamp_text)
    except ValueError as exc:
        raise ValueError("invalid order history cursor") from exc
    if created_at.tzinfo is None:
        raise ValueError("invalid order history cursor")
    return created_at, row_id


def _encode_order_history_cursor(row: dict[str, Any]) -> str:
    created_at = row.get("created_at")
    row_id = str(row.get("id") or "")
    if not isinstance(created_at, datetime) or created_at.tzinfo is None or not row_id:
        raise ValueError("order history row cannot be paginated")
    return f"{created_at.isoformat()}|{row_id}"


def _fixed_decimal_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return format(parsed, ".8f")


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


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)
