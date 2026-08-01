# Operations Runbook

REQ: REQ-DEP-004, REQ-EXE-014, REQ-OBS-005, REQ-WAL-006, REQ-FND-019, REQ-ALP-019, REQ-ALP-025, REQ-ALP-026

Use this runbook for live incidents, degraded health, bad deploys, and credential failures.

## Recurring Funding

Funding schedules are saved under Settings and run directly after the confirmed venue portfolio refresh. Weekly and monthly schedules create expected deposits at 09:00 America/New_York on the next business day when needed. Low-balance schedules require a fresh confirmed buying-power snapshot. Polymarket is observe-only.

Bank and ACH setup remains venue-managed. The application has no Plaid integration. Optional direct Alpaca deposits require an existing ACH relationship plus provider-scoped Broker secrets for the API key, API secret, account ID, and relationship ID. Missing secrets do not block application startup.

Keep `direct_transfers_enabled=false`, `max_transfer_usd=0.00`, and `max_monthly_transfer_usd=0.00` until a separate direct-funding change is approved. The global kill switch or funding emergency stop blocks new transfer claims while activity reads, matching, missing detection, and recovery alerts continue.

Review `reserved`, `submitted`, and `unknown` direct occurrences before changing limits. A claim with `post_attempted_at` is never posted again. The worker reconciles it by exact provider transfer ID or one exact incoming amount, ACH relationship, and time-window candidate. Zero or multiple candidates remain `unknown`. Terminal rejection, return, or failure releases the reservation and creates one alert.

An alert in `sending` means delivery was claimed but the final SES result was not persisted. Review SES and CloudWatch before changing that row. Do not reset it to pending without confirming that SES did not accept the message.

For rollback, first enable the funding emergency stop and set direct funding and both limits to the disabled zero defaults. Roll back ECS only after these values are read back. Funding tables are retained so expected, missing, matched, and cash-flow history remains available after application rollback.

Release smoke tests must not create a real transfer. Verify authenticated funding config readback and query the backend CloudWatch log group for the structured marker `funding_broker_post_attempt`. The release window must contain zero matching events.

## Alpaca Short Selling

Short entry is an audited application setting and defaults to `alpaca.allow_shorting=false`. Keep it disabled until the selected Alpaca account reports active status, shorting enabled, at least 2,000 USD equity, enough current buying power, and no trading or account block. Each entry also requires the current asset to be active, tradable, shortable, and `easy_to_borrow`.

Each model provider must resolve to a distinct Alpaca account in the same environment and mode. If two providers resolve to one account, the service quarantines that account and blocks both provider routes. Correct both credentials and complete one successful refresh with distinct routes before live routing can resume. Portfolio refresh also reconciles submitted local intents from exact broker fill and terminal order evidence before it compares open orders.

When approved, enable the setting under **Settings > Trading Access**. The service uses whole-share sell-to-open orders only. It refuses notional and fractional short entries, hard-to-borrow or unknown borrow states, and any new entry where a position or unresolved order exists in the symbol.

Disabling the setting stops new shorts. It does not block an exact risk-reducing buy-to-close for an existing reconciled short. The close is routed by environment, model provider, account mode, and account registration. If the broker cannot accept the exact quantity or the current account does not match the originating account, the service refuses automation and records an operator-action state. Never round down a fractional short cover.

For rollback, save `alpaca.allow_shorting=false` first and read it back. Leave exit monitoring running so existing short exposure can close through the exact cover path. Then roll back ECS if the application build must be reverted. Deployment verification uses read-only Alpaca account and asset calls and never places a live short order.

## SigNoz Observability

Use `docs/signoz-observability.md` to enable SigNoz traces, logs, frontend browser telemetry, optional CloudWatch log forwarding, and the SigNoz MCP server. Keep `SIGNOZ_INGESTION_KEY` in local env or AWS Secrets Manager, not in tracked files.

## Manual Runs

Use the Operations dashboard manual-run controls when you need to trigger the loop outside the scheduler.

- `Data import` fetches provider market data and stops before scanner logic.
- `Scanner only` fetches data, runs scanner filters, and stops before LLM reasoning.
- `Full dry run` runs data fetch, scanner, reasoning, execution, and exit with live execution disabled for that run.
- `Full live-gated` runs all five stages with the configured live setting, credentials, risk gates, persistence gate, and kill switch still enforced.

Skipped downstream stages are recorded as `skipped` pipeline rows. Review the pipeline detail grid to see the records behind each step.

## Data Source Boundaries

- Imported Polymarket history comes from clean-room Gamma market metadata and Polygon `OrderFilled` backfills.
- Provider market data is the current snapshot used by scanner runs, separate from historical imports.
- Scanner results are filter decisions over provider data plus persisted historical context.
- LLM reasoning rows are model-provider scoring records created only after scanner acceptance.
- Execution rows are order intents and simulated or submitted order outcomes.
- Exit monitoring rows are position checks and exit intents, separate from entry execution.

Historical import records can explain wallet and market context, but they are not proof that a current scanner, LLM, execution, or exit stage ran.

## Historical Import Runtime Config

The clean-room Polygon backfill path uses non-secret runtime settings:

- `POLYGON_RPC_URL`: Polygon JSON-RPC endpoint used for `eth_getLogs`.
- `POLYGON_ORDER_FILLED_MAX_BLOCK_RANGE`: maximum block span per request before splitting.
- `POLYGON_ORDER_FILLED_MAX_WINDOWS`: maximum windows per importer run.
- `POLYGON_ORDER_FILLED_IMPORT_CADENCE_MINUTES`: minimum cadence for scheduled import attempts.
- `POLYGON_ORDER_FILLED_RETRY_SPLIT`: whether oversized-window errors should retry with smaller windows.

Treat RPC URLs with embedded provider tokens as secrets even though the base setting is non-secret.

Live-gated runs can submit real orders only when the runtime has attached venue submitters. The backend attaches them when `LIVE_ENABLED=true`, the venue flag is enabled, required credentials are present, and the Alpaca account status is `active`.

- Alpaca long entries use market buy-to-open orders at `/v2/orders` with notional sizing.
- Enabled Alpaca short entries use eligible whole-share sell-to-open orders at `/v2/orders` after current account and asset checks.
- Alpaca exits use sell-to-close for longs and exact-quantity buy-to-close for shorts.
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
