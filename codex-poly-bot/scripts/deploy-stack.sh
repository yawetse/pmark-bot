#!/usr/bin/env bash
set -euo pipefail

environment="${1:?usage: scripts/deploy-stack.sh development|production}"

case "${environment}" in
  development)
    enable_background_worker_default="true"
    live_enabled="false"
    trading_account_mode="paper"
    default_selected_venue="alpaca"
    polymarket_us_enabled="false"
    polymarket_international_enabled="false"
    alpaca_enabled="true"
    polymarket_slippage_threshold="${POLYMARKET_MARKET_ORDER_SLIPPAGE:-0.02}"
    alpaca_slippage_threshold="${ALPACA_MARKET_ORDER_SLIPPAGE:-0.005}"
    alpaca_base_url="${ALPACA_BASE_URL:-https://paper-api.alpaca.markets}"
    alpaca_data_feed="${ALPACA_DATA_FEED:-iex}"
    alpaca_account_status="${ALPACA_ACCOUNT_STATUS:-paper_ready}"
    alpaca_symbol_presets="${ALPACA_SYMBOL_PRESETS:-sp500,nasdaq100}"
    alpaca_custom_symbols="${ALPACA_CUSTOM_SYMBOLS:-}"
    alpaca_symbol_universe="${ALPACA_SYMBOL_UNIVERSE:-}"
    alpaca_symbol_chunk_size="${ALPACA_SYMBOL_CHUNK_SIZE:-50}"
    alpaca_historical_bar_limit="${ALPACA_HISTORICAL_BAR_LIMIT:-30}"
    polygon_rpc_url="${POLYGON_RPC_URL:-}"
    polygon_order_filled_max_block_range="${POLYGON_ORDER_FILLED_MAX_BLOCK_RANGE:-500}"
    polygon_order_filled_max_windows="${POLYGON_ORDER_FILLED_MAX_WINDOWS:-1}"
    polygon_order_filled_import_cadence_minutes="${POLYGON_ORDER_FILLED_IMPORT_CADENCE_MINUTES:-60}"
    polygon_order_filled_retry_split="${POLYGON_ORDER_FILLED_RETRY_SPLIT:-true}"
    ;;
  production)
    enable_background_worker_default="false"
    live_enabled="true"
    trading_account_mode="live"
    default_selected_venue="polymarket_us"
    polymarket_us_enabled="true"
    polymarket_international_enabled="false"
    alpaca_enabled="true"
    polymarket_slippage_threshold="${POLYMARKET_MARKET_ORDER_SLIPPAGE:-0.02}"
    alpaca_slippage_threshold="${ALPACA_MARKET_ORDER_SLIPPAGE:-0.005}"
    alpaca_base_url="${ALPACA_BASE_URL:-https://api.alpaca.markets}"
    alpaca_data_feed="${ALPACA_DATA_FEED:-iex}"
    alpaca_account_status="${ALPACA_ACCOUNT_STATUS:-reviewing}"
    alpaca_symbol_presets="${ALPACA_SYMBOL_PRESETS:-sp500,nasdaq100}"
    alpaca_custom_symbols="${ALPACA_CUSTOM_SYMBOLS:-}"
    alpaca_symbol_universe="${ALPACA_SYMBOL_UNIVERSE:-}"
    alpaca_symbol_chunk_size="${ALPACA_SYMBOL_CHUNK_SIZE:-50}"
    alpaca_historical_bar_limit="${ALPACA_HISTORICAL_BAR_LIMIT:-30}"
    polygon_rpc_url="${POLYGON_RPC_URL:-}"
    polygon_order_filled_max_block_range="${POLYGON_ORDER_FILLED_MAX_BLOCK_RANGE:-500}"
    polygon_order_filled_max_windows="${POLYGON_ORDER_FILLED_MAX_WINDOWS:-1}"
    polygon_order_filled_import_cadence_minutes="${POLYGON_ORDER_FILLED_IMPORT_CADENCE_MINUTES:-60}"
    polygon_order_filled_retry_split="${POLYGON_ORDER_FILLED_RETRY_SPLIT:-true}"
    ;;
  *)
    echo "unsupported environment: ${environment}" >&2
    exit 2
    ;;
esac

required_common=(
  VPC_ID
  PRIVATE_SUBNET_IDS
  PUBLIC_SUBNET_IDS
)

for key in "${required_common[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    echo "missing required environment variable: ${key}" >&2
    exit 2
  fi
done

