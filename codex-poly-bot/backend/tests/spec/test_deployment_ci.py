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


def test_req_dep_011_01_rds_uses_gp3_storage() -> None:
    """TST-REQ-DEP-011-01: Validates REQ-DEP-011."""

    template = (PROJECT_ROOT / "infra" / "cloudformation.yml").read_text()

    assert "StorageType: gp3" in template
    assert "StorageType: gp2" not in template


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
    root_workflow = PROJECT_ROOT.parent / ".github" / "workflows" / "codex-poly-bot-ci.yml"

    assert root_workflow.is_file()
    assert "deploy-development:" in workflow_text
    assert "github.ref == 'refs/heads/develop'" in workflow_text
    assert "container-build" in workflow_text
    assert "migration-safety" in workflow_text
    assert "SIGNOZ_ENABLED: ${{ vars.SIGNOZ_ENABLED }}" in workflow_text
    assert "SIGNOZ_FRONTEND_ENABLED: ${{ vars.SIGNOZ_FRONTEND_ENABLED }}" in workflow_text
    assert "SIGNOZ_REGION: ${{ vars.SIGNOZ_REGION }}" in workflow_text
    assert "SIGNOZ_OTLP_ENDPOINT: ${{ vars.SIGNOZ_OTLP_ENDPOINT }}" in workflow_text
    assert (
        "SIGNOZ_INGESTION_KEY_SECRET_ARN: ${{ vars.SIGNOZ_INGESTION_KEY_SECRET_ARN }}"
        in workflow_text
    )
    assert (
        "SIGNOZ_CLOUDWATCH_READ_POLICY_ENABLED: ${{ vars.SIGNOZ_CLOUDWATCH_READ_POLICY_ENABLED }}"
        in workflow_text
    )

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
    assert 'docker push "$ECR_REGISTRY/codex-poly-bot-$DEPLOY_ENV-backend' in workflow_text
    assert "codex-poly-bot-$DEPLOY_ENV-backend:latest" in workflow_text
    assert "codex-poly-bot-$DEPLOY_ENV-frontend:latest" in workflow_text
    assert "aws ecs update-service" in workflow_text
    assert "aws ecs wait services-stable" in workflow_text
    assert "--service codex-poly-bot-production-frontend" in workflow_text

def test_req_dep_002_03_cloudformation_exposes_frontend_and_backend_services() -> None:
    """TST-REQ-DEP-002-03: Validates REQ-DEP-002

    Given: CloudFormation infrastructure
    When: public application resources are inspected
    Then: ALB, frontend service, backend service, and runtime env settings are defined
    """
    text = (PROJECT_ROOT / "infra" / "cloudformation.yml").read_text()

    assert "AWS::ElasticLoadBalancingV2::LoadBalancer" in text
    assert "FrontendTaskDefinition" in text
    assert "FrontendService" in text
    assert "BackendTargetGroup" in text
    assert "FrontendTargetGroup" in text
    assert "DASHBOARD_ALLOWED_USERS" in text
    assert "BACKEND_TOKEN_SIGNING_SECRET" in text
    assert "postgresql+psycopg://${DatabaseUsername}" in text
    assert "SIGNOZ_ENABLED" in text
    assert "SIGNOZ_FRONTEND_ENABLED" in text
    assert "SignozCloudWatchReadPolicyEnabled" in text
    assert "SignozCloudWatchReadPolicy" in text
    assert "ApplicationUrl" in text

def test_req_dep_002_06_backend_task_has_worker_memory_headroom() -> None:
    """TST-REQ-DEP-002-06: Validates REQ-DEP-002

    Given: production backend traffic can load dashboard and runtime datasets
    When: CloudFormation task sizing is inspected
    Then: the backend Fargate task has 2 vCPU and 16 GiB of memory for scheduler work
    """
    text = (PROJECT_ROOT / "infra" / "cloudformation.yml").read_text()
    backend_block = text[
        text.index("  BackendTaskDefinition:") : text.index("  FrontendTaskDefinition:")
    ]

    assert 'Cpu: "2048"' in backend_block
    assert 'Memory: "16384"' in backend_block

