# Trading Account Readiness Plan

Purpose: track the account, credential, and verification work needed before asking Codex to confirm live trading connectivity.

Do not paste secrets into this plan. Check off items only after the action is complete and the evidence is available outside this file.

## Phase 1: Accounts

- [ ] Polymarket US account created.
- [ ] Polymarket US identity verification approved.
- [ ] Polymarket US account funded.
- [ ] Alpaca account created.
- [ ] Alpaca brokerage identity verification approved.
- [ ] Alpaca paper trading account available.
- [ ] Alpaca live brokerage account funded with the starting live-test amount.

## Phase 2: API Credentials

- [ ] Polymarket US developer API key created.
- [ ] Polymarket US API key ID stored outside the repo.
- [ ] Polymarket US API secret stored outside the repo.
- [ ] Alpaca paper API key ID and secret created.
- [ ] Alpaca live API key ID and secret created.
- [ ] Alpaca paper and live base URLs recorded outside the repo.
- [ ] Market data feed selected for Alpaca: `iex` or `sip`.

## Phase 3: AWS Secret Storage

- [ ] Development Polymarket US secrets created in AWS Secrets Manager.
- [ ] Development Alpaca paper secrets created in AWS Secrets Manager.
- [ ] Production Polymarket US secrets created in AWS Secrets Manager, if production is in scope.
- [ ] Production Alpaca live secrets created in AWS Secrets Manager, if production is in scope.
- [ ] AWS secret names match the bot's credential-loading contract.
- [ ] No trading secrets are present in GitHub secrets, markdown files, `.env`, screenshots, or terminal history.

## Phase 4: Bot Safety Gates

- [ ] `LIVE_ENABLED=false` confirmed before connectivity checks.
- [ ] `POLYMARKET_US_ENABLED=false` confirmed before connectivity checks.
- [ ] `ALPACA_ENABLED=false` confirmed before connectivity checks.
- [ ] Dashboard authentication works for the approved operator.
- [ ] Notification delivery works.
- [ ] Kill switch works from the dashboard or API.
- [ ] Risk limits are set for max position size, max daily loss, max open positions, and slippage.

## Phase 5: Ask Codex To Verify

After the credentials are stored, ask Codex:

```text
Confirm the Codex Poly Bot can read the Polymarket US and Alpaca credentials from AWS Secrets Manager, run read-only account and market data checks, keep live trading disabled, and report any missing setup without placing orders.
```

Expected verification:

- [ ] Codex confirms AWS identity and target environment.
- [ ] Codex confirms each required secret exists without printing secret values.
- [ ] Codex confirms Polymarket US read-only account or balance check succeeds.
- [ ] Codex confirms Alpaca paper read-only account check succeeds.
- [ ] Codex confirms Alpaca market data check succeeds.
- [ ] Codex confirms no live orders were placed.
- [ ] Codex confirms live enablement remains blocked until explicit approval.

## Phase 6: First Live Test Approval

- [ ] Paper and dry-run checks pass.
- [ ] Operator approves a small live test in writing.
- [ ] Only one venue is enabled for the test.
- [ ] Only one model provider is enabled for the test.
- [ ] Live test amount is capped.
- [ ] Rollback owner is identified.
- [ ] Post-test audit events and account balances are reviewed.
