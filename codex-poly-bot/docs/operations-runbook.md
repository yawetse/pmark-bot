# Operations Runbook

REQ: REQ-DEP-004, REQ-EXE-014, REQ-OBS-005, REQ-WAL-006

Use this runbook for live incidents, degraded health, bad deploys, and credential failures.

## SigNoz Observability

Use `docs/signoz-observability.md` to enable SigNoz traces, logs, frontend browser telemetry, CloudWatch log forwarding, and the SigNoz MCP server. Keep `SIGNOZ_INGESTION_KEY` in local env or AWS Secrets Manager, not in tracked files.

## Manual Runs

Use the Operations dashboard manual-run controls when you need to trigger the loop outside the scheduler.

- `Data import` fetches provider market data and stops before scanner logic.
- `Scanner only` fetches data, runs scanner filters, and stops before LLM reasoning.
- `Full dry run` runs data fetch, scanner, reasoning, execution, and exit with live execution disabled for that run.
- `Full live-gated` runs all five stages with the configured live setting, credentials, risk gates, persistence gate, and kill switch still enforced.

Skipped downstream stages are recorded as `skipped` pipeline rows. Review the pipeline detail grid to see the records behind each step.

Live-gated runs can submit real orders only when the runtime has attached venue submitters. The backend attaches them when `LIVE_ENABLED=true`, the venue flag is enabled, required credentials are present, and the Alpaca account status is `active`.

- Alpaca entries use market buy orders at `/v2/orders` with notional sizing.
- Alpaca exits use market sell orders at `/v2/orders` with tracked quantity.
- Polymarket entries use the official Polymarket US SDK `orders.create`.
- Polymarket exits use the official Polymarket US SDK `orders.close_position`.

If a submitter is missing, the pipeline records `LIVE_SUBMITTER_NOT_CONFIGURED` or `LIVE_EXIT_SUBMITTER_NOT_CONFIGURED` and does not call the venue.

## Provider Usage Imports

Use the Economics panel provider import buttons to backfill AI usage from provider-side reporting.

- OpenAI import requires `/codex-poly-bot/{environment}/openai/admin-api-key`, injected as `OPENAI_ADMIN_API_KEY`, or `OPENAI_USAGE_API_KEY` in the backend runtime environment.
- Claude import requires `/codex-poly-bot/{environment}/anthropic/admin-api-key`, injected as `ANTHROPIC_ADMIN_API_KEY`, or `ANTHROPIC_USAGE_API_KEY` in the backend runtime environment.
- Missing admin keys are recorded as `unsupported`, not as successful pulls.
- HTTP failures, provider rate limits, and response parsing failures are recorded as failed import runs.
- Imported rows are stored in `shared.ai_usage_events`; import attempts are stored in `shared.ai_usage_import_runs`.

The token spend grid shows usage source, cost source, latest usage time, latest import time, and provider import error state.

## Immediate Stop

1. Activate the kill switch from the dashboard operations view or the live-control API.
2. Verify `LIVE_ENABLED=false` and kill switch state is active for all venues and model providers.
3. Confirm open-order cancellation attempts are recorded for enabled venues.
4. Review recent audit events and system health indicators in the dashboard.

## Credential or Venue Failure

1. Keep live mode disabled for the affected venue.
2. Verify the missing wallet, brokerage, or API credential in AWS Secrets Manager.
3. Confirm the secret path uses the active environment prefix.
4. Rerun dry-run checks before re-enabling venue flags.

## ECS Rollback

Use ECS rollback when a bad deploy affects application code and the database migration is backward compatible.

1. Find the previous healthy task definition revision:

```bash
aws ecs list-task-definitions \
  --family-prefix codex-poly-bot-production-backend \
  --sort DESC
```

2. Update the service to the previous known healthy task definition:

```bash
aws ecs update-service \
  --cluster codex-poly-bot-production-cluster \
  --service codex-poly-bot-production-backend \
  --task-definition codex-poly-bot-production-backend:PREVIOUS_REVISION
```

3. Wait for service stability:

```bash
aws ecs wait services-stable \
  --cluster codex-poly-bot-production-cluster \
  --services codex-poly-bot-production-backend
```

4. Verify dashboard health, recent audit events, and notification delivery.

## RDS Restore Point Guidance

Use RDS restore only when data corruption or an unsafe migration requires database recovery. Prefer a point-in-time restore to a new DB instance, validate it, then cut over through a controlled change.

1. Identify the last known good restore point.
2. Restore the database to a new RDS instance from that restore point.
3. Run schema and smoke checks against the restored instance.
4. Keep live trading disabled until the restored database is verified.
5. Update application configuration to the restored endpoint only after approval.
6. Keep the failed database available for investigation until incident review is complete.

Do not use RDS restore as the first response to a normal application regression. Roll back ECS first when the schema remains compatible.
