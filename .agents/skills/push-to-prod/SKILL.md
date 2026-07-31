---
name: push-to-prod
description: Ship codex-poly-bot through the approved GitHub and AWS release path. Use when the user asks to push, deploy, release, promote, merge develop to main, check CI/CD, verify development or production deployment, or collect evidence for Codex Poly Bot environments.
---

# Push To Prod

## Scope

Use this workflow for `/Users/yawetse/Developer/github/yawetse/pmark-bot/codex-poly-bot`.
Keep live trading credentials, broker credentials, wallet private keys, and LLM API keys out of git. Store deployed credentials in AWS Secrets Manager under `/codex-poly-bot/{environment}/...`.

## Branch Flow

1. Work on a `codex/...` branch.
2. Open a PR into `develop`.
3. Merge to `develop` only after backend tests, frontend checks, migration safety, and image build pass.
4. A push to `develop` deploys the `development` GitHub environment and AWS stack `codex-poly-bot-development`.
5. Open a PR from `develop` into `main` for production promotion.
6. Merge to `main` only after the same checks pass.
7. A push to `main` deploys the `production` GitHub environment and AWS stack `codex-poly-bot-production`.

## CI/CD Contract

Confirm the root workflow `.github/workflows/codex-poly-bot-ci.yml` and the project copy `codex-poly-bot/.github/workflows/ci.yml` stay aligned.

Required job order:

1. `backend-tests`
2. `frontend-check`
3. `migration-safety`
4. `infrastructure-deploy` on pushes to `develop` or `main`
5. `container-build`
6. `deploy-development` or `deploy-production`

The infrastructure job must run `./codex-poly-bot/scripts/deploy-stack.sh`. The ECS deploy job must force new deployments and run `aws ecs wait services-stable`.

## GitHub Environment Inputs

Each GitHub environment needs these variables:

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

Each GitHub environment needs these secrets:

- `AWS_DEPLOY_ROLE_ARN`
- `BACKEND_TOKEN_SIGNING_SECRET`
- `DASHBOARD_CSRF_TOKEN`
- `DASHBOARD_SESSION_SECRET`
- `DATABASE_PASSWORD`
- `DASHBOARD_GITHUB_CLIENT_SECRET`

## AWS Runtime Contract

Use `us-east-1`.

Development:

- Stack: `codex-poly-bot-development`
- Domain: `dev-codex-poly-bot.repetere.net`
- Runtime: `LIVE_ENABLED=false`, `TRADING_ACCOUNT_MODE=paper`, `ALPACA_ENABLED=true`

Production:

- Stack: `codex-poly-bot-production`
- Domain: `codex-poly-bot.repetere.net`
- Runtime: `LIVE_ENABLED=true`, `TRADING_ACCOUNT_MODE=live`, `POLYMARKET_US_ENABLED=true`, `ALPACA_ENABLED=true`

The CloudFormation template must support an ACM certificate, HTTP-to-HTTPS redirect, ALB HTTPS listener, SES identity, and ECS secret injection for:

- `/codex-poly-bot/{environment}/openai/api-key`
- `/codex-poly-bot/{environment}/anthropic/api-key`

## Validation

Before publishing, run:

```bash
aws cloudformation validate-template --template-body file://codex-poly-bot/infra/cloudformation.yml
bash -n codex-poly-bot/scripts/deploy-stack.sh
cd codex-poly-bot/backend && python -m pytest tests/spec/test_deployment_ci.py
cd ../frontend && npm run typecheck && npm run test:auth-boundary && npm run test:dashboard-controls && npm run test:dashboard-operations
```

If a command cannot run because dependencies are missing, install the repo-local dependencies and rerun once.

## Evidence

After deployment, collect evidence without printing secret values:

- GitHub Actions run URL and final status for the branch push.
- `aws cloudformation describe-stacks` outputs for dev and prod, excluding secrets.
- `aws ecs describe-services` health for backend and frontend in dev and prod.
- HTTPS health checks for `https://dev-codex-poly-bot.repetere.net/health` and `https://codex-poly-bot.repetere.net/health`.
- Browser screenshots for the dev and prod application URLs.
- SES identity verification status for `asyncdoc.net`.
- ACM certificate status for the repetere.net hostnames.

## Goal Completion Handoff

For every completed push-to-production goal:

1. Keep the goal active until the production deployment and every required evidence check pass.
2. Add the final commit, pull requests, GitHub Actions, CloudFormation, ECS, HTTPS, SES, ACM, and screenshot evidence to the tracking GitHub issue.
3. Email the authenticated user with the same evidence. For Gmail self-delivery, send directly to `me`, then verify the message in Sent.
4. Archive the current Codex thread only after the evidence email is confirmed sent.
5. If email delivery or thread archival is unavailable, keep the goal active and report the blocker. Never archive before a failed or unverified delivery.

## Publish Rules

Stage only files related to this deployment. Do not stage unrelated dirty files from other bot projects.
Open PRs as draft unless the user explicitly asks for ready review.
Do not merge PRs unless the user explicitly requests the merge or the task includes an approved push-to-prod run.
