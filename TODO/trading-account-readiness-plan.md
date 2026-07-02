# Trading Account Readiness Plan

Purpose: track the account, credential, and verification work needed before asking Codex to confirm live trading connectivity.

Do not paste secrets into this plan. Check off items only after the action is complete and the evidence is available outside this file.

## Phase 1: Accounts

- [x] Polymarket US account created.
- [ ] Polymarket US identity verification approved.
- [ ] Polymarket US account funded.
- [ ] Alpaca account created.
- [ ] Alpaca brokerage identity verification approved.
- [ ] Alpaca paper trading account available.
- [ ] Alpaca live brokerage account funded with the starting live-test amount.

## Phase 2: API Credentials

- [x] Polymarket US developer API key created.
- [x] Polymarket US API key ID stored outside the repo.
- [x] Polymarket US API secret stored outside the repo.
- [ ] Alpaca paper API key ID and secret created.
- [ ] Alpaca live API key ID and secret created.
- [ ] Alpaca paper and live base URLs recorded outside the repo.
- [ ] Market data feed selected for Alpaca: `iex` or `sip`.

## Phase 3: AWS Secret Storage

- [x] Development Polymarket US secrets created in AWS Secrets Manager.
- [x] Development Alpaca paper secrets created in AWS Secrets Manager.
- [x] Production Polymarket US secrets created in AWS Secrets Manager, if production is in scope.
- [x] Production Alpaca live secrets created in AWS Secrets Manager, if production is in scope.
- [x] AWS secret names match the bot's credential-loading contract.
- [ ] No trading secrets are present in GitHub secrets, markdown files, `.env`, screenshots, or terminal history.

Evidence 2026-07-02: AWS identity `arn:aws:iam::506304330252:user/yawetse` confirmed access to `us-east-1`. Secrets Manager contains the expected development and production Polymarket, Alpaca, OpenAI, Anthropic, and SigNoz secret names under `/codex-poly-bot/{environment}/...`; ECS backend task definitions inject only the expected secret environment names, without printing secret values.

Polymarket evidence 2026-07-02: `scripts/polymarket-readonly-smoke.py` used AWS Secrets Manager values to authenticate against Polymarket US in development and production, returned successful read-only account and market checks, and attempted no order operations. Local Polymarket credential values were removed from `.env.local`, `.env.development`, and `.env.production`.

## Phase 4: Bot Safety Gates

- [x] Production `LIVE_ENABLED=true` confirmed as intentional operator direction.
- [x] Production `POLYMARKET_US_ENABLED=true` confirmed as intentional operator direction.
- [x] Production `ALPACA_ENABLED=true` confirmed as intentional operator direction.
- [ ] Dashboard authentication works for the approved operator.
- [ ] Notification delivery works.
- [ ] Kill switch works from the dashboard or API.
- [ ] Risk limits are set for max position size, max daily loss, max open positions, and slippage.

Evidence 2026-07-02: Operator confirmed live trading should be enabled. AWS production backend task definition `codex-poly-bot-production-backend:15` has `LIVE_ENABLED=true`, `TRADING_ACCOUNT_MODE=live`, `POLYMARKET_US_ENABLED=true`, `ALPACA_ENABLED=true`, and `ALPACA_ACCOUNT_STATUS=active`.

## Phase 5: Ask Codex To Verify

After the credentials are stored, ask Codex:

```text
Confirm the Codex Poly Bot can read the Polymarket US and Alpaca credentials from AWS Secrets Manager, run read-only account and market data checks, confirm production live trading is intentionally enabled, and report any missing setup without placing orders.
```

Expected verification:

- [x] Codex confirms AWS identity and target environment.
- [x] Codex confirms each required secret exists without printing secret values.
- [x] Codex confirms Polymarket US read-only account or balance check succeeds.
- [ ] Codex confirms Alpaca paper read-only account check succeeds.
- [ ] Codex confirms Alpaca market data check succeeds.
- [ ] Codex confirms no live orders were placed.
- [x] Codex confirms production live enablement has explicit operator direction.

## Phase 6: First Live Test Approval

- [ ] Paper and dry-run checks pass.
- [ ] Operator approves a small live test in writing.
- [ ] Only one venue is enabled for the test.
- [ ] Only one model provider is enabled for the test.
- [ ] Live test amount is capped.
- [ ] Rollback owner is identified.
- [ ] Post-test audit events and account balances are reviewed.
