# Deployment

REQ: REQ-DEP-002, REQ-DEP-003, REQ-DEP-004, REQ-DEP-005, REQ-DEP-006, REQ-DEP-010, REQ-WAL-003, REQ-KAL-004, REQ-KAL-010

`codex-poly-bot` deploys to AWS `us-east-1`. The infrastructure contract is defined in `infra/cloudformation.yml`.

## AWS Stack

- Compute: ECS Fargate services for backend and frontend workloads.
- Images: Amazon ECR repositories for backend and frontend containers.
- Database: RDS Postgres.
- Storage: S3 snapshot buckets with lifecycle retention.
- Secrets: AWS Secrets Manager paths scoped to `/codex-poly-bot/{environment}/...`.
- Observability: CloudWatch log groups.
- Notifications: Amazon SES email identity.
- HTTPS: ALB listener with ACM certificate support and HTTP-to-HTTPS redirects.

Development and production use separate parameter files, stack names, secret prefixes, and resources.
The planned hostnames are:

| Environment | Hostname |
| --- | --- |
| `development` | `dev-codex-poly-bot.repetere.net` |
| `production` | `codex-poly-bot.repetere.net` |

## Runtime Profiles

The deployed profiles are explicit and separate:

| Environment | Account mode | Live flag | Venue flags | Worker default |
| --- | --- | --- | --- | --- |
| `development` | `paper` | `LIVE_ENABLED=false` | `ALPACA_ENABLED=true`; Polymarket and Kalshi disabled by default | `ENABLE_BACKGROUND_WORKER=true` |
| `production` | `live` | `LIVE_ENABLED=true` | `POLYMARKET_US_ENABLED=true`, `ALPACA_ENABLED=true`; Kalshi disabled until its secrets and account checks pass | `ENABLE_BACKGROUND_WORKER=false` |

The profile values are recorded in `infra/parameters/dev.json` and `infra/parameters/prod.json`, and the CloudFormation task definitions expose matching runtime environment variables.
Production keeps the in-process scheduler disabled by default so dashboard/API health is isolated from worker memory failures. Set `ENABLE_BACKGROUND_WORKER=true` only after the worker path is verified or split into a separate service.

To refresh local copies of deployed secrets after authenticating to AWS, run:

```bash
./scripts/sync-env-files.py development --pull-aws
./scripts/sync-env-files.py production --pull-aws
```

The helper reads AWS Secrets Manager paths under `/codex-poly-bot/{environment}/...` when the local AWS session is valid. GitHub Actions secrets cannot be read back through the GitHub API; only GitHub variables are readable.

## CI and Deploy Flow

GitHub Actions runs backend tests and frontend checks first. Migration safety runs after tests and rejects destructive SQL markers that require an expand/contract release. On pushes to deployable branches, the workflow then deploys or updates CloudFormation, builds and publishes images to ECR, forces ECS deployments, and waits for both services to become stable.

Merges to `develop` select the development environment. Merges to `main` select production. Other branches run CI without automatic deployment.

The first production deployment depends on GitHub environment configuration:

| GitHub environment | Merge target | AWS stack |
| --- | --- | --- |
| `development` | `develop` | `codex-poly-bot-development` |
| `production` | `main` | `codex-poly-bot-production` |

## Required GitHub Configuration

- `AWS_DEPLOY_ROLE_ARN`: OIDC role allowed to deploy the matching environment.

Set these GitHub environment variables for both `development` and `production`:

- `APPLICATION_DOMAIN_NAME`
- `ALPACA_ACCOUNT_STATUS`
- `CERTIFICATE_ARN`
- `DASHBOARD_ALLOWED_USERS`
- `DASHBOARD_GITHUB_CLIENT_ID`
- `DATABASE_USERNAME`
- `DESIRED_COUNT`
- `KALSHI_ENABLED`
- `KALSHI_MARKET_ORDER_SLIPPAGE`
- `KALSHI_MARKET_DATA_LIMIT`
- `KALSHI_MARKET_PAGE_SIZE`
- `KALSHI_READ_RETRIES`
- `KALSHI_RETRY_BACKOFF_SECONDS`
- `PRIVATE_SUBNET_IDS`
- `PUBLIC_SUBNET_IDS`
- `SES_IDENTITY_EMAIL`
- `VPC_ID`

Use `ALPACA_ACCOUNT_STATUS=active` only after the live account approval and live-trading checklist evidence are complete. Production deploys otherwise default Alpaca to `reviewing`.

