"""Red-phase tests for Deployment, CI/CD, and Codex Web Setup."""

from __future__ import annotations

from app.bootstrap import (
    PROJECT_ROOT,
    REQUIRED_DIRECTORIES,
    REQUIRED_ENV_EXAMPLES,
    aws_infrastructure_check,
    ci_blocks_build_and_deploy_on_test_failure,
    ci_tests_run_before_build_or_deploy,
    ci_workflow_check,
    codex_web_ready,
    compose_services,
    deployment_plan_for_branch,
    deployment_resource_separation_check,
    deployment_target_region_check,
    env_files_are_gitignored,
    env_examples_have_no_secrets,
    github_actions_environment_for_branch,
    iam_secret_scope_check,
    local_app_stack_services_ready,
    load_runtime_defaults,
    local_startup_check,
    migration_safety_gate,
    required_paths_exist,
    safe_defaults,
    scan_env_examples_for_secret_values,
    s3_lifecycle_policy_check,
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
    Then: ECS Fargate, RDS, S3, Secrets Manager, CloudWatch, SES, IAM, and ECR resources are defined
    """
    check = aws_infrastructure_check(PROJECT_ROOT)

    assert check.ok
    assert check.region == "us-east-1"
    assert check.resources == (
        "ecr",
        "ecs_fargate",
        "iam",
        "rds_postgres",
        "s3",
        "secrets_manager",
        "cloudwatch",
        "ses",
    )

def test_req_dep_002_02_non_us_east_1_deployment_target_deployment_validation() -> None:
    """TST-REQ-DEP-002-02: Validates REQ-DEP-002

    Given: a non-us-east-1 deployment target
    When: deployment validation runs
    Then: deployment is blocked or requires explicit override
    """
    blocked = deployment_target_region_check("us-west-2")
    override = deployment_target_region_check("us-west-2", explicit_override=True)

    assert not blocked.ok
    assert blocked.refusal_reason == "deployment region must be us-east-1"
    assert override.ok
    assert override.override_required

def test_req_dat_006_02_cloudformation_s3_raw_lifecycle_retains_365_days() -> None:
    """TST-REQ-DAT-006-02: Validates REQ-DAT-006

    Given: S3 buckets are created by infrastructure
    When: lifecycle rules are validated
    Then: raw snapshots are retained for 365 days
    """
    check = s3_lifecycle_policy_check(PROJECT_ROOT)

    assert check.ok
    assert check.raw_retention_days == 365

def test_req_dat_007_02_cloudformation_s3_normalized_lifecycle_retains_730_days() -> None:
    """TST-REQ-DAT-007-02: Validates REQ-DAT-007

    Given: S3 buckets are created by infrastructure
    When: lifecycle rules are validated
    Then: normalized snapshots are retained for 730 days
    """
    check = s3_lifecycle_policy_check(PROJECT_ROOT)

    assert check.ok
    assert check.normalized_retention_days == 730

def test_req_wal_003_03_ecs_task_role_scopes_secret_access_to_environment_prefix() -> None:
    """TST-REQ-WAL-003-03: Validates REQ-WAL-003

    Given: an ECS task attempts to read deployment secrets
    When: IAM secret scope is validated
    Then: only the current environment secret prefix is allowed
    """
    check = iam_secret_scope_check(PROJECT_ROOT)

    assert check.ok
    assert check.denies_cross_environment
    assert check.secret_resource_pattern is not None

def test_req_dep_003_01_code_merged_develop_github_actions_runs_development_deployment() -> None:
    """TST-REQ-DEP-003-01: Validates REQ-DEP-003

    Given: code is merged to `develop`
    When: GitHub Actions runs
    Then: the development deployment workflow is selected
    """
    assert github_actions_environment_for_branch("develop") == "development"
    plan = deployment_plan_for_branch("develop", tests_passed=True, ecr_publish_ok=True)

    assert plan.environment == "development"
    assert plan.deploy_selected
    assert plan.ecs_deploy

def test_req_dep_003_02_branch_other_than_develop_main_github_actions_runs() -> None:
    """TST-REQ-DEP-003-02: Validates REQ-DEP-003

    Given: a branch other than `develop` or `main`
    When: GitHub Actions runs
    Then: automatic environment deployment is not triggered
    """
    plan = deployment_plan_for_branch("feature/new-signal", tests_passed=True, ecr_publish_ok=True)

    assert github_actions_environment_for_branch("feature/new-signal") is None
    assert not plan.deploy_selected
    assert plan.blocked_reason == "branch is not deployable"

def test_req_dep_003_03_workflow_develop_branch_deploys_development_after_build() -> None:
    """TST-REQ-DEP-003-03: Validates REQ-DEP-003

    Given: code is merged to `develop`
    When: the workflow is inspected
    Then: development deployment is selected after tests, migration safety, and ECR publish
    """
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "deploy-development:" in workflow_text
    assert "github.ref == 'refs/heads/develop'" in workflow_text
    assert "container-build" in workflow_text
    assert "migration-safety" in workflow_text

def test_req_dep_004_01_code_merged_main_github_actions_runs_production_deployment() -> None:
    """TST-REQ-DEP-004-01: Validates REQ-DEP-004

    Given: code is merged to `main`
    When: GitHub Actions runs
    Then: production deployment starts automatically
    """
    plan = deployment_plan_for_branch("main", tests_passed=True, ecr_publish_ok=True)

    assert plan.environment == "production"
    assert plan.deploy_selected
    assert plan.ecs_deploy

def test_req_dep_004_02_production_deployment_tests_fail_github_actions_runs_production() -> None:
    """TST-REQ-DEP-004-02: Validates REQ-DEP-004

    Given: production deployment tests fail
    When: GitHub Actions runs
    Then: production deploy steps do not execute
    """
    plan = deployment_plan_for_branch("main", tests_passed=False, ecr_publish_ok=True)

    assert plan.environment == "production"
    assert not plan.ecr_publish
    assert not plan.ecs_deploy
    assert plan.blocked_reason == "tests failed"

def test_req_dep_004_03_workflow_main_branch_deploys_production_after_build() -> None:
    """TST-REQ-DEP-004-03: Validates REQ-DEP-004

    Given: code is merged to `main`
    When: the workflow is inspected
    Then: production deployment is selected after tests, migration safety, and ECR publish
    """
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "deploy-production:" in workflow_text
    assert "github.ref == 'refs/heads/main'" in workflow_text
    assert "container-build" in workflow_text
    assert "migration-safety" in workflow_text

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

def test_req_dep_005_05_destructive_migration_rejected_requires_expand_contract_split() -> None:
    """TST-REQ-DEP-005-05: Validates REQ-DEP-005

    Given: a migration is destructive or contract-phase
    When: CI evaluates migration safety
    Then: automatic deploy is rejected and an expand/contract split is required
    """
    destructive = migration_safety_gate("ALTER TABLE positions DROP COLUMN legacy_state;")
    safe = migration_safety_gate("ALTER TABLE positions ADD COLUMN new_state text;")
    plan = deployment_plan_for_branch(
        "main",
        tests_passed=True,
        ecr_publish_ok=True,
        migration_safe=destructive.ok,
    )

    assert not destructive.ok
    assert destructive.requires_expand_contract
    assert destructive.destructive_markers == ("drop column",)
    assert safe.ok
    assert not plan.ecs_deploy
    assert plan.blocked_reason == "migration requires expand/contract split"

def test_req_dep_006_01_tests_pass_deployment_workflow_runs_backend_frontend_images() -> None:
    """TST-REQ-DEP-006-01: Validates REQ-DEP-006

    Given: tests pass
    When: deployment workflow runs
    Then: backend and frontend images are built and published to ECR before ECS deployment
    """
    plan = deployment_plan_for_branch("main", tests_passed=True, ecr_publish_ok=True)

    assert plan.build_images == ("backend", "frontend")
    assert plan.ecr_publish
    assert plan.ecs_deploy

def test_req_dep_006_03_workflow_publishes_ecr_images_before_ecs_deploy() -> None:
    """TST-REQ-DEP-006-03: Validates REQ-DEP-006

    Given: tests and migration safety pass
    When: the workflow is inspected
    Then: backend and frontend images are pushed to ECR before ECS deployment
    """
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    build_index = workflow_text.index("container-build:")
    deploy_index = workflow_text.index("deploy-production:")

    assert build_index < deploy_index
    assert "docker build -t codex-poly-bot-backend" in workflow_text
    assert "docker push $ECR_REGISTRY/codex-poly-bot-$DEPLOY_ENV-backend" in workflow_text
    assert "aws ecs update-service" in workflow_text

def test_req_dep_006_02_ecr_publish_fails_deployment_workflow_runs_ecs_deployment() -> None:
    """TST-REQ-DEP-006-02: Validates REQ-DEP-006

    Given: ECR publish fails
    When: deployment workflow runs
    Then: ECS deployment is skipped and failure status is reported
    """
    plan = deployment_plan_for_branch("develop", tests_passed=True, ecr_publish_ok=False)

    assert plan.ecr_publish is False
    assert plan.ecs_deploy is False
    assert plan.blocked_reason == "ecr publish failed"

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
    check = deployment_resource_separation_check(PROJECT_ROOT)

    assert check.ok
    assert check.environments == ("development", "production")
    assert check.secret_prefixes == (
        "/codex-poly-bot/development/",
        "/codex-poly-bot/production/",
    )
