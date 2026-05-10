"""Local bootstrap and safe default configuration.

REQ: REQ-DEP-001, REQ-DEP-007, REQ-DEP-008, REQ-DEP-009, REQ-EXE-001,
REQ-VEN-002, REQ-VEN-003, REQ-EXE-012, REQ-ALP-013
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
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
CI_WORKFLOW_RELATIVE_PATH = ".github/workflows/ci.yml"
CI_TEST_JOB_NAMES = ("backend-tests", "frontend-check")
CI_GATED_JOB_MARKERS = ("build", "deploy", "ecr", "ecs", "container")
AWS_INFRA_TEMPLATE_RELATIVE_PATH = "infra/cloudformation.yml"
AWS_PARAMETER_FILES = {
    "development": "infra/parameters/dev.json",
    "production": "infra/parameters/prod.json",
}
AWS_REQUIRED_RESOURCE_MARKERS = {
    "ecs_fargate": ("AWS::ECS::Service", "FARGATE"),
    "rds_postgres": ("AWS::RDS::DBInstance", "postgres"),
    "s3": ("AWS::S3::Bucket",),
    "secrets_manager": ("AWS::SecretsManager::Secret",),
    "cloudwatch": ("AWS::Logs::LogGroup",),
    "ses": ("AWS::SES::EmailIdentity",),
}


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
class CIWorkflowCheck:
    """CI test gate validation result.

    REQ: REQ-DEP-005
    """

    ok: bool
    workflow_path: Path
    test_jobs: tuple[str, ...]
    gated_jobs: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class AwsInfrastructureCheck:
    """AWS infrastructure template validation result.

    REQ: REQ-DEP-002
    """

    ok: bool
    region: str | None
    resources: tuple[str, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeploymentRegionCheck:
    """Deployment target region validation result.

    REQ: REQ-DEP-002
    """

    ok: bool
    region: str
    override_required: bool = False
    refusal_reason: str | None = None


@dataclass(frozen=True)
class DeploymentPlan:
    """GitHub Actions deployment plan for one branch.

    REQ: REQ-DEP-003, REQ-DEP-004, REQ-DEP-006
    """

    branch: str
    environment: str | None
    deploy_selected: bool
    build_images: tuple[str, ...] = ()
    ecr_publish: bool = False
    ecs_deploy: bool = False
    blocked_reason: str | None = None


@dataclass(frozen=True)
class DeploymentResourceSeparationCheck:
    """Development and production deployment separation result.

    REQ: REQ-DEP-010
    """

    ok: bool
    environments: tuple[str, ...]
    secret_prefixes: tuple[str, ...]
    errors: tuple[str, ...] = ()


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


def ci_workflow_path(root: Path = PROJECT_ROOT) -> Path:
    """Return the expected GitHub Actions CI workflow path.

    REQ: REQ-DEP-005
    """

    return root / CI_WORKFLOW_RELATIVE_PATH


def ci_workflow_check(root: Path = PROJECT_ROOT) -> CIWorkflowCheck:
    """Validate that CI tests gate build or deploy jobs.

    REQ: REQ-DEP-005
    """

    workflow_path = ci_workflow_path(root)
    errors: list[str] = []
    if not workflow_path.is_file():
        return CIWorkflowCheck(
            ok=False,
            workflow_path=workflow_path,
            test_jobs=(),
            gated_jobs=(),
            errors=(f"missing:{CI_WORKFLOW_RELATIVE_PATH}",),
        )

    workflow_text = workflow_path.read_text()
    job_names = _workflow_job_names(workflow_text)
    test_jobs = tuple(job for job in CI_TEST_JOB_NAMES if job in job_names)
    missing_test_jobs = tuple(job for job in CI_TEST_JOB_NAMES if job not in job_names)
    errors.extend(f"missing test job:{job}" for job in missing_test_jobs)

    gated_jobs = tuple(
        job for job in job_names
        if any(marker in job for marker in CI_GATED_JOB_MARKERS)
    )
    if not gated_jobs:
        errors.append("missing gated build or deploy job")
    for job in gated_jobs:
        block = _workflow_job_block(workflow_text, job)
        missing_needs = tuple(test_job for test_job in CI_TEST_JOB_NAMES if test_job not in block)
        errors.extend(f"{job} missing needs:{test_job}" for test_job in missing_needs)

    return CIWorkflowCheck(
        ok=not errors,
        workflow_path=workflow_path,
        test_jobs=test_jobs,
        gated_jobs=gated_jobs,
        errors=tuple(errors),
    )


def ci_tests_run_before_build_or_deploy(root: Path = PROJECT_ROOT) -> bool:
    """Return whether CI executes tests before build or deploy jobs.

    REQ: REQ-DEP-005
    """

    return ci_workflow_check(root).ok


def ci_blocks_build_and_deploy_on_test_failure(root: Path = PROJECT_ROOT) -> bool:
    """Return whether build or deploy jobs depend on test jobs.

    REQ: REQ-DEP-005
    """

    check = ci_workflow_check(root)
    return check.ok and bool(check.gated_jobs)


def deployment_target_region_check(
    region: str,
    *,
    explicit_override: bool = False,
) -> DeploymentRegionCheck:
    """Validate AWS deployment region policy.

    REQ: REQ-DEP-002
    """

    if region == "us-east-1":
        return DeploymentRegionCheck(ok=True, region=region)
    if explicit_override:
        return DeploymentRegionCheck(
            ok=True,
            region=region,
            override_required=True,
        )
    return DeploymentRegionCheck(
        ok=False,
        region=region,
        refusal_reason="deployment region must be us-east-1",
    )


def aws_infrastructure_check(root: Path = PROJECT_ROOT) -> AwsInfrastructureCheck:
    """Validate AWS template coverage for the required managed services.

    REQ: REQ-DEP-002
    """

    template_path = root / AWS_INFRA_TEMPLATE_RELATIVE_PATH
    if not template_path.is_file():
        return AwsInfrastructureCheck(
            ok=False,
            region=None,
            resources=(),
            errors=(f"missing:{AWS_INFRA_TEMPLATE_RELATIVE_PATH}",),
        )

    template_text = template_path.read_text()
    region = _template_metadata_value(template_text, "DeploymentRegion")
    errors: list[str] = []
    region_check = deployment_target_region_check(region or "")
    if not region_check.ok:
        errors.append(region_check.refusal_reason or "invalid region")

    resources: list[str] = []
    for resource, markers in AWS_REQUIRED_RESOURCE_MARKERS.items():
        if all(marker in template_text for marker in markers):
            resources.append(resource)
        else:
            errors.append(f"missing resource:{resource}")
    return AwsInfrastructureCheck(
        ok=not errors,
        region=region,
        resources=tuple(resources),
        errors=tuple(errors),
    )


def github_actions_environment_for_branch(branch: str) -> str | None:
    """Return automatic deployment environment for a Git branch.

    REQ: REQ-DEP-003, REQ-DEP-004
    """

    if branch == "develop":
        return "development"
    if branch == "main":
        return "production"
    return None


def deployment_plan_for_branch(
    branch: str,
    *,
    tests_passed: bool,
    ecr_publish_ok: bool,
) -> DeploymentPlan:
    """Build a deployment plan gated by tests and ECR publish status.

    REQ: REQ-DEP-003, REQ-DEP-004, REQ-DEP-006
    """

    environment = github_actions_environment_for_branch(branch)
    if environment is None:
        return DeploymentPlan(
            branch=branch,
            environment=None,
            deploy_selected=False,
            blocked_reason="branch is not deployable",
        )
    if not tests_passed:
        return DeploymentPlan(
            branch=branch,
            environment=environment,
            deploy_selected=True,
            build_images=("backend", "frontend"),
            blocked_reason="tests failed",
        )
    if not ecr_publish_ok:
        return DeploymentPlan(
            branch=branch,
            environment=environment,
            deploy_selected=True,
            build_images=("backend", "frontend"),
            ecr_publish=False,
            ecs_deploy=False,
            blocked_reason="ecr publish failed",
        )
    return DeploymentPlan(
        branch=branch,
        environment=environment,
        deploy_selected=True,
        build_images=("backend", "frontend"),
        ecr_publish=True,
        ecs_deploy=True,
    )


def deployment_resource_separation_check(
    root: Path = PROJECT_ROOT,
) -> DeploymentResourceSeparationCheck:
    """Validate dev and prod resources use separate names and secret prefixes.

    REQ: REQ-DEP-010
    """

    errors: list[str] = []
    environments: list[str] = []
    secret_prefixes: list[str] = []
    resource_names: list[str] = []
    for environment, relative_path in AWS_PARAMETER_FILES.items():
        path = root / relative_path
        if not path.is_file():
            errors.append(f"missing:{relative_path}")
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            errors.append(f"invalid json:{relative_path}")
            continue
        if payload.get("environment") != environment:
            errors.append(f"{relative_path} environment mismatch")
        secret_prefix = payload.get("secret_prefix")
        if secret_prefix != f"/codex-poly-bot/{environment}/":
            errors.append(f"{relative_path} secret prefix mismatch")
        environments.append(environment)
        secret_prefixes.append(str(secret_prefix))
        resource_names.extend(str(name) for name in payload.get("resource_names", []))

    if len(resource_names) != len(set(resource_names)):
        errors.append("resource names must be environment-specific")
    if len(secret_prefixes) != len(set(secret_prefixes)):
        errors.append("secret prefixes must be environment-specific")
    return DeploymentResourceSeparationCheck(
        ok=not errors,
        environments=tuple(environments),
        secret_prefixes=tuple(secret_prefixes),
        errors=tuple(errors),
    )


def _workflow_job_names(workflow_text: str) -> tuple[str, ...]:
    jobs: list[str] = []
    in_jobs = False
    for line in workflow_text.splitlines():
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            jobs.append(line.strip().removesuffix(":"))
    return tuple(jobs)


def _workflow_job_block(workflow_text: str, job_name: str) -> str:
    lines = workflow_text.splitlines()
    start_index = None
    marker = f"  {job_name}:"
    for index, line in enumerate(lines):
        if line == marker:
            start_index = index
            break
    if start_index is None:
        return ""

    block: list[str] = []
    for line in lines[start_index:]:
        if block and line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            break
        block.append(line)
    return "\n".join(block)


def _template_metadata_value(template_text: str, key: str) -> str | None:
    marker = f"{key}:"
    for line in template_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(marker):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return None
