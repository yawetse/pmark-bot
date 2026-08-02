"""Runtime configuration service.

REQ: REQ-UI-006, REQ-UI-007, REQ-OBS-004, REQ-OBS-006, REQ-KAL-001, REQ-KAL-009
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.db import (
    PersistenceUnavailableError,
    RepositoryRegistry,
    SHARED_CONFIG_USERNAME,
    UnitOfWork,
    normalize_config_username,
)
from app.domain import Environment, FundingConfig, ModelProvider, Venue
from app.services.audit_service import ActorContext, AuditService, ConfigChange, ConfigMutationResult
from app.services.auth_service import DashboardAccessResult
from app.services.stock_universe import (
    DEFAULT_ALPACA_PRESET_REFRESH_CONFIG,
    DEFAULT_ALPACA_SYMBOL_PRESETS,
    normalize_preset_name,
    normalize_symbol_list,
    resolve_alpaca_symbol_universe,
    seed_alpaca_preset_snapshots,
    stock_universe_metadata,
)
from app.services.stock_universe_refresh_service import latest_preset_snapshot_payloads
from app.services.scanner_service import (
    DEFAULT_SCANNER_CONFIG,
    MAX_POLYMARKET_MARKET_DATA_LIMIT,
)
from app.services.brain_service import DEFAULT_REASONING_CONFIG
from app.services.llm_service import (
    DEFAULT_CLAUDE_SCORING_MAX_TOKENS,
    DEFAULT_CLAUDE_SCORING_MODEL,
    DEFAULT_OPENAI_SCORING_MAX_OUTPUT_TOKENS,
    DEFAULT_OPENAI_SCORING_MODEL,
    DEFAULT_OPENAI_SCORING_REASONING_EFFORT,
    OPENAI_SCORING_MODEL_OPTIONS,
)
from app.services.strategy_consensus_service import DEFAULT_STRATEGY_CONSENSUS_CONFIG


DEFAULT_EXECUTION_CONFIG = {
    "market_data_freshness_seconds": 300,
    "order_type": "market",
    "alpaca": {"model_capital_usd": "1000.00"},
}
DEFAULT_EXIT_CONFIG = {
    "polymarket": {
        "profit_target_usd": "5.00",
        "profit_target_pct": "0.25",
        "volume_spike_multiplier": "3.00",
        "max_thesis_age_hours": "72",
        "min_stale_price_move_pct": "0.10",
    },
    "alpaca": {
        "profit_target_pct": "0.02",
        "stop_loss_pct": "0.01",
        "trailing_stop_pct": "0.01",
        "max_position_age_hours": "6",
        "min_stale_price_move_pct": "0.005",
        "market_hours_only": True,
        "close_before_market_close_minutes": 15,
    },
}
DEFAULT_FUNDING_CONFIG = {
    "emergency_stop": False,
    "direct_transfers_enabled": False,
    "max_transfer_usd": "0.00",
    "max_monthly_transfer_usd": "0.00",
    "timezone": "America/New_York",
    "missing_after_business_days": 4,
    "schedules": [],
}

ACTIVE_STOCK_DAY_TRADER_PROFILE = "active_stock_day_trader"
ACTIVE_STOCK_DAY_TRADER_PROFILE_PATHS = (
    "trading_profile",
    "default_selected_venue",
    "venues.alpaca.enabled",
    "trading_loop_interval_seconds",
    "scanner.alpaca.min_quote_liquidity",
    "scanner.alpaca.max_spread",
    "scanner.alpaca.min_history_bars",
    "scanner.alpaca.strategies.momentum.enabled",
    "scanner.alpaca.strategies.momentum.min_change_pct",
    "scanner.alpaca.strategies.mean_reversion.enabled",
    "scanner.alpaca.strategies.mean_reversion.min_deviation_pct",
    "scanner.alpaca.strategies.gap.enabled",
    "scanner.alpaca.strategies.gap.min_gap_pct",
    "scanner.alpaca.strategies.liquidity.enabled",
    "scanner.alpaca.strategies.liquidity.min_volume",
    "scanner.alpaca.strategies.volatility.enabled",
    "scanner.alpaca.strategies.volatility.min_range_pct",
    "scanner.alpaca.strategies.unusual_volume.enabled",
    "scanner.alpaca.strategies.unusual_volume.min_ratio",
    "reasoning.max_prompts_per_provider_per_run",
    "reasoning.alpaca.min_confidence",
    "reasoning.alpaca.min_edge",
    "llm.openai.budget_usd",
    "llm.openai.settings.budget_window_hours",
    "llm.claude.budget_usd",
    "llm.claude.settings.budget_window_hours",
    "risk.alpaca.max_position_usd",
    "risk.alpaca.max_daily_loss_usd",
    "risk.alpaca.max_open_positions",
    "risk.alpaca.max_portfolio_allocation_per_symbol",
    "risk.alpaca.market_order_slippage_threshold",
    "exit.alpaca.profit_target_pct",
    "exit.alpaca.stop_loss_pct",
    "exit.alpaca.trailing_stop_pct",
    "exit.alpaca.max_position_age_hours",
    "exit.alpaca.min_stale_price_move_pct",
    "exit.alpaca.market_hours_only",
    "exit.alpaca.close_before_market_close_minutes",
)


class ConfigConflictError(ValueError):
    """Raised when a dashboard save targets a stale config version.

    REQ: REQ-UI-007
    """


class ConfigValidationError(ValueError):
    """Raised when a dashboard config patch is not supported or safe.

    REQ: REQ-UI-005
    """


class ConfigAuthorizationError(PermissionError):
    """Raised when a dashboard config save is attempted without authorization.

    REQ: REQ-UI-005, REQ-UI-006
    """


@dataclass(frozen=True)
class ConfigPatchOperation:
    """One dashboard configuration patch operation.

    REQ: REQ-UI-005
    """

    op: str
    path: str
    value: Any


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    """One immutable config view for a trading loop.

    REQ: REQ-UI-007
    """

    environment: Environment
    version: str
    payload: dict[str, Any]
    audit_event_id: str | None = None
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ConfigReloadResult:
    """Result of loading the next-loop config snapshot.

    REQ: REQ-UI-007, REQ-OBS-006
    """

    snapshot: RuntimeConfigSnapshot
    degraded: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class ConfigSaveResult:
    """Audited config save result returned to dashboard API callers.

    REQ: REQ-UI-006, REQ-UI-007
    """

    mutation: ConfigMutationResult
    applies_on_next_loop: bool


class ConfigService:
    """Persist dashboard config changes and load stable loop snapshots."""

    SAFE_MINIMUM_LOOP_INTERVAL_SECONDS = 5
    KNOWN_STRATEGIES = {"arbitrage", "convergence", "whale_copy"}

    def __init__(
        self,
        registry: RepositoryRegistry | None = None,
        default_payload_factory: Callable[[], dict[str, Any]] | None = None,
    ):
        self.registry = registry or RepositoryRegistry()
        self._default_payload_factory = default_payload_factory or default_config_payload
        self.audit_service = AuditService(self.registry)
        self._last_good_snapshots: dict[tuple[Environment, str], RuntimeConfigSnapshot] = {}

    def save_config_patches(
        self,
        *,
        actor: ActorContext,
        access: DashboardAccessResult,
        environment: Environment,
        expected_version: str | None,
        version: str,
        patches: list[ConfigPatchOperation],
        username: str | None = None,
    ) -> ConfigSaveResult:
        """Validate and persist dashboard config patches.

        REQ: REQ-UI-005, REQ-UI-006, REQ-UI-007
        """

        if not access.authorized:
            raise ConfigAuthorizationError(access.reason or "dashboard access denied")
        if not patches:
            raise ConfigValidationError("config update requires at least one patch")

        current_payload = self._current_payload(environment, username=username)
        next_payload = deepcopy(current_payload)
        first_change: ConfigChange | None = None
        for patch in patches:
            old_value = self._value_at_path(next_payload, patch.path)
            validated_value = self._validated_patch_value(patch)
            self._apply_patch(next_payload, patch, validated_value)
            if first_change is None:
                first_change = ConfigChange(
                    path=patch.path,
                    old_value=old_value,
                    new_value=validated_value,
                )

        assert first_change is not None
        patched_paths = {patch.path for patch in patches}
        if patched_paths & {
            "alpaca.symbol_presets",
            "alpaca.custom_symbols",
            "alpaca.custom_presets",
        }:
            alpaca_config = next_payload.setdefault("alpaca", {})
            if isinstance(alpaca_config, dict):
                alpaca_config["symbol_universe"] = resolve_alpaca_symbol_universe(next_payload)
                alpaca_config["preset_metadata"] = stock_universe_metadata(next_payload)

        return self.save_config_change(
            actor=actor,
            environment=environment,
            change=first_change,
            version=version,
            payload=next_payload,
            expected_version=expected_version,
            username=username,
        )

    def save_config_change(
        self,
        *,
        actor: ActorContext,
        environment: Environment,
        change: ConfigChange,
        version: str,
        payload: dict[str, Any],
        expected_version: str | None = None,
        username: str | None = None,
    ) -> ConfigSaveResult:
        """Persist a new version after auditing the dashboard change.

        REQ: REQ-UI-006, REQ-UI-007, REQ-OBS-004
        """

        if expected_version is not None and expected_version != self.current_version(
            environment,
            username=username,
        ):
            raise ConfigConflictError("config version conflict")

        with UnitOfWork(self.registry.state) as unit:
            self.registry.state.lock_transaction_key(
                f"funding-controls:{environment.value}:{normalize_config_username(username)}"
            )
            if expected_version is not None and expected_version != self.current_version(
                environment,
                username=username,
            ):
                raise ConfigConflictError("config version conflict")
            audit_event = self.audit_service.record_config_change(
                actor=actor,
                environment=environment,
                change=change,
            )
            self._deactivate_active_versions(environment, username=username)
            config_version = self.registry.shared().record_config_version(
                environment=environment,
                username=username,
                version=version,
                payload=deepcopy(payload),
            )
            unit.commit()
        mutation = ConfigMutationResult(
            audit_event=audit_event,
            config_version=config_version,
        )
        return ConfigSaveResult(mutation=mutation, applies_on_next_loop=True)

    def config_for_next_loop(
        self,
        environment: Environment,
        username: str | None = None,
    ) -> ConfigReloadResult:
        """Load one config snapshot for the next trading loop.

        REQ: REQ-UI-007, REQ-OBS-006
        """

        try:
            row = self._latest_config_row(environment, username=username)
        except PersistenceUnavailableError as exc:
            return self._degraded_reload(environment, str(exc), username=username)

        owner = normalize_config_username(username)
        if row is None:
            fallback = RuntimeConfigSnapshot(
                environment=environment,
                version="bootstrap",
                payload=self._default_payload(environment),
            )
            self._last_good_snapshots[(environment, owner)] = fallback
            return ConfigReloadResult(snapshot=fallback)

        snapshot = RuntimeConfigSnapshot(
            environment=environment,
            version=row["version"],
            payload=self._payload_with_defaults(environment, deepcopy(row["payload"])),
        )
        self._last_good_snapshots[(environment, owner)] = snapshot
        return ConfigReloadResult(snapshot=snapshot)

    def current_version(self, environment: Environment, username: str | None = None) -> str | None:
        """Return the newest active config version for an environment."""

        row = self._latest_config_row(environment, username=username)
        return row["version"] if row else None

    def latest_config_owner(
        self,
        environment: Environment,
        *,
        allowed_usernames: tuple[str, ...] = (),
    ) -> str | None:
        """Return the newest active user config owner for scheduler reloads.

        REQ: REQ-UI-007
        """

        allowed = {
            owner
            for owner in (normalize_config_username(username) for username in allowed_usernames)
            if owner != SHARED_CONFIG_USERNAME
        }
        candidates: list[tuple[dict, str]] = []
        for row in self.registry.state.rows("shared.config_versions"):
            owner = normalize_config_username(row.get("username"))
            if row["environment"] != environment.value:
                continue
            if not row["active"] or owner == SHARED_CONFIG_USERNAME:
                continue
            if allowed and owner not in allowed:
                continue
            candidates.append((row, owner))
        if not candidates:
            return None
        _, owner = max(candidates, key=lambda candidate: candidate[0]["created_at"])
        return owner

    def _latest_config_row(self, environment: Environment, username: str | None = None) -> dict | None:
        owner = normalize_config_username(username)
        rows = [
            row
            for row in self.registry.state.rows("shared.config_versions")
            if row["environment"] == environment.value and row["active"]
        ]
        owner_rows = [
            row
            for row in rows
            if normalize_config_username(row.get("username")) == owner
        ]
        if owner_rows:
            return max(owner_rows, key=lambda row: row["created_at"])
        if owner == SHARED_CONFIG_USERNAME:
            return None
        shared_rows = [
            row
            for row in rows
            if normalize_config_username(row.get("username")) == SHARED_CONFIG_USERNAME
        ]
        if not shared_rows:
            return None
        return max(shared_rows, key=lambda row: row["created_at"])

    def _deactivate_active_versions(self, environment: Environment, username: str | None = None) -> None:
        owner = normalize_config_username(username)
        for row in self.registry.state.rows("shared.config_versions"):
            if (
                row["environment"] == environment.value
                and normalize_config_username(row.get("username")) == owner
            ):
                row["active"] = False

    def _current_payload(self, environment: Environment, username: str | None = None) -> dict[str, Any]:
        row = self._latest_config_row(environment, username=username)
        if row is not None:
            return self._payload_with_defaults(environment, deepcopy(row["payload"]))
        return self._default_payload(environment)

    def _default_payload(self, environment: Environment) -> dict[str, Any]:
        payload = deepcopy(self._default_payload_factory())
        # A deployed live-capable runtime is not an operator-approved config.
        # Bootstrap and degraded reloads must fail closed until persistence
        # supplies a saved version that explicitly enables live execution.
        payload["live_enabled"] = False
        return self._with_stock_universe_snapshots(environment, payload)

    def _payload_with_defaults(
        self,
        environment: Environment,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        defaults = deepcopy(self._default_payload_factory())
        defaults["live_enabled"] = False
        merged = _deep_merge_missing(defaults, payload)
        return self._with_stock_universe_snapshots(environment, merged)

    def _with_stock_universe_snapshots(
        self,
        environment: Environment,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        alpaca_config = payload.setdefault("alpaca", {})
        if not isinstance(alpaca_config, dict):
            return payload
        refresh_config = alpaca_config.get("preset_refresh")
        sources = {}
        if isinstance(refresh_config, dict) and isinstance(refresh_config.get("sources"), dict):
            sources = refresh_config["sources"]
        alpaca_config["preset_refresh"] = {
            **DEFAULT_ALPACA_PRESET_REFRESH_CONFIG,
            **(refresh_config if isinstance(refresh_config, dict) else {}),
            "sources": {
                **DEFAULT_ALPACA_PRESET_REFRESH_CONFIG["sources"],
                **sources,
            },
        }
        snapshots = self._latest_preset_snapshots(environment)
        alpaca_config["preset_snapshots"] = snapshots
        if "symbol_presets" in alpaca_config or "custom_symbols" in alpaca_config:
            alpaca_config["symbol_universe"] = resolve_alpaca_symbol_universe(payload)
        alpaca_config["preset_metadata"] = stock_universe_metadata(payload)
        return payload

    def _latest_preset_snapshots(self, environment: Environment) -> dict[str, dict[str, Any]]:
        try:
            rows = self.registry.shared().alpaca_symbol_preset_snapshots(environment=environment)
        except PersistenceUnavailableError:
            return seed_alpaca_preset_snapshots()
        snapshots = latest_preset_snapshot_payloads(rows)
        return snapshots or seed_alpaca_preset_snapshots()

    def _validated_patch_value(self, patch: ConfigPatchOperation) -> Any:
        if patch.op not in {"add", "replace", "remove"}:
            raise ConfigValidationError("unsupported config patch operation")
        if patch.path == "funding" and patch.op == "remove":
            raise ConfigValidationError("funding config cannot be removed")
        if patch.op == "remove":
            return None

        parts = patch.path.split(".")
        value = patch.value
        if patch.path == "funding":
            try:
                return FundingConfig.model_validate(value).model_dump(mode="json")
            except (TypeError, ValueError) as exc:
                raise ConfigValidationError(f"invalid funding config: {exc}") from exc
        if patch.path == "default_selected_venue":
            if value not in {venue.value for venue in Venue}:
                raise ConfigValidationError("unsupported default venue")
            return value
        if patch.path == "trading_profile":
            if value != ACTIVE_STOCK_DAY_TRADER_PROFILE:
                raise ConfigValidationError("unsupported trading profile")
            return value
        if patch.path == "live_enabled":
            return self._bool(value, patch.path)
        if parts[:1] == ["venues"] and len(parts) == 3 and parts[2] == "enabled":
            self._require_supported_venue(parts[1])
            return self._bool(value, patch.path)
        if patch.path == "trading_loop_interval_seconds":
            interval = self._positive_int(value, patch.path)
            if interval < self.SAFE_MINIMUM_LOOP_INTERVAL_SECONDS:
                raise ConfigValidationError("trading loop interval is below safe minimum")
            return interval
        if parts[:1] == ["strategies"] and len(parts) >= 3:
            self._require_strategy(parts[1])
            if len(parts) == 3 and parts[2] == "enabled":
                return self._bool(value, patch.path)
            if len(parts) >= 4 and parts[2] == "settings":
                return value
        if parts[:1] == ["scanner"] and len(parts) >= 3:
            return self._validated_scanner_patch_value(parts, value, patch.path)
        if patch.path == "reasoning.max_prompts_per_provider_per_run":
            return self._positive_int(value, patch.path)
        if parts[:1] == ["reasoning"] and len(parts) >= 3:
            return self._validated_reasoning_patch_value(parts, value, patch.path)
        if parts[:1] == ["execution"] and len(parts) >= 2:
            return self._validated_execution_patch_value(parts, value, patch.path)
        if parts[:1] == ["exit"] and len(parts) >= 3:
            return self._validated_exit_patch_value(parts, value, patch.path)
        if parts[:1] == ["llm"] and len(parts) >= 3:
            self._require_model_provider(parts[1])
            if len(parts) == 3 and parts[2] == "budget_usd":
                return str(self._positive_decimal(value, patch.path))
            if len(parts) >= 4 and parts[2] == "settings":
                if len(parts) == 4 and parts[3] == "model" and parts[1] == ModelProvider.OPENAI.value:
                    if value not in OPENAI_SCORING_MODEL_OPTIONS:
                        allowed = ", ".join(OPENAI_SCORING_MODEL_OPTIONS)
                        raise ConfigValidationError(f"OpenAI scoring model must be one of: {allowed}")
                    return value
                if value is None:
                    raise ConfigValidationError(f"{patch.path} cannot be null")
                return value
        if patch.path in {
            "risk.polymarket.max_position_usd",
            "risk.polymarket.max_daily_loss_usd",
            "risk.kalshi.max_position_usd",
            "risk.kalshi.max_daily_loss_usd",
            "risk.alpaca.max_position_usd",
            "risk.alpaca.max_daily_loss_usd",
        }:
            return str(self._positive_decimal(value, patch.path))
        if patch.path in {
            "risk.polymarket.max_open_positions",
            "risk.kalshi.max_open_positions",
            "risk.alpaca.max_open_positions",
            "notifications.cooldown_seconds",
        }:
            return self._positive_int(value, patch.path)
        if patch.path in {
            "risk.polymarket.market_order_slippage_threshold",
            "risk.kalshi.market_order_slippage_threshold",
            "risk.alpaca.max_portfolio_allocation_per_symbol",
            "risk.alpaca.market_order_slippage_threshold",
        }:
            return str(self._ratio(value, patch.path))
        if patch.path == "alpaca.account_mode":
            if value not in {"paper", "live"}:
                raise ConfigValidationError("alpaca account mode must be paper or live")
            return value
        if patch.path == "alpaca.allow_shorting":
            return self._bool(value, patch.path)
        if patch.path == "alpaca.symbol_universe":
            if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
                raise ConfigValidationError("alpaca symbol universe must be a non-empty list")
            return normalize_symbol_list(value)
        if patch.path == "alpaca.symbol_presets":
            if not isinstance(value, list):
                raise ConfigValidationError("alpaca symbol presets must be a list")
            return [
                preset
                for preset in (normalize_preset_name(item) for item in value)
                if preset
            ]
        if patch.path == "alpaca.custom_symbols":
            if not isinstance(value, list):
                raise ConfigValidationError("alpaca custom symbols must be a list")
            return normalize_symbol_list(value)
        if patch.path == "alpaca.custom_presets":
            if not isinstance(value, dict):
                raise ConfigValidationError("alpaca custom presets must be a mapping")
            normalized_presets = {}
            for preset_name, symbols in value.items():
                normalized_name = normalize_preset_name(preset_name)
                if not normalized_name or not isinstance(symbols, list):
                    raise ConfigValidationError("alpaca custom presets must map names to symbol lists")
                normalized_presets[normalized_name] = normalize_symbol_list(symbols)
            return normalized_presets
        if parts[:2] == ["alpaca", "preset_refresh"]:
            return self._validated_preset_refresh_patch_value(parts, value, patch.path)
        if patch.path == "notifications.recipients":
            if not isinstance(value, dict) or not value:
                raise ConfigValidationError("notification recipients must be a non-empty mapping")
            return value
        if patch.path == "notifications.email_on_trade_placed":
            return self._bool(value, patch.path)
        if parts[:2] == ["notifications", "thresholds"] and len(parts) == 3:
            return str(self._positive_decimal(value, patch.path))
        if patch.path == "notifications.digest_schedule_utc":
            if not isinstance(value, str) or not _valid_hhmm(value):
                raise ConfigValidationError("digest schedule must be HH:MM UTC")
            return value
        raise ConfigValidationError(f"unsupported config path: {patch.path}")

    def _validated_scanner_patch_value(self, parts: list[str], value: Any, path: str) -> Any:
        if parts[1] not in {"polymarket", "alpaca", Venue.KALSHI.value}:
            raise ConfigValidationError("unsupported scanner venue")
        if len(parts) == 3 and parts[2] in {"allowed_categories", "blocked_categories"}:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ConfigValidationError(f"{path} must be a string list")
            return [item.strip() for item in value if item.strip()]
        if len(parts) >= 4 and parts[2] == "strategies":
            if parts[3] not in {
                "momentum",
                "mean_reversion",
                "gap",
                "liquidity",
                "volatility",
                "unusual_volume",
            }:
                raise ConfigValidationError("unsupported stock scanner strategy")
            if len(parts) == 5 and parts[4] == "enabled":
                return self._bool(value, path)
            if len(parts) == 5:
                return str(self._positive_decimal(value, path))
            raise ConfigValidationError(f"unsupported config path: {path}")
        if parts[-1] in {"min_history_bars", "target_wallet_recent_hours"}:
            return self._positive_int(value, path)
        if parts[1] in {"polymarket", Venue.KALSHI.value} and parts[-1] == "market_data_limit":
            limit = self._positive_int(value, path)
            if limit > MAX_POLYMARKET_MARKET_DATA_LIMIT:
                raise ConfigValidationError(
                    f"{path} cannot exceed {MAX_POLYMARKET_MARKET_DATA_LIMIT}"
                )
            return limit
        if parts[-1] in {
            "min_depth",
            "min_liquidity",
            "max_spread",
            "min_volume",
            "min_hours_to_resolution",
            "max_hours_to_resolution",
            "min_quote_liquidity",
        }:
            return str(self._positive_decimal(value, path))
        raise ConfigValidationError(f"unsupported config path: {path}")

    def _validated_reasoning_patch_value(self, parts: list[str], value: Any, path: str) -> Any:
        if parts[1] not in {"polymarket", "alpaca"}:
            raise ConfigValidationError("unsupported reasoning venue")
        if len(parts) == 3 and parts[2] == "prompt_version":
            if not isinstance(value, str) or not value.strip():
                raise ConfigValidationError(f"{path} must be a non-empty string")
            return value.strip()
        if len(parts) == 3 and parts[2] in {"min_confidence", "min_edge"}:
            return str(self._ratio(value, path))
        if parts[1] == "polymarket" and len(parts) == 3 and parts[2] == "checks":
            allowed = {"base_rate", "news", "whale_check", "disposition"}
            if not isinstance(value, list) or not set(value) <= allowed:
                raise ConfigValidationError("unsupported Polymarket reasoning check")
            return list(dict.fromkeys(value))
        if parts[1] == "alpaca" and len(parts) == 3 and parts[2] == "inputs":
            allowed = {
                "price_action",
                "historical_bars",
                "volume",
                "sector",
                "index_membership",
                "event_news",
                "risk",
                "liquidity",
            }
            if not isinstance(value, list) or not set(value) <= allowed:
                raise ConfigValidationError("unsupported Alpaca reasoning input")
            return list(dict.fromkeys(value))
        raise ConfigValidationError(f"unsupported config path: {path}")

    def _validated_execution_patch_value(self, parts: list[str], value: Any, path: str) -> Any:
        if len(parts) == 2 and parts[1] == "market_data_freshness_seconds":
            return self._positive_int(value, path)
        if len(parts) == 2 and parts[1] == "order_type":
            if value not in {"market", "limit"}:
                raise ConfigValidationError("execution order type must be market or limit")
            return value
        if len(parts) == 3 and parts[1] == "alpaca" and parts[2] == "model_capital_usd":
            return str(self._positive_decimal(value, path))
        raise ConfigValidationError(f"unsupported config path: {path}")

    def _validated_exit_patch_value(self, parts: list[str], value: Any, path: str) -> Any:
        if parts[1] not in {"polymarket", "alpaca"}:
            raise ConfigValidationError("unsupported exit venue")
        if parts[1] == "alpaca" and len(parts) == 3 and parts[2] == "market_hours_only":
            return self._bool(value, path)
        if parts[1] == "alpaca" and len(parts) == 3 and parts[2] == "close_before_market_close_minutes":
            close_before = self._positive_int(value, path)
            if close_before > 120:
                raise ConfigValidationError("stock close window cannot exceed 120 minutes")
            return close_before
        if parts[-1] in {"max_thesis_age_hours", "max_position_age_hours"}:
            return str(self._positive_decimal(value, path))
        if parts[-1] in {
            "profit_target_usd",
            "profit_target_pct",
            "volume_spike_multiplier",
            "min_stale_price_move_pct",
            "stop_loss_pct",
            "trailing_stop_pct",
        }:
            return str(self._positive_decimal(value, path))
        raise ConfigValidationError(f"unsupported config path: {path}")

    def _validated_preset_refresh_patch_value(self, parts: list[str], value: Any, path: str) -> Any:
        if len(parts) != 3:
            raise ConfigValidationError(f"unsupported config path: {path}")
        if parts[2] == "enabled":
            return self._bool(value, path)
        if parts[2] in {"cadence_hours", "stale_after_hours"}:
            return self._positive_int(value, path)
        if parts[2] == "sources":
            if not isinstance(value, dict):
                raise ConfigValidationError("alpaca preset refresh sources must be a mapping")
            sources = {}
            for preset_name, source_url in value.items():
                normalized_name = normalize_preset_name(preset_name)
                if not normalized_name or not isinstance(source_url, str) or not source_url.strip():
                    raise ConfigValidationError("alpaca preset refresh sources must map presets to URLs")
                sources[normalized_name] = source_url.strip()
            return sources
        raise ConfigValidationError(f"unsupported config path: {path}")

    def _apply_patch(self, payload: dict[str, Any], patch: ConfigPatchOperation, value: Any) -> None:
        parts = patch.path.split(".")
        target = payload
        for part in parts[:-1]:
            child = target.get(part)
            if not isinstance(child, dict):
                child = {}
                target[part] = child
            target = child
        if patch.op == "remove":
            target.pop(parts[-1], None)
            return
        target[parts[-1]] = value

    def _value_at_path(self, payload: dict[str, Any], path: str) -> Any:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return deepcopy(current)

    def _require_supported_venue(self, raw: str) -> None:
        if raw not in {venue.value for venue in Venue}:
            raise ConfigValidationError("unsupported venue")

    def _require_strategy(self, raw: str) -> None:
        if raw not in self.KNOWN_STRATEGIES:
            raise ConfigValidationError("unsupported strategy")

    def _require_model_provider(self, raw: str) -> None:
        if raw not in {provider.value for provider in ModelProvider}:
            raise ConfigValidationError("unsupported model provider")

    def _bool(self, value: Any, path: str) -> bool:
        if not isinstance(value, bool):
            raise ConfigValidationError(f"{path} must be a boolean")
        return value

    def _positive_decimal(self, value: Any, path: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ConfigValidationError(f"{path} must be a decimal") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise ConfigValidationError(f"{path} must be positive")
        return parsed

    def _positive_int(self, value: Any, path: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigValidationError(f"{path} must be a positive integer")
        return value

    def _ratio(self, value: Any, path: str) -> Decimal:
        parsed = self._positive_decimal(value, path)
        if parsed > 1:
            raise ConfigValidationError(f"{path} must be between 0 and 1")
        return parsed

    def _degraded_reload(
        self,
        environment: Environment,
        message: str,
        username: str | None = None,
    ) -> ConfigReloadResult:
        owner = normalize_config_username(username)
        prior = self._last_good_snapshots.get((environment, owner))
        if prior is None:
            prior = RuntimeConfigSnapshot(
                environment=environment,
                version="bootstrap",
                payload=self._default_payload(environment),
            )
            self._last_good_snapshots[(environment, owner)] = prior

        health_message = f"config reload failed: {message}"
        try:
            self.registry.shared().record_system_health(
                component="config",
                status="degraded",
                message=health_message,
                environment=environment,
            )
        except PersistenceUnavailableError:
            pass
        return ConfigReloadResult(
            snapshot=prior,
            degraded=True,
            error_message=health_message,
        )


DEFAULT_ALPACA_SYMBOL_UNIVERSE = tuple(
    resolve_alpaca_symbol_universe(
        {
            "alpaca": {
                "symbol_presets": list(DEFAULT_ALPACA_SYMBOL_PRESETS),
                "custom_symbols": [],
                "preset_snapshots": seed_alpaca_preset_snapshots(),
            }
        }
    )
)


def default_config_payload() -> dict[str, Any]:
    """Return safe runtime config defaults for dashboard editing.

    REQ: REQ-UI-005, REQ-EXE-001, REQ-EXE-007, REQ-STR-002, REQ-KAL-001, REQ-KAL-009
    """

    payload = {
        "default_selected_venue": Venue.ALPACA.value,
        "trading_profile": ACTIVE_STOCK_DAY_TRADER_PROFILE,
        "live_enabled": False,
        "venues": {
            Venue.POLYMARKET_US.value: {"enabled": False},
            Venue.POLYMARKET_INTERNATIONAL.value: {"enabled": False},
            Venue.ALPACA.value: {"enabled": True},
            Venue.KALSHI.value: {"enabled": False},
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
                "settings": {
                    "model": DEFAULT_CLAUDE_SCORING_MODEL,
                    "max_tokens": DEFAULT_CLAUDE_SCORING_MAX_TOKENS,
                    "budget_window_hours": 24,
                },
            },
            ModelProvider.OPENAI.value: {
                "budget_usd": "20.00",
                "settings": {
                    "model": DEFAULT_OPENAI_SCORING_MODEL,
                    "max_output_tokens": DEFAULT_OPENAI_SCORING_MAX_OUTPUT_TOKENS,
                    "reasoning_effort": DEFAULT_OPENAI_SCORING_REASONING_EFFORT,
                    "budget_window_hours": 24,
                },
            },
        },
        "risk": {
            "polymarket": {
                "max_position_usd": "25.00",
                "max_daily_loss_usd": "50.00",
                "max_open_positions": 5,
                "market_order_slippage_threshold": "0.02",
            },
            "alpaca": {
                "max_position_usd": "100.00",
                "max_daily_loss_usd": "100.00",
                "max_open_positions": 5,
                "max_portfolio_allocation_per_symbol": "0.10",
                "market_order_slippage_threshold": "0.005",
            },
            Venue.KALSHI.value: {
                "max_position_usd": "25.00",
                "max_daily_loss_usd": "50.00",
                "max_open_positions": 5,
                "market_order_slippage_threshold": "0.02",
            },
        },
        "scanner": DEFAULT_SCANNER_CONFIG,
        "reasoning": DEFAULT_REASONING_CONFIG,
        "strategy_consensus": DEFAULT_STRATEGY_CONSENSUS_CONFIG,
        "execution": DEFAULT_EXECUTION_CONFIG,
        "exit": DEFAULT_EXIT_CONFIG,
        "alpaca": {
            "account_mode": "paper",
            "allow_shorting": False,
            "symbol_presets": list(DEFAULT_ALPACA_SYMBOL_PRESETS),
            "custom_symbols": [],
            "custom_presets": {},
            "preset_refresh": DEFAULT_ALPACA_PRESET_REFRESH_CONFIG,
            "preset_snapshots": seed_alpaca_preset_snapshots(),
            "symbol_universe": list(DEFAULT_ALPACA_SYMBOL_UNIVERSE),
        },
        "notifications": {
            "recipients": {},
            "thresholds": {},
            "cooldown_seconds": 1800,
            "digest_schedule_utc": "13:00",
            "email_on_trade_placed": True,
        },
        "funding": deepcopy(DEFAULT_FUNDING_CONFIG),
    }
    payload["alpaca"]["preset_metadata"] = stock_universe_metadata(payload)
    return payload


def trading_profile_patches(profile: str) -> list[ConfigPatchOperation]:
    """Return one audited patch set for a supported trading profile."""

    if profile != ACTIVE_STOCK_DAY_TRADER_PROFILE:
        raise ConfigValidationError("unsupported trading profile")
    payload = default_config_payload()
    return [
        ConfigPatchOperation(
            op="replace",
            path=path,
            value=deepcopy(_profile_value_at_path(payload, path)),
        )
        for path in ACTIVE_STOCK_DAY_TRADER_PROFILE_PATHS
    ]


def _profile_value_at_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ConfigValidationError(f"trading profile path is unavailable: {path}")
        value = value[part]
    return value


def _deep_merge_missing(defaults: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    for key, value in payload.items():
        if isinstance(defaults.get(key), dict) and isinstance(value, dict):
            defaults[key] = _deep_merge_missing(defaults[key], value)
        else:
            defaults[key] = value
    return defaults


def _valid_hhmm(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59
