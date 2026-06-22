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
    ;;
  production)
    live_enabled="true"
    trading_account_mode="live"
    default_selected_venue="polymarket_us"
    polymarket_us_enabled="true"
    polymarket_international_enabled="false"
    alpaca_enabled="true"
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
manage_ses_identity="${MANAGE_SES_IDENTITY:-false}"
application_domain_name="${APPLICATION_DOMAIN_NAME:-}"
certificate_arn="${CERTIFICATE_ARN:-}"
github_client_id="${GITHUB_CLIENT_ID:-${DASHBOARD_GITHUB_CLIENT_ID:-}}"
github_client_secret="${GITHUB_CLIENT_SECRET:-${DASHBOARD_GITHUB_CLIENT_SECRET:-}}"

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
  "SesIdentityEmail=${ses_identity_email}"
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

aws cloudformation deploy \
  --stack-name "${stack_name}" \
  --template-file "codex-poly-bot/infra/cloudformation.yml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "${parameter_overrides[@]}"

aws cloudformation describe-stacks \
  --stack-name "${stack_name}" \
  --query 'Stacks[0].Outputs' \
  --output table
