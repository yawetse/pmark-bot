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
- [ ] Create a developer API key.
- [ ] Store the API key ID in the password manager or secure credential inventory.
- [ ] Store the API secret in the password manager or secure credential inventory.
- [ ] Confirm the secret was copied before closing the one-time display dialog.
- [ ] Confirm whether the API uses production or sandbox endpoints for the first live verification.

## AWS Secrets Manager

- [ ] Add the development Polymarket US API credentials to AWS Secrets Manager under `/codex-poly-bot/development/...`.
- [ ] Add the production Polymarket US API credentials to AWS Secrets Manager under `/codex-poly-bot/production/...` only when ready for production.
- [ ] Confirm no Polymarket credentials are stored in GitHub secrets, `.env`, shell history, screenshots, or markdown files.
- [ ] Confirm secret names match the bot's current credential-loading contract before enabling live orders.

## Bot Enablement Gates

- [ ] Keep `LIVE_ENABLED=false`.
- [ ] Keep `POLYMARKET_US_ENABLED=false`.
- [ ] Ask Codex to verify read-only account, balance, and market data access after credentials are stored.
- [ ] Run dry-run order checks before enabling live Polymarket orders.
- [ ] Confirm kill switch and notification delivery before enabling live orders.

## Reference

- Polymarket US API docs: https://docs.polymarket.us
