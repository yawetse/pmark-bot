# SigNoz Observability

REQ: REQ-OBS-001, REQ-OBS-002, REQ-OBS-005, REQ-OBS-006

Use this guide to turn on SigNoz for codex-poly-bot without putting account secrets in the repo.

## Data Sources

The app now emits these sources:

- Backend traces and logs from FastAPI as `codex-poly-bot-backend`.
- Backend HTTP response logs with method, route, status, duration, request id, environment, and client IP.
- Frontend browser traces and logs as `codex-poly-bot-frontend`.
- Frontend JavaScript error, unhandled rejection, and `console.error` logs.
- Frontend-to-backend proxy response logs from the Next.js server.
- ECS application logs in CloudWatch under `/aws/ecs/codex-poly-bot/<environment>`.

## SigNoz Cloud

Set these variables in local `.env.local`, ECS task parameters, or your deployment environment:

```bash
SIGNOZ_ENABLED=true
SIGNOZ_FRONTEND_ENABLED=true
SIGNOZ_REGION=<region>
SIGNOZ_INGESTION_KEY=<ingestion-key>
SIGNOZ_SERVICE_NAME=codex-poly-bot-backend
SIGNOZ_FRONTEND_SERVICE_NAME=codex-poly-bot-frontend
```

`SIGNOZ_OTLP_ENDPOINT` is optional. If it is empty, the app derives `https://ingest.<region>.signoz.cloud:443`.

For AWS deployment, store the ingestion key in Secrets Manager and pass its ARN as `SignozIngestionKeySecretArn`. The frontend uses a same-origin OTLP proxy, so the key stays server-side.

## CloudWatch Logs

The CloudFormation stack already writes backend and frontend container logs to CloudWatch. Set `SignozCloudWatchReadPolicyEnabled=true` only when the deploy role is allowed to create managed IAM policies and you want CloudFormation to output `SignozCloudWatchReadPolicyArn` for the application log group.

Use `infra/signoz-cloudwatch-collector.yml` with `otelcol-contrib` when you want a manual CloudWatch pull collector:

```bash
AWS_REGION=us-east-1 \
PROJECT_NAME=codex-poly-bot \
ENVIRONMENT_NAME=production \
SIGNOZ_REGION=<region> \
SIGNOZ_INGESTION_KEY=<ingestion-key> \
otelcol-contrib --config infra/signoz-cloudwatch-collector.yml
```

If you use the SigNoz Cloud one-click AWS integration instead, point it at the same CloudWatch log group and keep the policy scope limited to `/aws/ecs/codex-poly-bot/<environment>`.

## MCP

For Codex, add the hosted SigNoz MCP server:

```bash
codex mcp add signoz --url https://mcp.<region>.signoz.cloud/mcp
codex mcp login signoz
```

The repo also includes `.codex/config.toml.example` with the same MCP URL template.

## Alert Issue Routing

GPDoc owns the shared SigNoz webhook relay that creates GitHub issues from alerts. `codex-poly-bot` alerts should route to `yawetse/pmark-bot` with these labels:

- `signoz-alert`
- `area:codex-poly-bot`
- `severity:critical`, `severity:error`, `severity:warning`, or `severity:info`
- `codex-auto` for critical and error alerts that should start Codex triage

The repository root includes `.github/workflows/signoz-codex-alert.yml`. The workflow starts only when an issue has both `signoz-alert` and `codex-auto`. It can comment, upload a patch artifact, or open a draft pull request. It does not merge, deploy, or change live trading settings.

Alert issue closure is controlled by labels and repository evidence. A `signoz-resolved` issue closes automatically unless an open remediation pull request references the issue. A synthetic or smoke-test alert closes automatically when Codex produces no remediation patch. Other firing production alerts stay open until they are resolved, fixed, or manually closed.

Set the repository secret `OPENAI_API_KEY` before relying on Codex Action runs. Without that secret, the workflow comments on the issue and leaves it open for manual triage.

## Local Check

With SigNoz disabled, HTTP response logs still appear in normal app logs. With SigNoz enabled, verify:

- `codex-poly-bot-backend` appears under Services.
- `codex-poly-bot-frontend` appears after opening the dashboard in a browser.
- Logs Explorer contains `http_response` entries.
- CloudWatch logs contain `aws.cloudwatch.log_group_name` after the collector or AWS integration runs.
