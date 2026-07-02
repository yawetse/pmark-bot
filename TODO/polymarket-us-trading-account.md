# TODO: Polymarket US Trading Account

Purpose: create the regulated Polymarket US account and API setup needed before the bot can place live prediction-market orders.

Do not paste API keys, private keys, seed phrases, or account secrets into this file.

## Account Setup

- [ ] Download the Polymarket US app.
- [ ] Create the Polymarket US account using the sign-in method that will also be used for the developer portal.
- [ ] Complete identity verification and wait for trading approval.
- [ ] Confirm the account is approved for live trading in the app.
- [ ] Set up the funding method supported by the app.
- [ ] Fund the account with the starting live-test amount.
- [ ] Record the non-secret account identifier or username in the credential inventory, if Polymarket US exposes one.

## API Setup

- [ ] Open `polymarket.us/developer`.
- [ ] Sign in with the same method used in the Polymarket US app.
- [x] Create a developer API key.
- [x] Store the API key ID in the password manager or secure credential inventory.
- [x] Store the API secret in the password manager or secure credential inventory.
- [x] Confirm the stored secret works after the one-time display dialog.
- [x] Confirm whether the API uses production or sandbox endpoints for the first live verification.

Evidence 2026-07-02: `scripts/polymarket-readonly-smoke.py` authenticated through the official Polymarket US adapter for both production and development using AWS Secrets Manager values only. It used `https://api.polymarket.us` and `https://gateway.polymarket.us`, called only `account.balances` and `markets.list`, returned five markets per environment, and attempted no order operations.

## AWS Secrets Manager

- [x] Add the development Polymarket US API credentials to AWS Secrets Manager under `/codex-poly-bot/development/...`.
- [x] Add the production Polymarket US API credentials to AWS Secrets Manager under `/codex-poly-bot/production/...` only when ready for production.
- [x] Confirm no Polymarket credentials are stored in GitHub secrets, `.env`, shell history, screenshots, or markdown files.
- [x] Confirm secret names match the bot's current credential-loading contract before enabling live orders.

Evidence 2026-07-02: AWS Secrets Manager contains `/codex-poly-bot/development/polymarket/key-id`, `/codex-poly-bot/development/polymarket/secret-key`, `/codex-poly-bot/development/polymarket/private-key`, and matching production names. ECS injects `POLYMARKET_KEY_ID`, `POLYMARKET_SECRET_KEY`, and `POLYMARKET_PRIVATE_KEY` into the backend task definition by name only.

Hygiene evidence 2026-07-02: GitHub repo and environment secret names contain no Polymarket credentials. Local `.env.local`, `.env.development`, and `.env.production` Polymarket credential values were scrubbed. An exact-value scan of the repo, local env files, shell history, and known Codex Poly Bot verification screenshot directories loaded six Polymarket secret values from AWS and found zero matches outside AWS Secrets Manager.

## Bot Enablement Gates

- [x] Production `LIVE_ENABLED=true` is intentional operator direction.
- [x] Production `POLYMARKET_US_ENABLED=true` is intentional operator direction.
- [x] Ask Codex to verify read-only account, balance, and market data access after credentials are stored.
- [x] Run dry-run order checks before enabling live Polymarket orders.
- [ ] Run a `Full live-gated` check with tiny risk caps and confirm Polymarket entries use the official SDK `orders.create` path only when expected.
- [ ] Run an exit-path check with a tiny open position and confirm Polymarket exits use the official SDK `orders.close_position` path.
- [ ] Confirm kill switch and notification delivery before enabling live orders.

Read-only and dry-run evidence 2026-07-02: production and development smoke checks returned `ok=true`, `read_only_account_check.ok=true`, `read_only_market_check.ok=true`, `market_count=5`, and `order_operations_attempted=[]`. Focused backend tests passed: `tests/spec/test_venue_integration.py` with 21 tests and `tests/spec/test_lifecycle_service.py` with 8 tests.

## Reference

- Polymarket US API docs: https://docs.polymarket.us