stack_name="${STACK_NAME:-codex-poly-bot-${environment}}"
project_name="${PROJECT_NAME:-codex-poly-bot}"
desired_count="${DESIRED_COUNT:-1}"
database_username="${DATABASE_USERNAME:-codexbot}"
dashboard_allowed_users="${DASHBOARD_ALLOWED_USERS:-yawetse}"
runtime_config_username="${RUNTIME_CONFIG_USERNAME:-}"
ses_identity_email="${SES_IDENTITY_EMAIL:-yaw.etse@gmail.com}"
if [[ -n "${NOTIFICATION_RECIPIENTS:-}" ]]; then
  notification_recipients="${NOTIFICATION_RECIPIENTS}"
elif [[ "${ses_identity_email}" == *"@"* ]]; then
  notification_recipients="operator:${ses_identity_email}"
else
  notification_recipients="operator:${NOTIFICATION_RECIPIENT_EMAIL:-yaw.etse@gmail.com}"
fi
manage_ses_identity="${MANAGE_SES_IDENTITY:-false}"
application_domain_name="${APPLICATION_DOMAIN_NAME:-}"
certificate_arn="${CERTIFICATE_ARN:-}"
github_client_id="${GITHUB_CLIENT_ID:-${DASHBOARD_GITHUB_CLIENT_ID:-}}"
github_client_secret="${GITHUB_CLIENT_SECRET:-${DASHBOARD_GITHUB_CLIENT_SECRET:-}}"
enable_background_worker="${ENABLE_BACKGROUND_WORKER:-${enable_background_worker_default}}"
worker_heartbeat_interval_seconds="${WORKER_HEARTBEAT_INTERVAL_SECONDS:-900}"
signoz_enabled="${SIGNOZ_ENABLED:-false}"
signoz_frontend_enabled="${SIGNOZ_FRONTEND_ENABLED:-${signoz_enabled}}"
signoz_region="${SIGNOZ_REGION:-}"
signoz_otlp_endpoint="${SIGNOZ_OTLP_ENDPOINT:-}"
signoz_ingestion_key_secret_arn="${SIGNOZ_INGESTION_KEY_SECRET_ARN:-}"
signoz_cloudwatch_read_policy_enabled="${SIGNOZ_CLOUDWATCH_READ_POLICY_ENABLED:-false}"
openai_tick_summary_timeout_seconds="${OPENAI_TICK_SUMMARY_TIMEOUT_SECONDS:-60}"

stack_exists="false"
if aws cloudformation describe-stacks --stack-name "${stack_name}" >/dev/null 2>&1; then
  stack_exists="true"
fi

required_on_create=(
  DATABASE_PASSWORD
  BACKEND_TOKEN_SIGNING_SECRET
  DASHBOARD_SESSION_SECRET
  DASHBOARD_CSRF_TOKEN
)

if [[ "${stack_exists}" == "false" ]]; then
  for key in "${required_on_create[@]}"; do
    if [[ -z "${!key:-}" ]]; then
      echo "missing required environment variable for first stack create: ${key}" >&2
      exit 2
    fi
  done
fi

parameter_overrides=(
  "EnvironmentName=${environment}"
  "ProjectName=${project_name}"
  "VpcId=${VPC_ID}"
  "PrivateSubnetIds=${PRIVATE_SUBNET_IDS}"
  "PublicSubnetIds=${PUBLIC_SUBNET_IDS}"
  "DesiredCount=${desired_count}"
  "LiveEnabled=${live_enabled}"
  "TradingAccountMode=${trading_account_mode}"
  "DefaultSelectedVenue=${default_selected_venue}"
  "PolymarketUsEnabled=${polymarket_us_enabled}"
  "PolymarketInternationalEnabled=${polymarket_international_enabled}"
  "AlpacaEnabled=${alpaca_enabled}"
  "PolymarketMarketOrderSlippage=${polymarket_slippage_threshold}"
  "AlpacaMarketOrderSlippage=${alpaca_slippage_threshold}"
  "AlpacaBaseUrl=${alpaca_base_url}"
  "AlpacaDataFeed=${alpaca_data_feed}"
  "AlpacaAccountStatus=${alpaca_account_status}"
  "AlpacaSymbolPresets=${alpaca_symbol_presets}"
  "AlpacaCustomSymbols=${alpaca_custom_symbols}"
  "AlpacaSymbolUniverse=${alpaca_symbol_universe}"
  "AlpacaSymbolChunkSize=${alpaca_symbol_chunk_size}"
  "AlpacaHistoricalBarLimit=${alpaca_historical_bar_limit}"
  "PolygonRpcUrl=${polygon_rpc_url}"
  "PolygonOrderFilledMaxBlockRange=${polygon_order_filled_max_block_range}"
  "PolygonOrderFilledMaxWindows=${polygon_order_filled_max_windows}"
  "PolygonOrderFilledImportCadenceMinutes=${polygon_order_filled_import_cadence_minutes}"
  "PolygonOrderFilledRetrySplit=${polygon_order_filled_retry_split}"
  "SesIdentityEmail=${ses_identity_email}"
  "NotificationRecipients=${notification_recipients}"
  "EnableBackgroundWorker=${enable_background_worker}"
  "WorkerHeartbeatIntervalSeconds=${worker_heartbeat_interval_seconds}"
  "OpenAiTickSummaryTimeoutSeconds=${openai_tick_summary_timeout_seconds}"
  "SignozEnabled=${signoz_enabled}"
  "SignozFrontendEnabled=${signoz_frontend_enabled}"
  "SignozRegion=${signoz_region}"
  "SignozOtlpEndpoint=${signoz_otlp_endpoint}"
  "SignozCloudWatchReadPolicyEnabled=${signoz_cloudwatch_read_policy_enabled}"
  "ManageSesIdentity=${manage_ses_identity}"
  "ApplicationDomainName=${application_domain_name}"
  "CertificateArn=${certificate_arn}"
  "DatabaseUsername=${database_username}"
  "DashboardAllowedUsers=${dashboard_allowed_users}"
  "RuntimeConfigUsername=${runtime_config_username}"
  "GithubClientId=${github_client_id}"
)