def test_req_dep_002_05_cloudformation_supports_https_domain_and_secret_injection() -> None:
    """TST-REQ-DEP-002-05: Validates REQ-DEP-002 and REQ-WAL-003

    Given: production-safe remote deployment
    When: CloudFormation infrastructure is inspected
    Then: HTTPS, custom-domain URLs, and LLM secrets are configured by environment
    """
    text = (PROJECT_ROOT / "infra" / "cloudformation.yml").read_text()

    assert "ApplicationDomainName" in text
    assert "CertificateArn" in text
    assert "Protocol: HTTPS" in text
    assert "StatusCode: HTTP_301" in text
    assert "OPENAI_API_KEY" in text
    assert "/codex-poly-bot/${EnvironmentName}/openai/api-key" in text
    assert "ANTHROPIC_API_KEY" in text
    assert "/codex-poly-bot/${EnvironmentName}/anthropic/api-key" in text
    assert "POLYMARKET_KEY_ID" in text
    assert "PolymarketKeyIdSecretArn" in text
    assert "POLYMARKET_SECRET_KEY" in text
    assert "PolymarketSecretKeySecretArn" in text
    assert "POLYMARKET_PRIVATE_KEY" in text
    assert "PolymarketPrivateKeySecretArn" in text
    assert "POLYMARKET_OPENAI_KEY_ID" in text
    assert "PolymarketOpenAiKeyIdSecretArn" in text
    assert "POLYMARKET_CLAUDE_SECRET_KEY" in text
    assert "PolymarketClaudeSecretKeySecretArn" in text
    assert "ALPACA_KEY_ID" in text
    assert "AlpacaKeyIdSecretArn" in text
    assert "ALPACA_SECRET_KEY" in text
    assert "AlpacaSecretKeySecretArn" in text
    assert "ALPACA_OPENAI_KEY_ID" in text
    assert "AlpacaOpenAiKeyIdSecretArn" in text
    assert "ALPACA_CLAUDE_SECRET_KEY" in text
    assert "AlpacaClaudeSecretKeySecretArn" in text
    assert "ALPACA_ACCOUNT_STATUS" in text
    assert "ALPACA_SYMBOL_PRESETS" in text
    assert "ALPACA_CUSTOM_SYMBOLS" in text
    assert "ALPACA_SYMBOL_UNIVERSE" in text
    assert "ALPACA_SYMBOL_CHUNK_SIZE" in text
    assert "ALPACA_HISTORICAL_BAR_LIMIT" in text
    assert "POLYGON_RPC_URL" in text
    assert "POLYGON_ORDER_FILLED_MAX_BLOCK_RANGE" in text
    assert "POLYGON_ORDER_FILLED_MAX_WINDOWS" in text
    assert "POLYGON_ORDER_FILLED_IMPORT_CADENCE_MINUTES" in text
    assert "POLYGON_ORDER_FILLED_RETRY_SPLIT" in text
    assert "NOTIFICATION_RECIPIENTS" in text
    assert "ENABLE_BACKGROUND_WORKER" in text
    assert "TaskExecutionSecretAccessPolicy" in text

def test_req_dep_002_06_deploy_script_discovers_runtime_secret_arns() -> None:
    """TST-REQ-DEP-002-06: Validates REQ-DEP-002 and REQ-WAL-003

    Given: per-environment runtime credentials in AWS Secrets Manager
    When: the deployment script is inspected
    Then: stack parameters receive only discovered environment-scoped secret ARNs
    """

    text = (PROJECT_ROOT / "scripts" / "deploy-stack.sh").read_text()

    assert "secret_arn_or_empty" in text
    assert "/codex-poly-bot/${environment}/polymarket/key-id" in text
    assert "/codex-poly-bot/${environment}/polymarket/secret-key" in text
    assert "/codex-poly-bot/${environment}/polymarket/private-key" in text
    assert "/codex-poly-bot/${environment}/alpaca/key-id" in text
    assert "/codex-poly-bot/${environment}/alpaca/secret-key" in text
    assert "AlpacaAccountStatus=${alpaca_account_status}" in text
    assert "AlpacaSymbolPresets=${alpaca_symbol_presets}" in text
    assert "AlpacaCustomSymbols=${alpaca_custom_symbols}" in text
    assert "AlpacaSymbolUniverse=${alpaca_symbol_universe}" in text
    assert "AlpacaSymbolChunkSize=${alpaca_symbol_chunk_size}" in text
    assert "AlpacaHistoricalBarLimit=${alpaca_historical_bar_limit}" in text
    assert "PolygonRpcUrl=${polygon_rpc_url}" in text
    assert "PolygonOrderFilledMaxBlockRange=${polygon_order_filled_max_block_range}" in text
    assert "PolygonOrderFilledMaxWindows=${polygon_order_filled_max_windows}" in text
    assert (
        "PolygonOrderFilledImportCadenceMinutes=${polygon_order_filled_import_cadence_minutes}"
        in text
    )
    assert "PolygonOrderFilledRetrySplit=${polygon_order_filled_retry_split}" in text
    assert "alpaca_account_status=\"${ALPACA_ACCOUNT_STATUS:-paper_ready}\"" in text
    assert "alpaca_account_status=\"${ALPACA_ACCOUNT_STATUS:-reviewing}\"" in text
    assert "alpaca_symbol_presets=\"${ALPACA_SYMBOL_PRESETS:-sp500,nasdaq100}\"" in text
    assert "alpaca_symbol_universe=\"${ALPACA_SYMBOL_UNIVERSE:-}\"" in text
    assert "NOTIFICATION_RECIPIENT_EMAIL:-yaw.etse@gmail.com" in text
    assert "NotificationRecipients=${notification_recipients}" in text
    assert 'enable_background_worker_default="true"' in text
    assert 'enable_background_worker_default="false"' in text
    assert 'enable_background_worker="${ENABLE_BACKGROUND_WORKER:-${enable_background_worker_default}}"' in text
    assert "EnableBackgroundWorker=${enable_background_worker}" in text
    assert "SignozEnabled=${signoz_enabled}" in text
    assert "SignozFrontendEnabled=${signoz_frontend_enabled}" in text
    assert "SignozRegion=${signoz_region}" in text
    assert "SignozCloudWatchReadPolicyEnabled=${signoz_cloudwatch_read_policy_enabled}" in text
    assert "/codex-poly-bot/${environment}/signoz/ingestion-key" in text
    assert "SignozIngestionKeySecretArn=${signoz_ingestion_key_secret_arn}" in text

