"""FastAPI backend application bootstrap.

REQ: REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-005,
REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-009, REQ-UI-010,
REQ-UI-011, REQ-OBS-004, REQ-OBS-005, REQ-OBS-006
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import build_dashboard_router
from app.db import (
    DatabaseState,
    PersistenceConfigurationError,
    PersistenceUnavailableError,
    PersistentDatabaseState,
    RepositoryRegistry,
    create_session_factory,
    run_migrations,
)
from app.domain import Environment, Venue
from app.observability import configure_observability
from app.services import AuthService, ConfigService, KillSwitchService
from app.services.config_service import DEFAULT_ALPACA_SYMBOL_UNIVERSE
from app.services.stock_universe import (
    DEFAULT_ALPACA_SYMBOL_PRESETS,
    normalize_symbol_list,
    resolve_alpaca_symbol_universe,
)
from app.services.runtime_status_service import RuntimeStatusService


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppSettings:
    """Runtime settings for the FastAPI app.

    REQ: REQ-UI-001, REQ-UI-002, REQ-UI-003
    """

    allowed_usernames: tuple[str, ...] = ("yaw",)
    signing_secret: str = "local-dev-session-secret"
    trusted_origins: tuple[str, ...] = ("http://localhost:3100", "http://127.0.0.1:3100")
    csrf_token: str = "local-dev-csrf-token"
    environment: Environment = Environment.LOCAL
    runtime_env: dict[str, str] = field(default_factory=dict)
    database_url: str = ""
    runtime_config_username: str | None = None
    live_enabled: bool = False
    trading_account_mode: str = "local"
    default_selected_venue: Venue = Venue.POLYMARKET_US
    polymarket_us_enabled: bool = False
    polymarket_international_enabled: bool = False
    alpaca_enabled: bool = False
    polymarket_slippage_threshold: str = "0.02"
    alpaca_slippage_threshold: str = "0.005"
    alpaca_account_status: str = "active"
    alpaca_symbol_presets: tuple[str, ...] = DEFAULT_ALPACA_SYMBOL_PRESETS
    alpaca_custom_symbols: tuple[str, ...] = ()
    alpaca_symbol_universe: tuple[str, ...] = DEFAULT_ALPACA_SYMBOL_UNIVERSE
    polygon_rpc_url: str = ""
    polygon_order_filled_max_block_range: int = 500
    polygon_order_filled_max_windows: int = 1
    polygon_order_filled_import_cadence_minutes: int = 60
    polygon_order_filled_retry_split: bool = True
    ses_identity_email: str = ""
    notification_recipients: dict[str, str] = field(default_factory=dict)
    background_worker_enabled: bool = False
    worker_heartbeat_interval_seconds: int = 60

    @classmethod
    def from_env(cls) -> "AppSettings":
        """Load deployed app settings from environment variables.

        REQ: REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-006
        """

        runtime_env = {key: value for key, value in os.environ.items()}
        allowed_usernames = _csv_env("DASHBOARD_ALLOWED_USERS", ("yaw",))
        return cls(
            allowed_usernames=allowed_usernames,
            signing_secret=os.environ.get("BACKEND_TOKEN_SIGNING_SECRET", "local-dev-session-secret"),
            trusted_origins=_trusted_origins_from_env(),
            csrf_token=os.environ.get("DASHBOARD_CSRF_TOKEN", "local-dev-csrf-token"),
            environment=_environment_from_env(),
            runtime_env=runtime_env,
            database_url=os.environ.get("DATABASE_URL", "").strip(),
            runtime_config_username=_runtime_config_username_from_env(allowed_usernames),
            live_enabled=_bool_env("LIVE_ENABLED", False),
            trading_account_mode=os.environ.get("TRADING_ACCOUNT_MODE", "local"),
            default_selected_venue=_venue_from_env(),
            polymarket_us_enabled=_bool_env("POLYMARKET_US_ENABLED", False),
            polymarket_international_enabled=_bool_env("POLYMARKET_INTERNATIONAL_ENABLED", False),
            alpaca_enabled=_bool_env("ALPACA_ENABLED", False),
            polymarket_slippage_threshold=os.environ.get("POLYMARKET_MARKET_ORDER_SLIPPAGE", "0.02"),
            alpaca_slippage_threshold=os.environ.get("ALPACA_MARKET_ORDER_SLIPPAGE", "0.005"),
            alpaca_account_status=os.environ.get("ALPACA_ACCOUNT_STATUS", "active").strip().lower() or "active",
            alpaca_symbol_presets=_symbol_presets_from_env(),
            alpaca_custom_symbols=_custom_symbols_from_env(),
            alpaca_symbol_universe=_symbol_universe_from_env(),
            polygon_rpc_url=os.environ.get("POLYGON_RPC_URL", "").strip(),
            polygon_order_filled_max_block_range=_positive_int_env(
                "POLYGON_ORDER_FILLED_MAX_BLOCK_RANGE",
                500,
            ),
            polygon_order_filled_max_windows=_positive_int_env("POLYGON_ORDER_FILLED_MAX_WINDOWS", 1),
            polygon_order_filled_import_cadence_minutes=_positive_int_env(
                "POLYGON_ORDER_FILLED_IMPORT_CADENCE_MINUTES",
                60,
            ),
            polygon_order_filled_retry_split=_bool_env("POLYGON_ORDER_FILLED_RETRY_SPLIT", True),
            ses_identity_email=os.environ.get("SES_IDENTITY_EMAIL", "").strip(),
            notification_recipients=_notification_recipients_from_env(),
            background_worker_enabled=_bool_env("ENABLE_BACKGROUND_WORKER", False),
            worker_heartbeat_interval_seconds=_int_env("WORKER_HEARTBEAT_INTERVAL_SECONDS", 60),
        )


@dataclass
class DashboardApiServices:
    """Shared services used by API routers.

    REQ: REQ-UI-001, REQ-OBS-004
    """

    registry: RepositoryRegistry
    auth: AuthService
    config: ConfigService
    kill_switch: KillSwitchService
    runtime_status: RuntimeStatusService


def build_dashboard_api_services(
    settings: AppSettings,
    registry: RepositoryRegistry | None = None,
) -> DashboardApiServices:
    """Build a service container with one shared repository registry.

    REQ: REQ-UI-001, REQ-OBS-004
    """

    shared_registry = registry or _repository_registry_from_settings(settings)
    auth = AuthService(
        allowed_usernames=set(settings.allowed_usernames),
        signing_secret=settings.signing_secret,
        trusted_origins=set(settings.trusted_origins),
        registry=shared_registry,
    )
    runtime_status = RuntimeStatusService(settings=settings, registry=shared_registry)
    return DashboardApiServices(
        registry=shared_registry,
        auth=auth,
        config=ConfigService(
            shared_registry,
            default_payload_factory=runtime_status.runtime_config_payload,
        ),
        kill_switch=KillSwitchService(shared_registry),
        runtime_status=runtime_status,
    )


def create_app(
    settings: AppSettings | None = None,
    services: DashboardApiServices | None = None,
) -> FastAPI:
    """Create the FastAPI backend app with dashboard API routes.

    REQ: REQ-UI-001, REQ-OBS-006
    """

    resolved_settings = settings or AppSettings.from_env()
    resolved_services = services or build_dashboard_api_services(resolved_settings)
    app = FastAPI(title="codex-poly-bot backend")
    app.state.settings = resolved_settings
    app.state.services = resolved_services
    app.state.worker_heartbeat_task = None
    resolved_services.runtime_status.record_worker_heartbeat(message="backend startup")
    configure_observability(app, settings=resolved_settings)

    if resolved_settings.background_worker_enabled:

        @app.on_event("startup")
        async def _start_worker_heartbeat() -> None:
            app.state.worker_heartbeat_task = asyncio.create_task(
                _worker_heartbeat_loop(
                    services=resolved_services,
                    settings=resolved_settings,
                    environment=resolved_settings.environment,
                    interval_seconds=resolved_settings.worker_heartbeat_interval_seconds,
                )
            )

        @app.on_event("shutdown")
        async def _stop_worker_heartbeat() -> None:
            task = app.state.worker_heartbeat_task
            if task is None:
                return
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.trusted_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_dashboard_router(resolved_settings, resolved_services))
    return app


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    values = tuple(item.strip() for item in os.environ.get(name, "").split(",") if item.strip())
    return values or default


def _runtime_config_username_from_env(allowed_usernames: tuple[str, ...]) -> str | None:
    explicit = os.environ.get("RUNTIME_CONFIG_USERNAME", "").strip()
    if explicit:
        return explicit
    if len(allowed_usernames) == 1:
        return allowed_usernames[0]
    return None


def _repository_registry_from_settings(settings: AppSettings) -> RepositoryRegistry:
    if not settings.database_url:
        return RepositoryRegistry()
    try:
        session_factory = create_session_factory(settings.database_url)
        engine = session_factory.kw.get("bind")
        if engine is not None:
            with engine.begin() as connection:
                run_migrations(connection)
        return RepositoryRegistry(PersistentDatabaseState(session_factory))
    except PersistenceConfigurationError:
        LOGGER.exception("Postgres persistence is misconfigured")
    except Exception:
        LOGGER.exception("Postgres persistence is unavailable")
    return RepositoryRegistry(DatabaseState(available=False))


def _scheduler_config_username(
    settings: AppSettings,
    services: DashboardApiServices,
    environment: Environment,
) -> str | None:
    """Resolve the runtime config owner used by the background scheduler.

    REQ: REQ-UI-007
    """

    if settings.runtime_config_username:
        return settings.runtime_config_username
    if len(settings.allowed_usernames) == 1:
        return settings.allowed_usernames[0]
    try:
        return services.config.latest_config_owner(
            environment,
            allowed_usernames=settings.allowed_usernames,
        )
    except PersistenceUnavailableError:
        LOGGER.exception("scheduler config owner lookup failed")
        return None


def _trusted_origins_from_env() -> tuple[str, ...]:
    configured = list(_csv_env("DASHBOARD_TRUSTED_ORIGINS", ()))
    nextauth_url = os.environ.get("NEXTAUTH_URL")
    if nextauth_url:
        configured.append(nextauth_url)
    return tuple(dict.fromkeys(configured)) or ("http://localhost:3100", "http://127.0.0.1:3100")


def _environment_from_env() -> Environment:
    raw_value = os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or Environment.LOCAL.value
    try:
        return Environment(raw_value)
    except ValueError:
        return Environment.LOCAL


def _venue_from_env() -> Venue:
    raw_value = os.environ.get("DEFAULT_SELECTED_VENUE", Venue.POLYMARKET_US.value)
    try:
        return Venue(raw_value)
    except ValueError:
        return Venue.POLYMARKET_US


def _symbol_universe_from_env() -> tuple[str, ...]:
    configured = _csv_env("ALPACA_SYMBOL_UNIVERSE", ())
    normalized = tuple(normalize_symbol_list(configured))
    if normalized:
        return normalized
    return tuple(
        resolve_alpaca_symbol_universe(
            {
                "alpaca": {
                    "symbol_presets": list(_csv_env("ALPACA_SYMBOL_PRESETS", DEFAULT_ALPACA_SYMBOL_PRESETS)),
                    "custom_symbols": list(_csv_env("ALPACA_CUSTOM_SYMBOLS", ())),
                }
            }
        )
    ) or DEFAULT_ALPACA_SYMBOL_UNIVERSE


def _symbol_presets_from_env() -> tuple[str, ...]:
    if os.environ.get("ALPACA_SYMBOL_UNIVERSE", "").strip():
        return ()
    return _csv_env("ALPACA_SYMBOL_PRESETS", DEFAULT_ALPACA_SYMBOL_PRESETS)


def _custom_symbols_from_env() -> tuple[str, ...]:
    if os.environ.get("ALPACA_SYMBOL_UNIVERSE", "").strip():
        return ()
    return tuple(normalize_symbol_list(_csv_env("ALPACA_CUSTOM_SYMBOLS", ())))


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(15, parsed)


def _positive_int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(1, parsed)


async def _worker_heartbeat_loop(
    *,
    services: DashboardApiServices,
    settings: AppSettings,
    environment: Environment,
    interval_seconds: int,
) -> None:
    while True:
        try:
            services.runtime_status.record_worker_heartbeat(
                status="running",
                message="scheduler tick started",
            )
            username = _scheduler_config_username(settings, services, environment)
            reload_result = services.config.config_for_next_loop(environment, username=username)
            config_payload = reload_result.snapshot.payload or services.runtime_status.runtime_config_payload()
            await asyncio.to_thread(
                services.runtime_status.trigger_scheduled_run,
                environment=environment,
                config_payload=config_payload,
            )
        except Exception:
            LOGGER.exception("background scheduler tick failed")
            services.runtime_status.record_worker_heartbeat(
                status="failed",
                message="scheduler tick failed",
            )
        await asyncio.sleep(interval_seconds)


def _notification_recipients_from_env() -> dict[str, str]:
    raw = os.environ.get("NOTIFICATION_RECIPIENTS", "").strip()
    recipients: dict[str, str] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        if ":" in item:
            name, email = item.split(":", 1)
        else:
            name, email = "operator", item
        if email.strip():
            recipients[name.strip() or "operator"] = email.strip()
    ses_identity = os.environ.get("SES_IDENTITY_EMAIL", "").strip()
    if not recipients and ses_identity:
        recipients["operator"] = ses_identity
    return recipients
