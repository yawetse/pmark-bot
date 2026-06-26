# Live Trading Checklist

REQ: REQ-WAL-001, REQ-WAL-002, REQ-WAL-003, REQ-WAL-006, REQ-EXE-001, REQ-EXE-014, REQ-EXE-017, REQ-OBS-005

Live trading remains blocked for any venue until every item below has evidence in the release record.

The dashboard `Full live-gated` manual run mode does not bypass this checklist. It only allows the pipeline to use the configured live setting after credentials, risk limits, persistence, venue status, and the kill switch allow it.

Implementation status: the runtime can now attach concrete Alpaca and Polymarket US submitters when live mode, venue flags, active account status, and required credentials are present. Missing adapters or credentials still produce refused intents instead of venue calls.

## Credentials and Accounts

- Confirm the target environment is correct, `development` or `production`.
- Confirm each venue, account mode, and model provider has separate wallet or brokerage credentials.
- Confirm Polymarket wallet setup is complete for the selected account mode.
- Confirm Alpaca paper or live account setup is complete for the selected account mode.
- Confirm deployed secrets exist only in AWS Secrets Manager under `/codex-poly-bot/{environment}/...`.
- Confirm production runtime exposes `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`, `POLYMARKET_KEY_ID`, and either `POLYMARKET_SECRET_KEY` or `POLYMARKET_PRIVATE_KEY` through ECS secret injection.

## Dry-Run Evidence

- Run the trading loop in dry-run mode with the target venue and provider.
- Confirm simulated orders are recorded and no venue submission method is called.
- Confirm recent audit events and health indicators are visible in the dashboard.
- Confirm account balance, buying power, and market data freshness checks pass.
- Run a `Full live-gated` manual run with intentionally tiny risk caps and confirm the run either submits the expected tiny order or records a specific refusal reason. Do not treat `accepted` as enough evidence.

## Live Enablement Controls

- Keep `LIVE_ENABLED=false` until final approval.
- Enable only the intended venue flag, such as `POLYMARKET_US_ENABLED=true` or `ALPACA_ENABLED=true`.
- Confirm concrete live venue submitters are attached for each intended venue and no `LIVE_SUBMITTER_NOT_CONFIGURED` refusal is present in the dry-run/live-gated evidence.
- Confirm no `LIVE_EXIT_SUBMITTER_NOT_CONFIGURED` refusal is present when open positions cross exit triggers.
- Confirm risk limits for max position size, max daily loss, max open positions, Kelly cap, and market order slippage.
- Confirm dashboard auth allows only approved operators.
- Confirm SES identity is verified and notification recipients are approved.
- Confirm the kill switch can be activated from the dashboard or API.
- Confirm the kill switch disables live trading for all venues and providers.

## Final Approval

Record the operator, environment, venue, model provider, account mode, risk config version, dry-run evidence, and rollback owner before setting live mode.

## Venue Submitter Contract

- Alpaca entries submit market buy orders to `/v2/orders` using notional sizing and deterministic client order IDs.
- Alpaca exits submit market sell orders to `/v2/orders` using the tracked open quantity.
- Polymarket entries submit through the official Polymarket US SDK `orders.create` method.
- Polymarket exits submit through the official Polymarket US SDK `orders.close_position` method with configured market-order slippage tolerance.