def test_req_dep_002_04_cloudformation_keeps_frontend_owned_api_routes_on_frontend() -> None:
    """TST-REQ-DEP-002-04: Validates REQ-DEP-002

    Given: CloudFormation ALB listener rules
    When: frontend-owned and backend API routes are inspected
    Then: frontend-owned /api/* paths are routed to the frontend before backend /api/* routing
    """
    text = (PROJECT_ROOT / "infra" / "cloudformation.yml").read_text()
    auth_rule_index = text.index("FrontendAuthListenerRule")
    observability_rule_index = text.index("FrontendObservabilityListenerRule")
    backend_rule_index = text.index("BackendListenerRule")

    assert auth_rule_index < backend_rule_index
    assert observability_rule_index < backend_rule_index
    assert "- /api/auth/*" in text
    assert "- /api/observability/*" in text
    assert "Priority: 5" in text[auth_rule_index:backend_rule_index]
    assert "Priority: 6" in text[observability_rule_index:backend_rule_index]
    assert "- /api/*" in text[backend_rule_index:]
    assert "Priority: 10" in text[backend_rule_index:]

def test_req_dep_006_04_workflow_deploys_infrastructure_before_ecr_publish() -> None:
    """TST-REQ-DEP-006-04: Validates REQ-DEP-006

    Given: GitHub Actions deploys a branch environment
    When: the workflow is inspected
    Then: CloudFormation runs before ECR publish and ECS waits for stability
    """
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    root_workflow_text = (
        PROJECT_ROOT.parent / ".github" / "workflows" / "codex-poly-bot-ci.yml"
    ).read_text()

    for text in (workflow_text, root_workflow_text):
        infra_index = text.index("infrastructure-deploy:")
        build_index = text.index("container-build:")
        deploy_index = text.index("deploy-production:")
        assert infra_index < build_index < deploy_index
        assert "Deploy CloudFormation stack" in text
        assert "./codex-poly-bot/scripts/deploy-stack.sh" in text
        assert "ALPACA_ACCOUNT_STATUS: ${{ vars.ALPACA_ACCOUNT_STATUS }}" in text
        assert "ALPACA_SYMBOL_PRESETS: ${{ vars.ALPACA_SYMBOL_PRESETS }}" in text
        assert "ALPACA_CUSTOM_SYMBOLS: ${{ vars.ALPACA_CUSTOM_SYMBOLS }}" in text
        assert "ALPACA_SYMBOL_UNIVERSE: ${{ vars.ALPACA_SYMBOL_UNIVERSE }}" in text
        assert "ALPACA_SYMBOL_CHUNK_SIZE: ${{ vars.ALPACA_SYMBOL_CHUNK_SIZE }}" in text
        assert "ALPACA_HISTORICAL_BAR_LIMIT: ${{ vars.ALPACA_HISTORICAL_BAR_LIMIT }}" in text
        assert "ENABLE_BACKGROUND_WORKER: ${{ vars.ENABLE_BACKGROUND_WORKER }}" in text
        assert (
            "WORKER_HEARTBEAT_INTERVAL_SECONDS: ${{ vars.WORKER_HEARTBEAT_INTERVAL_SECONDS }}"
            in text
        )
        assert "environment: production" in text
        assert "environment: development" in text
        assert "aws ecs wait services-stable" in text

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