Set these GitHub environment secrets for both environments:

- `BACKEND_TOKEN_SIGNING_SECRET`
- `DASHBOARD_CSRF_TOKEN`
- `DASHBOARD_SESSION_SECRET`
- `DATABASE_PASSWORD`
- `DASHBOARD_GITHUB_CLIENT_SECRET`

## GitHub OAuth Callback URLs

Use a separate GitHub OAuth app for each deployed environment. The frontend sends a `redirect_uri` built from `NEXTAUTH_URL`, and CloudFormation sets `NEXTAUTH_URL` from `APPLICATION_DOMAIN_NAME`.

| Environment | GitHub OAuth app callback URL |
| --- | --- |
| `development` | `https://dev-codex-poly-bot.repetere.net/api/auth/github/callback` |
| `production` | `https://codex-poly-bot.repetere.net/api/auth/github/callback` |

Store each OAuth app's client ID in that environment's `DASHBOARD_GITHUB_CLIENT_ID` variable and the matching client secret in `DASHBOARD_GITHUB_CLIENT_SECRET`. A GitHub "redirect_uri is not associated with this application" error means the callback URL registered on the OAuth app does not match the URL sent by `/api/auth/github/start`.

Verify the deployed redirect before testing login:

```bash
curl -sSI https://dev-codex-poly-bot.repetere.net/api/auth/github/start | grep -i '^location:'
curl -sSI https://codex-poly-bot.repetere.net/api/auth/github/start | grep -i '^location:'
```

Trading credentials are not stored in GitHub Actions secrets. Live venue, wallet, broker, LLM, and notification secrets must be stored in AWS Secrets Manager under the active environment prefix. The ECS task definitions inject `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from `/codex-poly-bot/{environment}/openai/api-key` and `/codex-poly-bot/{environment}/anthropic/api-key`.

CloudFormation creates placeholder OpenAI and Anthropic secret values so ECS can start before provider keys exist. Replace those AWS Secrets Manager values with provider-issued API keys before using model-backed workflows.

## Kalshi Secrets and Hosts

The deploy script sets `KALSHI_ENVIRONMENT=demo` in development and `KALSHI_ENVIRONMENT=production` in production. The application derives the recommended Kalshi host from that value and rejects environment crossover. It does not accept a runtime base URL override.

The deploy script discovers these optional secret paths and omits each ECS injection when the path does not exist:

- `/codex-poly-bot/{environment}/kalshi/market-data/key-id`
- `/codex-poly-bot/{environment}/kalshi/market-data/private-key`
- `/codex-poly-bot/{environment}/kalshi/openai/key-id`
- `/codex-poly-bot/{environment}/kalshi/openai/private-key`
- `/codex-poly-bot/{environment}/kalshi/claude/key-id`
- `/codex-poly-bot/{environment}/kalshi/claude/private-key`

Missing read credentials permit public market summaries but suppress order-book candidates. Missing provider credentials suppress account reconciliation and live submission for that provider. A release must verify zero Kalshi `POST` and `DELETE` operations in the deployment window; production validation uses public and authenticated GET requests only.

## Optional Alpaca Broker Funding Secrets

Direct incoming ACH support uses four optional secrets per model provider:

- `/codex-poly-bot/{environment}/alpaca/openai/broker-api-key`
- `/codex-poly-bot/{environment}/alpaca/openai/broker-api-secret`
- `/codex-poly-bot/{environment}/alpaca/openai/broker-account-id`
- `/codex-poly-bot/{environment}/alpaca/openai/ach-relationship-id`
- `/codex-poly-bot/{environment}/alpaca/claude/broker-api-key`
- `/codex-poly-bot/{environment}/alpaca/claude/broker-api-secret`
- `/codex-poly-bot/{environment}/alpaca/claude/broker-account-id`
- `/codex-poly-bot/{environment}/alpaca/claude/ach-relationship-id`

The deploy script discovers these paths when they exist and omits them otherwise. Development and production paths remain separate. Do not place bank account details, raw routing data, or Plaid tokens in the stack, GitHub, application config, logs, or funding tables.

Every release that includes funding code must read back the authenticated funding config and confirm direct funding is disabled with both limits set to `0.00`. Query the backend CloudWatch log group for `funding_broker_post_attempt` over the release window and require a zero count. Do not use a real transfer as a deployment smoke test.
