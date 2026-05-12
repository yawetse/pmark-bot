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

Development and production use separate parameter files, stack names, secret prefixes, and resources.

## CI and Deploy Flow

GitHub Actions runs backend tests and frontend checks first. Migration safety runs after tests and rejects destructive SQL markers that require an expand/contract release. Container build and ECR publish run only after the test and migration gates pass.

Merges to `develop` select the development environment. Merges to `main` select production. Other branches run CI without automatic deployment.

## Required GitHub Secrets

- `AWS_DEPLOY_ROLE_ARN`: OIDC role allowed to deploy the matching environment.

Trading credentials are not stored in GitHub Actions secrets. Live venue, wallet, broker, LLM, and notification secrets must be stored in AWS Secrets Manager under the active environment prefix.
