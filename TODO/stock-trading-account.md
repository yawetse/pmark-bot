# TODO: Stock Trading Account

Purpose: create the brokerage and market data setup needed before the bot can place live stock-market orders.

Preferred first broker for this bot: Alpaca, because the current codebase already has an Alpaca venue path.

Do not paste API keys, brokerage secrets, bank details, or account numbers into this file.

## Alpaca Account Setup

- [x] Create an Alpaca Trading API account.
- [x] Complete brokerage identity verification.
- [x] Enable multi-factor authentication.
- [x] Create or confirm the paper trading account.
- [x] Create or confirm the live brokerage account.
- [ ] Link the funding bank account.
- [x] Fund the live account with the starting live-test amount.
- [ ] Confirm whether the account is cash or margin.
- [ ] Confirm whether short selling, extended-hours trading, options, and margin are disabled or approved intentionally.

## API Credentials

- [x] Generate paper trading API credentials.
- [x] Generate live trading API credentials.
- [x] Store the paper API key ID and secret in the password manager or secure credential inventory.
- [x] Store the live API key ID and secret in the password manager or secure credential inventory.
- [x] Record the paper base URL and live base URL.
- [x] Confirm paper and live credentials are not mixed.

## Market Data

- [x] Start with the free/basic IEX market data feed for paper testing.
- [x] Decide whether the strategy needs full SIP market data.
- [x] Subscribe to Alpaca Algo Trader Plus only if full U.S. stock market coverage is required.
- [x] Record the selected market data feed: `iex` or `sip`.

## AWS Secrets Manager

- [x] Add paper Alpaca credentials to AWS Secrets Manager under `/codex-poly-bot/development/...`.
- [x] Add live Alpaca credentials to AWS Secrets Manager under `/codex-poly-bot/production/...` only when ready for production.
- [x] Confirm no Alpaca credentials are stored in GitHub secrets, `.env`, shell history, screenshots, or markdown files.
- [x] Confirm secret names match the bot's current credential-loading contract before enabling live orders.

Evidence 2026-07-02: AWS Secrets Manager contains `/codex-poly-bot/development/alpaca/key-id`, `/codex-poly-bot/development/alpaca/secret-key`, and matching production names. ECS injects `ALPACA_KEY_ID` and `ALPACA_SECRET_KEY` into the backend task definition by name only.

Alpaca live account evidence 2026-07-03: operator confirmed the live Alpaca account is created and funded. Screenshot evidence showed `$100.00` portfolio value, `$100.00` buying power, `$100.00` cash, and no open positions. Account numbers and credentials are intentionally not recorded here.

Read-only Alpaca verification 2026-07-03: Codex retrieved Alpaca credentials from AWS Secrets Manager without printing values, confirmed the paper account is `ACTIVE`, confirmed IEX market data returned a SPY quote, confirmed the live account is `ACTIVE` and unblocked, confirmed recent live order count was `0`, and attempted no order operations.

Alpaca validation 2026-07-07: Computer Use confirmed Alpaca MFA is enabled with authenticator MFA marked secure and required. Safari showed no connected ACH or wire funding account, so the bank-link item remains open even though a $100 wire deposit completed on 2026-06-24. Alpaca Plans & Features showed Market Data subscription status `Basic`; the production runtime uses `ALPACA_DATA_FEED=iex`, so SIP / Algo Trader Plus is not required for the current tiny-risk rollout. Codex scrubbed local Alpaca values from `.env.production`, `.env.local`, and `.env.development`; an exact-value scan across 10 AWS-stored Alpaca/Polymarket trading secrets, 208 repo text/history files, and shell history returned no matches. GitHub secret names contain no Alpaca or Polymarket trading keys.

Live Alpaca read-only verification 2026-07-07: Codex retrieved paper and live Alpaca credentials from AWS Secrets Manager without printing values. Paper and live accounts returned `ACTIVE`, unblocked, cash and buying power present, and open order count `0`. The live Trading API returned `shorting_enabled=false`, no options levels, and no order operations attempted. Safari account configuration still showed a shorting toggle enabled, so restriction confirmation remains open until the dashboard setting is intentionally turned off or approved.

## Bot Enablement Gates

- [x] Production `LIVE_ENABLED=true` is intentional operator direction.
- [x] Production `ALPACA_ENABLED=true` is intentional operator direction.
- [x] Ask Codex to verify read-only paper account, buying power, positions, and market data after credentials are stored.
- [x] Run paper order checks before any live stock order.
- [x] Run dry-run live-account checks before enabling live stock orders.
- [ ] Run a `Full live-gated` check with tiny risk caps and confirm Alpaca entries submit as notional market buys only when expected.
- [ ] Run an exit-path check with a tiny tracked long position and confirm Alpaca exits submit as market sells for the tracked quantity.
- [ ] Confirm kill switch and notification delivery before enabling live orders.

Paper order evidence 2026-07-07: Codex fetched development Alpaca paper credentials from AWS Secrets Manager without printing values, used only `https://paper-api.alpaca.markets`, submitted a non-marketable SPY limit buy for quantity `1` at `$0.01`, and immediately canceled it. Alpaca returned paper account `ACTIVE`, market closed with next open `2026-07-08T09:30:00-04:00`, order status `accepted`, cancel HTTP `204`, and open orders remained `0` before and after. No live Alpaca endpoint was used.

Live-account dry-run evidence 2026-07-07: Codex fetched production Alpaca live credentials from AWS Secrets Manager without printing values and used read-only Trading API calls against `https://api.alpaca.markets`. The account returned `ACTIVE`, `trading_blocked=false`, `account_blocked=false`, open order count `0`, market closed, and next open `2026-07-08T09:30:00-04:00`. The local live-account dry-run execution path returned `simulated`, recorded the dry-run order, `broker_submitted=false`, fake submit calls `0`, and no live order endpoint was called.

## Reference

- Alpaca docs: https://docs.alpaca.markets
