# Trading Account Readiness Plan

Purpose: track the account, credential, and verification work needed before asking Codex to confirm live trading connectivity.

Do not paste secrets into this plan. Check off items only after the action is complete and the evidence is available outside this file.

## Phase 1: Accounts

- [x] Polymarket US account created.
- [x] Polymarket US identity verification approved.
- [x] Polymarket US account funded.
- [x] Alpaca account created.
- [x] Alpaca brokerage identity verification approved.
- [x] Alpaca paper trading account available.
- [x] Alpaca live brokerage account funded with the starting live-test amount.

## Phase 2: API Credentials

- [x] Polymarket US developer API key created.
- [x] Polymarket US API key ID stored outside the repo.
- [x] Polymarket US API secret stored outside the repo.
- [x] Alpaca paper API key ID and secret created.
- [x] Alpaca live API key ID and secret created.
- [x] Alpaca paper and live base URLs recorded outside the repo.
- [x] Market data feed selected for Alpaca: `iex` or `sip`.

## Phase 3: AWS Secret Storage

- [x] Development Polymarket US secrets created in AWS Secrets Manager.
- [x] Development Alpaca paper secrets created in AWS Secrets Manager.
- [x] Production Polymarket US secrets created in AWS Secrets Manager, if production is in scope.
- [x] Production Alpaca live secrets created in AWS Secrets Manager, if production is in scope.
- [x] AWS secret names match the bot's credential-loading contract.
- [x] No trading secrets are present in GitHub secrets, markdown files, `.env`, screenshots, or terminal history.

Evidence 2026-07-02: AWS identity `arn:aws:iam::506304330252:user/yawetse` confirmed access to `us-east-1`. Secrets Manager contains the expected development and production Polymarket, Alpaca, OpenAI, Anthropic, and SigNoz secret names under `/codex-poly-bot/{environment}/...`; ECS backend task definitions inject only the expected secret environment names, without printing secret values.

Polymarket evidence 2026-07-02: `scripts/polymarket-readonly-smoke.py` used AWS Secrets Manager values to authenticate against Polymarket US in development and production, returned successful read-only account and market checks, and attempted no order operations. Local Polymarket credential values were removed from `.env.local`, `.env.development`, and `.env.production`.

Polymarket account evidence 2026-07-02: operator confirmed Polymarket US is set for live trading and provided an app screenshot showing username `goofyrobin3284`, `$120 cash`, deposit and withdraw controls, and no positions. The non-secret identifier is recorded in `docs/trading-account-inventory.md`.

Alpaca account evidence 2026-07-03: operator confirmed the live Alpaca account is created and funded. Screenshot evidence showed the Alpaca dashboard for an individual trading brokerage account with `$100.00` portfolio value, `$100.00` buying power, `$100.00` cash, and no open positions. Account numbers and credentials are intentionally not recorded here.

Read-only Alpaca verification 2026-07-03: Codex retrieved Alpaca credentials from AWS Secrets Manager without printing values, confirmed the paper account is `ACTIVE`, confirmed IEX market data returned a SPY quote, confirmed the live account is `ACTIVE` and unblocked, confirmed recent live order count was `0`, and attempted no order operations. Alpaca returned `shorting_enabled=false` and no options levels, but did not return a clear `account_type`; cash-vs-margin and full restriction confirmation remain open.

Secret hygiene and account validation 2026-07-07: Codex scrubbed local Alpaca values from `.env.production`, `.env.local`, and `.env.development`. An exact-value scan across 10 AWS-stored Alpaca/Polymarket trading secrets, 208 repo text/history files, and shell history returned no matches. GitHub secret names contain no Alpaca or Polymarket trading keys. Computer Use confirmed Alpaca MFA is enabled, the live account is funded, Market Data is `Basic`, and no ACH/wire connected funding account is currently shown. Live Alpaca read-only API checks returned `ACTIVE`, unblocked, no open orders, cash and buying power present, `shorting_enabled=false`, and no options levels. Polymarket production read-only smoke checks succeeded for account balances and market listing with no order operations attempted.

