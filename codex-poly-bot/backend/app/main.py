"""FastAPI backend application bootstrap.

REQ: REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-005,
REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-009, REQ-UI-010,
REQ-UI-011, REQ-OBS-004, REQ-OBS-005, REQ-OBS-006
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import build_dashboard_router
from app.db import RepositoryRegistry
from app.domain import Environment
from app.services import AuthService, ConfigService, KillSwitchService


@dataclass(frozen=True)
class AppSettings:
    """Runtime settings for the FastAPI app.

    REQ: REQ-UI-001, REQ-UI-002, REQ-UI-003
    """

    allowed_usernames: tuple[str, ...] = ("yaw",)
    signing_secret: str = "local-dev-session-secret"
    trusted_origins: tuple[str, ...] = ("http://localhost:3000",)
    csrf_token: str = "local-dev-csrf-token"
    environment: Environment = Environment.LOCAL


@dataclass
class DashboardApiServices:
    """Shared services used by API routers.

    REQ: REQ-UI-001, REQ-OBS-004
    """

    registry: RepositoryRegistry
    auth: AuthService
    config: ConfigService
    kill_switch: KillSwitchService


def build_dashboard_api_services(
    settings: AppSettings,
    registry: RepositoryRegistry | None = None,
) -> DashboardApiServices:
    """Build a service container with one shared repository registry.

    REQ: REQ-UI-001, REQ-OBS-004
    """

    shared_registry = registry or RepositoryRegistry()
    auth = AuthService(
        allowed_usernames=set(settings.allowed_usernames),
        signing_secret=settings.signing_secret,
        trusted_origins=set(settings.trusted_origins),
        registry=shared_registry,
    )
    return DashboardApiServices(
        registry=shared_registry,
        auth=auth,
        config=ConfigService(shared_registry),
        kill_switch=KillSwitchService(shared_registry),
    )


def create_app(
    settings: AppSettings | None = None,
    services: DashboardApiServices | None = None,
) -> FastAPI:
    """Create the FastAPI backend app with dashboard API routes.

    REQ: REQ-UI-001, REQ-OBS-006
    """

    resolved_settings = settings or AppSettings()
    resolved_services = services or build_dashboard_api_services(resolved_settings)
    app = FastAPI(title="codex-poly-bot backend")
    app.state.settings = resolved_settings
    app.state.services = resolved_services

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.trusted_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_dashboard_router(resolved_settings, resolved_services))
    return app