def test_req_dep_008_03_alpaca_paper_smoke_script_refuses_live_trading() -> None:
    """TST-REQ-DEP-008-03: Validates REQ-DEP-008 and REQ-ALP-006

    Given: the Alpaca paper smoke command
    When: the script is inspected
    Then: it requires development paper mode and refuses live endpoints
    """
    script = PROJECT_ROOT / "scripts" / "alpaca-paper-smoke.py"
    text = script.read_text()

    assert script.is_file()
    assert "APP_ENV=development" in text
    assert "ENVIRONMENT=development" in text
    assert "TRADING_ACCOUNT_MODE=paper" in text
    assert "paper-api.alpaca.markets" in text
    assert "paper smoke refuses LIVE_ENABLED=true" in text
    assert "25.00 or less" in text

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

def test_req_dep_001_03_local_development_docs_cover_docker_and_gitignored_env() -> None:
    """TST-REQ-DEP-001-03: Validates REQ-DEP-001

    Given: local development docs
    When: a developer follows setup guidance
    Then: Docker startup and gitignored `.env` files are documented
    """
    text = (PROJECT_ROOT / "docs" / "local-setup.md").read_text()

    assert "docker compose up" in text
    assert ".env" in text
    assert "gitignored" in text

def test_req_dep_001_04_docker_compose_runs_backend_and_frontend_apps() -> None:
    """TST-REQ-DEP-001-04: Validates REQ-DEP-001

    Given: the local Docker Compose contract
    When: the app stack services are inspected
    Then: backend and frontend services run the real app processes
    """
    text = (PROJECT_ROOT / "docker-compose.yml").read_text()

    assert "context: ./backend" in text
    assert "context: ./frontend" in text
    assert "uvicorn" in text
    assert "app.main:create_app" in text
    assert "8000:8000" in text
    assert "3100:3000" in text
    assert "frontend placeholder" not in text
    assert "backend safe defaults ok" not in text

def test_req_dep_008_03_codex_web_docs_install_and_test_without_production_secrets() -> None:
    """TST-REQ-DEP-008-03: Validates REQ-DEP-008

    Given: Codex web setup docs
    When: a developer installs dependencies and runs tests
    Then: production trading secrets are not required
    """
    text = (PROJECT_ROOT / "docs" / "codex-web.md").read_text()
    lower_text = text.lower()

    assert "./scripts/setup-local.sh" in text
    assert "production trading secrets are not required" in lower_text
    assert "pytest" in text
    assert "npm run typecheck" in text

def test_req_exe_017_03_live_trading_checklist_requires_safety_gates() -> None:
    """TST-REQ-EXE-017-03: Validates REQ-EXE-017

    Given: live trading checklist docs
    When: an operator prepares live trading
    Then: account, dry-run, venue, risk, auth, SES, and kill-switch checks are required
    """
    text = (PROJECT_ROOT / "docs" / "live-trading-checklist.md").read_text().lower()

    for phrase in (
        "wallet",
        "account",
        "dry-run",
        "venue",
        "risk",
        "auth",
        "ses",
        "kill switch",
    ):
        assert phrase in text

def test_req_dep_004_04_operations_runbook_defines_ecs_rollback_and_rds_restore() -> None:
    """TST-REQ-DEP-004-04: Validates REQ-DEP-004

    Given: operations runbook docs
    When: a bad deploy occurs
    Then: ECS rollback and RDS restore-point guidance are documented
    """
    text = (PROJECT_ROOT / "docs" / "operations-runbook.md").read_text().lower()

    assert "ecs rollback" in text
    assert "aws ecs update-service" in text
    assert "rds restore" in text
    assert "restore point" in text

def test_req_wal_003_04_documentation_keeps_deployed_secrets_in_aws() -> None:
    """TST-REQ-WAL-003-04: Validates REQ-WAL-003

    Given: wallet and deployment docs
    When: deployed secret handling is reviewed
    Then: deployed credentials are documented as AWS Secrets Manager values
    """
    wallet_docs = (PROJECT_ROOT / "docs" / "wallets-and-accounts.md").read_text()
    deployment_docs = (PROJECT_ROOT / "docs" / "deployment.md").read_text()

    assert "AWS Secrets Manager" in wallet_docs
    assert "/codex-poly-bot/{environment}/" in wallet_docs
    assert "Trading credentials are not stored in GitHub Actions secrets" in deployment_docs
