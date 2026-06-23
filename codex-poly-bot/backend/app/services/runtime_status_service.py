"""Runtime readiness and dashboard status helpers.

REQ: REQ-UI-004, REQ-UI-009, REQ-NOT-006, REQ-DAT-008,
REQ-WAL-005, REQ-WAL-006, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.db.schema import SHARED_SCHEMA
from app.domain import Environment, ModelProvider, Venue


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
        recipient_count = len([value for value in recipients.values() if str(value).strip()])
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
