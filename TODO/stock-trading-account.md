# TODO: Stock Trading Account

Purpose: create the brokerage and market data setup needed before the bot can place live stock-market orders.

Preferred first broker for this bot: Alpaca, because the current codebase already has an Alpaca venue path.

Do not paste API keys, brokerage secrets, bank details, or account numbers into this file.

## Alpaca Account Setup

- [ ] Create an Alpaca Trading API account.
- [ ] Complete brokerage identity verification.
- [ ] Enable multi-factor authentication.
- [x] Create or confirm the paper trading account.
- [ ] Create or confirm the live brokerage account.
- [ ] Link the funding bank account.
- [ ] Fund the live account with the starting live-test amount.
- [ ] Confirm whether the account is cash or margin.
- [ ] Confirm whether short selling, extended-hours trading, options, and margin are disabled or approved intentionally.

## API Credentials

- [x] Generate paper trading API credentials.
- [ ] Generate live trading API credentials.
- [ ] Store the paper API key ID and secret in the password manager or secure credential inventory.
- [ ] Store the live API key ID and secret in the password manager or secure credential inventory.
- [x] Record the paper base URL and live base URL.
- [x] Confirm paper and live credentials are not mixed.

## Market Data

- [x] Start with the free/basic IEX market data feed for paper testing.
- [ ] Decide whether the strategy needs full SIP market data.
- [ ] Subscribe to Alpaca Algo Trader Plus only if full U.S. stock market coverage is required.
- [x] Record the selected market data feed: `iex` or `sip`.

## AWS Secrets Manager

- [ ] Add paper Alpaca credentials to AWS Secrets Manager under `/codex-poly-bot/development/...`.
- [ ] Add live Alpaca credentials to AWS Secrets Manager under `/codex-poly-bot/production/...` only when ready for production.
- [ ] Confirm no Alpaca credentials are stored in GitHub secrets, `.env`, shell history, screenshots, or markdown files.
- [ ] Confirm secret names match the bot's current credential-loading contract before enabling live orders.

## Bot Enablement Gates

- [ ] Keep `LIVE_ENABLED=false`.
- [ ] Keep `ALPACA_ENABLED=false`.
- [x] Ask Codex to verify read-only paper account, buying power, positions, and market data after credentials are stored.
- [ ] Run paper order checks before any live stock order.
- [ ] Run dry-run live-account checks before enabling live stock orders.
- [ ] Run a `Full live-gated` check with tiny risk caps and confirm Alpaca entries submit as notional market buys only when expected.
- [ ] Run an exit-path check with a tiny tracked long position and confirm Alpaca exits submit as market sells for the tracked quantity.
- [ ] Confirm kill switch and notification delivery before enabling live orders.

## Reference

- Alpaca docs: https://docs.alpaca.markets
