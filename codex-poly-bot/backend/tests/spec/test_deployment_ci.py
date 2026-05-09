"""Red-phase tests for Deployment, CI/CD, and Codex Web Setup."""

from __future__ import annotations

from tests.spec.helpers import pending
from app.bootstrap import (
    PROJECT_ROOT,
    REQUIRED_DIRECTORIES,
    REQUIRED_ENV_EXAMPLES,
    ci_blocks_build_and_deploy_on_test_failure,
    ci_tests_run_before_build_or_deploy,
    ci_workflow_check,
    codex_web_ready,
    compose_services,
    env_files_are_gitignored,
    env_examples_have_no_secrets,
    local_app_stack_services_ready,
    load_runtime_defaults,
    local_startup_check,
    required_paths_exist,
    safe_defaults,
    scan_env_examples_for_secret_values,
)


def test_req_dep_001_01_local_docker_gitignored_env_files_local_startup_commands() -> None:
    """TST-REQ-DEP-001-01: Validates REQ-DEP-001

    Given: local Docker and gitignored `.env` files
    When: local startup commands run
    Then: the app stack starts without production secrets
    """
    assert required_paths_exist(PROJECT_ROOT)
    assert (PROJECT_ROOT / "docker-compose.yml").is_file()
    assert env_files_are_gitignored(PROJECT_ROOT)
    assert local_app_stack_services_ready(PROJECT_ROOT)
    assert {"postgres", "backend", "frontend"}.issubset(set(compose_services(PROJECT_ROOT)))

    check = local_startup_check(PROJECT_ROOT, env={})
    assert check.ok
    assert not check.uses_production_secrets

def test_req_dep_001_02_required_local_env_values_missing_local_startup_runs() -> None:
    """TST-REQ-DEP-001-02: Validates REQ-DEP-001

    Given: required local env values are missing
    When: local startup runs
    Then: startup fails with safe dry-run defaults or clear setup errors
    """
    check = local_startup_check(PROJECT_ROOT / "missing", env={})

    assert not check.ok
    assert check.errors
    assert safe_defaults().global_execution_mode == "dry_run"

def test_req_dep_002_01_cloudformation_parameters_us_east_1_infrastructure_templates_validated() -> None:
    """TST-REQ-DEP-002-01: Validates REQ-DEP-002

    Given: CloudFormation parameters for us-east-1
    When: infrastructure templates are validated
    Then: ECS Fargate, RDS, S3, Secrets Manager, CloudWatch, and SES resources are defined
    """
    pending("TST-REQ-DEP-002-01", "REQ-DEP-002")

def test_req_dep_002_02_non_us_east_1_deployment_target_deployment_validation() -> None:
    """TST-REQ-DEP-002-02: Validates REQ-DEP-002

    Given: a non-us-east-1 deployment target
    When: deployment validation runs
    Then: deployment is blocked or requires explicit override
    """
    pending("TST-REQ-DEP-002-02", "REQ-DEP-002")

def test_req_dep_003_01_code_merged_develop_github_actions_runs_development_deployment() -> None:
    """TST-REQ-DEP-003-01: Validates REQ-DEP-003

    Given: code is merged to `develop`
    When: GitHub Actions runs
    Then: the development deployment workflow is selected
    """
    pending("TST-REQ-DEP-003-01", "REQ-DEP-003")

def test_req_dep_003_02_branch_other_than_develop_main_github_actions_runs() -> None:
    """TST-REQ-DEP-003-02: Validates REQ-DEP-003

    Given: a branch other than `develop` or `main`
    When: GitHub Actions runs
    Then: automatic environment deployment is not triggered
    """
    pending("TST-REQ-DEP-003-02", "REQ-DEP-003")

def test_req_dep_004_01_code_merged_main_github_actions_runs_production_deployment() -> None:
    """TST-REQ-DEP-004-01: Validates REQ-DEP-004

    Given: code is merged to `main`
    When: GitHub Actions runs
    Then: production deployment starts automatically
    """
    pending("TST-REQ-DEP-004-01", "REQ-DEP-004")

def test_req_dep_004_02_production_deployment_tests_fail_github_actions_runs_production() -> None:
    """TST-REQ-DEP-004-02: Validates REQ-DEP-004

    Given: production deployment tests fail
    When: GitHub Actions runs
    Then: production deploy steps do not execute
    """
    pending("TST-REQ-DEP-004-02", "REQ-DEP-004")

def test_req_dep_005_01_ci_triggered_workflow_execution_starts_tests_run_before() -> None:
    """TST-REQ-DEP-005-01: Validates REQ-DEP-005

    Given: CI is triggered
    When: workflow execution starts
    Then: tests run before build or deploy jobs
    """
    check = ci_workflow_check(PROJECT_ROOT)

    assert check.ok
    assert set(check.test_jobs) == {"backend-tests", "frontend-check"}
    assert "container-build" in check.gated_jobs
    assert ci_tests_run_before_build_or_deploy(PROJECT_ROOT)

