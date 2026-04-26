"""Local bootstrap and safe default configuration.

REQ: REQ-DEP-001, REQ-DEP-007, REQ-DEP-008, REQ-DEP-009, REQ-EXE-001,
REQ-VEN-002, REQ-VEN-003, REQ-EXE-012, REQ-ALP-013
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DIRECTORIES = ("backend", "frontend", "infra", "docs", "scripts")
REQUIRED_ENV_EXAMPLES = (
    ".env.example",
    "backend/.env.example",
    "frontend/.env.example",
    "infra/.env.example",
)
REQUIRED_COMPOSE_SERVICES = ("postgres", "backend", "frontend")
PRODUCTION_SECRET_KEYS = (
    "POLYMARKET_PRIVATE_KEY",
    "ALPACA_SECRET_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_CLIENT_SECRET",
    "AWS_SECRET_ACCESS_KEY",
)
SAFE_SECRET_PLACEHOLDERS = ("", "change-me", "set-locally", "optional-in-dry-run")


@dataclass(frozen=True)
class VenueDefault:
    """Default venue safety settings."""

    enabled: bool
    slippage_threshold: Decimal


@dataclass(frozen=True)
class SafeDefaults:
    """Runtime defaults used before Postgres config is available."""

    default_selected_venue: str
    live_enabled: bool
    venues: dict[str, VenueDefault]

    @property
    def global_execution_mode(self) -> str:
        """REQ: REQ-EXE-001"""
        return "live" if self.live_enabled else "dry_run"


@dataclass(frozen=True)
class LocalStartupCheck:
    """Local setup validation result."""

    ok: bool
    uses_production_secrets: bool
    missing_required_directories: tuple[str, ...]
    missing_env_examples: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class OperationGate:
    """Result of checking whether a disabled venue may perform an operation."""

    allowed: bool
    refusal_reason: str | None


def safe_defaults() -> SafeDefaults:
    """Return safe bootstrap defaults.

    REQ: REQ-VEN-002, REQ-VEN-003, REQ-EXE-001, REQ-EXE-012, REQ-ALP-013
    """
    return SafeDefaults(
        default_selected_venue="polymarket_us",
        live_enabled=False,
        venues={
            "polymarket_us": VenueDefault(enabled=False, slippage_threshold=Decimal("0.02")),
            "polymarket_international": VenueDefault(
                enabled=False,
                slippage_threshold=Decimal("0.02"),
            ),
            "alpaca": VenueDefault(enabled=False, slippage_threshold=Decimal("0.005")),
        },
    )


def load_runtime_defaults(explicit_venue: str | None = None, live_enabled: str | bool | None = None) -> SafeDefaults:
    """Load validated runtime defaults without requiring secrets.

    REQ: REQ-VEN-002, REQ-EXE-001, REQ-DEP-009
    """
    defaults = safe_defaults()
    selected_venue = explicit_venue or defaults.default_selected_venue
    if selected_venue not in defaults.venues:
        selected_venue = defaults.default_selected_venue
    return SafeDefaults(
        default_selected_venue=selected_venue,
        live_enabled=parse_live_enabled(live_enabled),
        venues=defaults.venues,
    )


def parse_live_enabled(value: str | bool | None) -> bool:
    """Parse live mode and fail closed for absent or invalid values.

    REQ: REQ-EXE-001
    """
    if value is True:
        return True
    if value is False or value is None:
        return False
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return False


def venue_operation_gate(venue: str, operation: str, defaults: SafeDefaults | None = None) -> OperationGate:
    """Return whether a venue may scan, score, or trade.

    REQ: REQ-VEN-003
    """
    config = defaults or safe_defaults()
    venue_config = config.venues.get(venue)
    if venue_config is None:
        return OperationGate(False, f"unsupported venue for {operation}")
    if not venue_config.enabled:
        return OperationGate(False, f"venue disabled for {operation}")
    return OperationGate(True, None)


def with_venue_enabled(defaults: SafeDefaults, venue: str, enabled: bool) -> SafeDefaults:
    """Return a copy of defaults with one venue enabled flag changed.

    REQ: REQ-VEN-003
    """
    if venue not in defaults.venues:
        raise KeyError(venue)
    venues = dict(defaults.venues)
    current = venues[venue]
    venues[venue] = VenueDefault(enabled=enabled, slippage_threshold=current.slippage_threshold)
    return SafeDefaults(
        default_selected_venue=defaults.default_selected_venue,
        live_enabled=defaults.live_enabled,
        venues=venues,
    )


def configured_slippage_threshold(venue: str, defaults: SafeDefaults | None = None) -> Decimal:
    """Return the venue market-order slippage threshold.

    REQ: REQ-EXE-012, REQ-ALP-013
    """
    config = defaults or safe_defaults()
    return config.venues[venue].slippage_threshold


def with_slippage_threshold(defaults: SafeDefaults, venue: str, raw_value: Decimal | str) -> SafeDefaults:
    """Return a copy of defaults with a validated slippage threshold override.

    REQ: REQ-EXE-012, REQ-ALP-013
    """
    if venue not in defaults.venues:
        raise KeyError(venue)
    try:
        threshold = Decimal(str(raw_value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("slippage threshold must be a decimal") from exc
    if threshold < 0:
        raise ValueError("slippage threshold cannot be negative")
    venues = dict(defaults.venues)
    current = venues[venue]
    venues[venue] = VenueDefault(enabled=current.enabled, slippage_threshold=threshold)
    return SafeDefaults(
        default_selected_venue=defaults.default_selected_venue,
        live_enabled=defaults.live_enabled,
        venues=venues,
    )


def market_order_slippage_allowed(venue: str, estimated_slippage: Decimal | str) -> bool:
    """Return whether estimated slippage is inside the configured limit.

    REQ: REQ-EXE-012, REQ-ALP-013
    """
    try:
        observed = Decimal(str(estimated_slippage))
    except (InvalidOperation, ValueError):
        return False
    return observed <= configured_slippage_threshold(venue)


def required_paths_exist(root: Path = PROJECT_ROOT) -> bool:
    """Return whether the local monorepo scaffold is present.

    REQ: REQ-DEP-001, REQ-DEP-008
    """
    return all((root / directory).is_dir() for directory in REQUIRED_DIRECTORIES)


def env_files_are_gitignored(root: Path = PROJECT_ROOT) -> bool:
    """Return whether local env files are covered by project gitignore.

    REQ: REQ-DEP-001
    """
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return False
    patterns = {
        line.strip()
        for line in gitignore.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    return {".env", ".env.local", "**/.env", "**/.env.local"}.issubset(patterns)


def compose_services(root: Path = PROJECT_ROOT) -> tuple[str, ...]:
    """Return service names declared in the local Docker Compose file.

    REQ: REQ-DEP-001
    """
    compose_file = root / "docker-compose.yml"
    if not compose_file.exists():
        return ()
    services: list[str] = []
    in_services = False
    for line in compose_file.read_text().splitlines():
        if line.startswith("services:"):
            in_services = True
            continue
        if in_services and line and not line.startswith(" "):
            break
        if in_services and line.startswith("  ") and not line.startswith("    "):
            name = line.strip().removesuffix(":")
            if name:
                services.append(name)
    return tuple(services)


def local_app_stack_services_ready(root: Path = PROJECT_ROOT) -> bool:
    """Return whether the Docker Compose stack declares required local services.

    REQ: REQ-DEP-001
    """
    return set(REQUIRED_COMPOSE_SERVICES).issubset(set(compose_services(root)))


def missing_required_directories(root: Path = PROJECT_ROOT) -> tuple[str, ...]:
    """Return missing scaffold directories."""
    return tuple(directory for directory in REQUIRED_DIRECTORIES if not (root / directory).is_dir())


def env_example_paths(root: Path = PROJECT_ROOT) -> tuple[Path, ...]:
    """Return expected env example paths.

    REQ: REQ-DEP-007
    """
    return tuple(root / path for path in REQUIRED_ENV_EXAMPLES)


def env_examples_have_no_secrets(root: Path = PROJECT_ROOT) -> bool:
    """Validate env examples document keys without embedding secrets.

    REQ: REQ-DEP-007
    """
    return not scan_env_examples_for_secret_values(root)


def scan_env_examples_for_secret_values(root: Path = PROJECT_ROOT) -> tuple[str, ...]:
    """Return any real-looking secret assignments found in `.env.example` files.

    REQ: REQ-DEP-007
    """
    findings: list[str] = []
    for path in env_example_paths(root):
        if not path.exists():
            findings.append(f"missing:{path.relative_to(root)}")
            continue
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, raw_value = stripped.split("=", 1)
            value = raw_value.strip().strip('"').strip("'")
            if key in PRODUCTION_SECRET_KEYS and value not in SAFE_SECRET_PLACEHOLDERS:
                findings.append(f"{path.relative_to(root)}:{key}")
    return tuple(findings)


def local_startup_check(root: Path = PROJECT_ROOT, env: dict[str, str] | None = None) -> LocalStartupCheck:
    """Validate that local startup can run without production trading secrets.

    REQ: REQ-DEP-001, REQ-DEP-008, REQ-DEP-009
    """
    environment = env or {}
    missing_dirs = missing_required_directories(root)
    missing_examples = tuple(
        str(path.relative_to(root)) for path in env_example_paths(root) if not path.exists()
    )
    secret_values = scan_env_examples_for_secret_values(root)
    provided_production_secrets = tuple(
        key for key in PRODUCTION_SECRET_KEYS if environment.get(key) not in (None, "")
    )
    errors = missing_dirs + missing_examples + secret_values
    return LocalStartupCheck(
        ok=not errors,
        uses_production_secrets=bool(provided_production_secrets),
        missing_required_directories=missing_dirs,
        missing_env_examples=missing_examples,
        errors=errors,
    )


def codex_web_ready(root: Path = PROJECT_ROOT) -> bool:
    """Return whether Codex web can inspect and test without production secrets.

    REQ: REQ-DEP-008, REQ-DEP-009
    """
    check = local_startup_check(root=root, env={})
    defaults = safe_defaults()
    return check.ok and not check.uses_production_secrets and defaults.global_execution_mode == "dry_run"