## Phase 4: Bot Safety Gates

- [x] Production `LIVE_ENABLED=true` confirmed as intentional operator direction.
- [x] Production `POLYMARKET_US_ENABLED=true` confirmed as intentional operator direction.
- [x] Production `ALPACA_ENABLED=true` confirmed as intentional operator direction.
- [x] Dashboard authentication works for the approved operator.
- [x] Notification delivery works.
- [ ] Kill switch works from the dashboard or API.
- [x] Risk limits are set for max position size, max daily loss, max open positions, and slippage.
- [x] Fix production dashboard operations/readiness payload OOM before live-readiness closure.

Evidence 2026-07-02: Operator confirmed live trading should be enabled. AWS production backend task definition `codex-poly-bot-production-backend:15` has `LIVE_ENABLED=true`, `TRADING_ACCOUNT_MODE=live`, `POLYMARKET_US_ENABLED=true`, `ALPACA_ENABLED=true`, and `ALPACA_ACCOUNT_STATUS=active`.

Dashboard and risk evidence 2026-07-07: Computer Use confirmed the production dashboard opens for the approved operator and shows the saved Aggressive runtime settings. Direct authenticated API checks confirmed `config/current`, `notifications/settings`, and `operations/tick-schedule` return 200. Production risk config includes Alpaca max position `$100.00`, max daily loss `$100.00`, max open positions `5`, slippage `0.005`; Polymarket max position `$25.00`, max daily loss `$50.00`, max open positions `5`, slippage `0.02`.

Notification delivery evidence 2026-07-07: Codex added authenticated `POST /api/notifications/test`, deployed it to production at `56afd7a`, then fixed SES domain-identity sender normalization at `ca3eaf3` after the first production send returned `InvalidParameterValue: Missing final '@domain'` for `SES_IDENTITY_EMAIL=asyncdoc.net`. The rerun returned HTTP `202`, `sent=true`, `attemptRecorded=true`, `recipientCount=1`, `messageIdPresent=true`, `retryable=false`, and production `/health` stayed OK.

Production blocker 2026-07-07: Heavy dashboard endpoints are not ready for live-readiness closure. Direct authenticated checks showed `market-data/latest` returned 200 but took about 24 seconds and returned a large payload; `operations/summary`, `dashboard/realtime-snapshot`, and `dashboard/summary` timed out. ECS replaced backend tasks after `OutOfMemoryError: container killed due to memory usage`; the replacement task recovered and `/health` returned 200, but full readiness remains blocked until the operations/readiness payload path is fixed.

Local fix evidence 2026-07-07: Codex changed the dashboard operations summary so high-volume Polymarket historical import and Alpaca broker history scans are deferred by default and only loaded with `include_history=true`. Dashboard summary and realtime snapshot now use the bounded operations payload, reuse already-fetched market data inside loop observability, and cap dashboard market-data candidate details. Validation passed with `codex-poly-bot/backend/.venv/bin/python -m pytest codex-poly-bot/backend/tests/spec/test_dashboard_api.py -q`, `npm --prefix codex-poly-bot/frontend run test:dashboard-operations`, and `npm --prefix codex-poly-bot/frontend run typecheck`. This item remains open until the fix is deployed and the production endpoints return without OOM.

Production validation evidence 2026-07-07: The first production deployment still OOM-killed the backend when `/api/operations/summary` was requested; ECS stopped task `77cf09caeb3d407a9a8869c5bad58ba0` with exit code `137` and reason `OutOfMemoryError: container killed due to memory usage`. Codex tightened the default operations payload again so scanner, reasoning, strategy consensus, execution, exit, order events, and pipeline runs are also deferred from the default summary unless `include_details=true` is explicitly requested.