optional_secret_parameters=(
  DATABASE_PASSWORD:DatabasePassword
  BACKEND_TOKEN_SIGNING_SECRET:BackendTokenSigningSecret
  DASHBOARD_SESSION_SECRET:DashboardSessionSecret
  DASHBOARD_CSRF_TOKEN:DashboardCsrfToken
)

for item in "${optional_secret_parameters[@]}"; do
  env_key="${item%%:*}"
  parameter_key="${item##*:}"
  if [[ -n "${!env_key:-}" ]]; then
    parameter_overrides+=("${parameter_key}=${!env_key}")
  fi
done

if [[ -n "${github_client_secret}" ]]; then
  parameter_overrides+=("GithubClientSecret=${github_client_secret}")
fi

secret_arn_or_empty() {
  local secret_name="$1"
  aws secretsmanager describe-secret \
    --secret-id "${secret_name}" \
    --query ARN \
    --output text 2>/dev/null || true
}

add_secret_parameter_if_present() {
  local secret_name="$1"
  local parameter_name="$2"
  local secret_arn
  secret_arn="$(secret_arn_or_empty "${secret_name}")"
  if [[ -n "${secret_arn}" && "${secret_arn}" != "None" ]]; then
    parameter_overrides+=("${parameter_name}=${secret_arn}")
  fi
}

add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/polymarket/key-id" \
  "PolymarketKeyIdSecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/polymarket/secret-key" \
  "PolymarketSecretKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/polymarket/private-key" \
  "PolymarketPrivateKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/polymarket_us/openai/key-id" \
  "PolymarketOpenAiKeyIdSecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/polymarket_us/openai/secret-key" \
  "PolymarketOpenAiSecretKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/polymarket_us/openai/private-key" \
  "PolymarketOpenAiPrivateKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/polymarket_us/claude/key-id" \
  "PolymarketClaudeKeyIdSecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/polymarket_us/claude/secret-key" \
  "PolymarketClaudeSecretKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/polymarket_us/claude/private-key" \
  "PolymarketClaudePrivateKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/alpaca/key-id" \
  "AlpacaKeyIdSecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/alpaca/secret-key" \
  "AlpacaSecretKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/alpaca/openai/key-id" \
  "AlpacaOpenAiKeyIdSecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/alpaca/openai/secret-key" \
  "AlpacaOpenAiSecretKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/alpaca/claude/key-id" \
  "AlpacaClaudeKeyIdSecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/alpaca/claude/secret-key" \
  "AlpacaClaudeSecretKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/openai/admin-api-key" \
  "OpenAiAdminApiKeySecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/anthropic/admin-api-key" \
  "AnthropicAdminApiKeySecretArn"
if [[ -n "${signoz_ingestion_key_secret_arn}" ]]; then
  parameter_overrides+=("SignozIngestionKeySecretArn=${signoz_ingestion_key_secret_arn}")
else
  add_secret_parameter_if_present \
    "/codex-poly-bot/${environment}/signoz/ingestion-key" \
    "SignozIngestionKeySecretArn"
fi

aws cloudformation deploy \
  --stack-name "${stack_name}" \
  --template-file "codex-poly-bot/infra/cloudformation.yml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "${parameter_overrides[@]}" \
  --tags \
    "Project=${project_name}" \
    "Environment=${environment}" \
    "Application=codex-poly-bot" \
    "ManagedBy=cloudformation"

aws cloudformation describe-stacks \
  --stack-name "${stack_name}" \
  --query 'Stacks[0].Outputs' \
  --output table