def test_req_dep_005_02_tests_fail_in_ci_workflow_execution_continues_container() -> None:
    """TST-REQ-DEP-005-02: Validates REQ-DEP-005

    Given: tests fail in CI
    When: workflow execution continues
    Then: container build and deploy jobs are blocked
    """
    check = ci_workflow_check(PROJECT_ROOT)

    assert check.ok
    assert not check.errors
    assert ci_blocks_build_and_deploy_on_test_failure(PROJECT_ROOT)

def test_req_dep_006_01_tests_pass_deployment_workflow_runs_backend_frontend_images() -> None:
    """TST-REQ-DEP-006-01: Validates REQ-DEP-006

    Given: tests pass
    When: deployment workflow runs
    Then: backend and frontend images are built and published to ECR before ECS deployment
    """
    pending("TST-REQ-DEP-006-01", "REQ-DEP-006")

def test_req_dep_006_02_ecr_publish_fails_deployment_workflow_runs_ecs_deployment() -> None:
    """TST-REQ-DEP-006-02: Validates REQ-DEP-006

    Given: ECR publish fails
    When: deployment workflow runs
    Then: ECS deployment is skipped and failure status is reported
    """
    pending("TST-REQ-DEP-006-02", "REQ-DEP-006")

def test_req_dep_007_01_repo_setup_files_inspected_env_example_files_validated() -> None:
    """TST-REQ-DEP-007-01: Validates REQ-DEP-007

    Given: repo setup files are inspected
    When: `.env.example` files are validated
    Then: required local config keys are documented without secrets
    """
    for relative_path in REQUIRED_ENV_EXAMPLES:
        assert (PROJECT_ROOT / relative_path).is_file()

    assert env_examples_have_no_secrets(PROJECT_ROOT)

def test_req_dep_007_02_env_example_contains_real_looking_secret_value_secret(tmp_path) -> None:
    """TST-REQ-DEP-007-02: Validates REQ-DEP-007

    Given: `.env.example` contains a real-looking secret value
    When: secret scanning runs
    Then: validation fails
    """
    for relative_path in REQUIRED_ENV_EXAMPLES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("OPENAI_API_KEY=\n")
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=sk-real-looking-value\n")

    findings = scan_env_examples_for_secret_values(tmp_path)

    assert ".env.example:OPENAI_API_KEY" in findings

def test_req_dep_008_01_codex_web_setup_docs_scripts_developer_follows_setup() -> None:
    """TST-REQ-DEP-008-01: Validates REQ-DEP-008

    Given: Codex web setup docs and scripts
    When: a developer follows setup
    Then: dependencies, tests, and safe dry-run config are available
    """
    assert (PROJECT_ROOT / "AGENTS.md").is_file()
    assert (PROJECT_ROOT / "docs" / "local-setup.md").is_file()
    setup_script = PROJECT_ROOT / "scripts" / "setup-local.sh"
    assert setup_script.is_file()
    script_text = setup_script.read_text()
    assert "pip install -e" in script_text
    assert "pytest" in script_text
    assert codex_web_ready(PROJECT_ROOT)

def test_req_dep_008_02_setup_runs_without_trading_secrets_dependency_install_tests() -> None:
    """TST-REQ-DEP-008-02: Validates REQ-DEP-008

    Given: setup runs without trading secrets
    When: dependency install and tests run
    Then: setup still succeeds with dry-run-safe defaults
    """
    check = local_startup_check(PROJECT_ROOT, env={})

    assert check.ok
    assert not check.uses_production_secrets
    assert safe_defaults().live_enabled is False

def test_req_dep_009_01_codex_web_environment_without_production_trading_secrets_dependencies() -> None:
    """TST-REQ-DEP-009-01: Validates REQ-DEP-009

    Given: a Codex web environment without production trading secrets
    When: dependencies install, tests run, or code is inspected
    Then: those actions succeed
    """
    defaults = load_runtime_defaults()
    check = local_startup_check(PROJECT_ROOT, env={})

    assert defaults.global_execution_mode == "dry_run"
    assert check.ok
    assert not check.uses_production_secrets

def test_req_dep_009_02_code_tries_require_production_secrets_during_import_tests() -> None:
    """TST-REQ-DEP-009-02: Validates REQ-DEP-009

    Given: code tries to require production secrets during import or tests
    When: CI or Codex setup runs
    Then: the test fails
    """
    defaults = load_runtime_defaults(live_enabled=None)

    assert defaults.global_execution_mode == "dry_run"
    assert all((PROJECT_ROOT / directory).exists() for directory in REQUIRED_DIRECTORIES)

def test_req_dep_010_01_development_production_deployments_infrastructure_secret_names_validated_resources() -> None:
    """TST-REQ-DEP-010-01: Validates REQ-DEP-010

    Given: development and production deployments
    When: infrastructure and secret names are validated
    Then: resources, secrets, wallets, and config are separated by environment
    """
    pending("TST-REQ-DEP-010-01", "REQ-DEP-010")