Production closure evidence 2026-07-07: The compact operations payload fix was pushed to `develop` at `fed22e7`, deployed to development, then promoted to `main` at `591e67a` and deployed to production. ECR published production backend image tag `591e67a9d261f4263b61e2c3a596dc8f65bc7cc4`; ECS production backend deployment `ecs-svc/5515280985956515027` completed with desired `1`, running `1`, pending `0`, failed `0`; production `/health` returned `{"status":"ok"}` after authenticated dashboard checks. Authenticated production checks returned 200 for `/api/operations/summary` in `0.126s` with scanner, reasoning, strategy consensus, execution, exit, historical import, and broker history deferred; `/api/dashboard/realtime-snapshot` in `18.078s`; `/api/dashboard/summary` in `15.486s`; and `/api/market-data/latest` in `14.257s` with `candidateCount=617` and returned candidate details capped at `50`.

## Phase 5: Ask Codex To Verify

After the credentials are stored, ask Codex:

```text
Confirm the Codex Poly Bot can read the Polymarket US and Alpaca credentials from AWS Secrets Manager, run read-only account and market data checks, confirm production live trading is intentionally enabled, and report any missing setup without placing orders.
```

Expected verification:

- [x] Codex confirms AWS identity and target environment.
- [x] Codex confirms each required secret exists without printing secret values.
- [x] Codex confirms Polymarket US read-only account or balance check succeeds.
- [x] Codex confirms Alpaca paper read-only account check succeeds.
- [x] Codex confirms Alpaca market data check succeeds.
- [x] Codex confirms no live orders were placed.
- [x] Codex confirms production live enablement has explicit operator direction.

## Phase 6: First Live Test Approval

- [ ] Paper and dry-run checks pass.
- [ ] Operator approves a small live test in writing.
- [ ] Only one venue is enabled for the test.
- [ ] Only one model provider is enabled for the test.
- [ ] Live test amount is capped.
- [ ] Rollback owner is identified.
- [ ] Post-test audit events and account balances are reviewed.

Non-order gate smoke evidence 2026-07-07: `codex-poly-bot/backend/.venv/bin/python codex-poly-bot/scripts/polymarket-operational-gates-smoke.py --notional 1.00` passed. It validated the Polymarket entry path, exit path, kill-switch refusal, and notification ledger using fake adapters, with `real_venue_calls_attempted=false` and `real_email_attempted=false`. Live readiness items for real notification delivery, dashboard/API kill switch, and live-test approval remain open.

Alpaca paper and dry-run evidence 2026-07-07: Codex completed a paper-only Alpaca submit/cancel check against `https://paper-api.alpaca.markets` and a live-account dry-run check against read-only `https://api.alpaca.markets` calls. Paper order status was `accepted`, cancel returned HTTP `204`, and open paper orders stayed at `0`. The live account returned `ACTIVE`, unblocked, open order count `0`, and the local dry-run execution path returned `simulated` with no broker submit call. The broader paper/dry-run readiness checkbox remains open until the production dashboard OOM fix is deployed and the production dry-run/readiness endpoints are rechecked.

Production dry-run blocker 2026-07-07: Authenticated production `POST /api/operations/manual-run` with `mode=full_dry_run` did not place live orders, but it is not ready for live-readiness closure. The first attempt returned a non-JSON gateway response and OOM-killed backend task `d6d0ab9f99b247b29dd8cd6a06a5b4e0` with exit code `137`. Codex deployed bounded non-live manual-run provider scope at `2fc82ef`, capping Polymarket market-data limit to `10` and Alpaca symbols to `20`, but the retry still returned HTTP `504` after about `60s` and OOM-killed backend task `267efebb1ca54a529ee9df07ad076f93` with exit code `137`. `/health` recovered after ECS replaced the task. Keep this item open until manual dry-runs run outside the request-serving task, use a smaller worker-safe scope, or the task memory/concurrency model is changed and production dry-run returns successfully.
