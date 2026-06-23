#!/usr/bin/env bash
set -euo pipefail

environment="${1:?usage: scripts/deploy-stack.sh development|production}"

case "${environment}" in
  development)
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
    ;;
  production)
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
ses_identity_email="${SES_IDENTITY_EMAIL:-yaw.etse@gmail.com}"
notification_recipients="${NOTIFICATION_RECIPIENTS:-operator:${ses_identity_email}}"
manage_ses_identity="${MANAGE_SES_IDENTITY:-false}"
application_domain_name="${APPLICATION_DOMAIN_NAME:-}"
certificate_arn="${CERTIFICATE_ARN:-}"
github_client_id="${GITHUB_CLIENT_ID:-${DASHBOARD_GITHUB_CLIENT_ID:-}}"
github_client_secret="${GITHUB_CLIENT_SECRET:-${DASHBOARD_GITHUB_CLIENT_SECRET:-}}"
enable_background_worker="${ENABLE_BACKGROUND_WORKER:-true}"
worker_heartbeat_interval_seconds="${WORKER_HEARTBEAT_INTERVAL_SECONDS:-60}"

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
  "SesIdentityEmail=${ses_identity_email}"
  "NotificationRecipients=${notification_recipients}"
  "EnableBackgroundWorker=${enable_background_worker}"
  "WorkerHeartbeatIntervalSeconds=${worker_heartbeat_interval_seconds}"
  "ManageSesIdentity=${manage_ses_identity}"
  "ApplicationDomainName=${application_domain_name}"
  "CertificateArn=${certificate_arn}"
  "DatabaseUsername=${database_username}"
  "DashboardAllowedUsers=${dashboard_allowed_users}"
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
  "/codex-poly-bot/${environment}/alpaca/key-id" \
  "AlpacaKeyIdSecretArn"
add_secret_parameter_if_present \
  "/codex-poly-bot/${environment}/alpaca/secret-key" \
  "AlpacaSecretKeySecretArn"

aws cloudformation deploy \
  --stack-name "${stack_name}" \
  --template-file "codex-poly-bot/infra/cloudformation.yml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "${parameter_overrides[@]}"

aws cloudformation describe-stacks \
  --stack-name "${stack_name}" \
  --query 'Stacks[0].Outputs' \
  --output table
