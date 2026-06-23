# Deployment

REQ: REQ-DEP-002, REQ-DEP-003, REQ-DEP-004, REQ-DEP-005, REQ-DEP-006, REQ-DEP-010, REQ-WAL-003

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

| Environment | Account mode | Live flag | Venue flags |
| --- | --- | --- | --- |
| `development` | `paper` | `LIVE_ENABLED=false` | `ALPACA_ENABLED=true`, Polymarket disabled |
| `production` | `live` | `LIVE_ENABLED=true` | `POLYMARKET_US_ENABLED=true`, `ALPACA_ENABLED=true` |

The profile values are recorded in `infra/parameters/dev.json` and `infra/parameters/prod.json`, and the CloudFormation task definitions expose matching runtime environment variables.

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
- `CERTIFICATE_ARN`
- `DASHBOARD_ALLOWED_USERS`
- `DASHBOARD_GITHUB_CLIENT_ID`
- `DATABASE_USERNAME`
- `DESIRED_COUNT`
- `PRIVATE_SUBNET_IDS`
- `PUBLIC_SUBNET_IDS`
- `SES_IDENTITY_EMAIL`
- `VPC_ID`

Set these GitHub environment secrets for both environments:

- `BACKEND_TOKEN_SIGNING_SECRET`
- `DASHBOARD_CSRF_TOKEN`
- `DASHBOARD_SESSION_SECRET`
- `DATABASE_PASSWORD`
- `DASHBOARD_GITHUB_CLIENT_SECRET`

Trading credentials are not stored in GitHub Actions secrets. Live venue, wallet, broker, LLM, and notification secrets must be stored in AWS Secrets Manager under the active environment prefix. The ECS task definitions inject `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from `/codex-poly-bot/{environment}/openai/api-key` and `/codex-poly-bot/{environment}/anthropic/api-key`.

CloudFormation creates placeholder OpenAI and Anthropic secret values so ECS can start before provider keys exist. Replace those AWS Secrets Manager values with provider-issued API keys before using model-backed workflows.
