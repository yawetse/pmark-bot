# Live Trading Checklist

REQ: REQ-WAL-001, REQ-WAL-002, REQ-WAL-003, REQ-WAL-006, REQ-EXE-001, REQ-EXE-014, REQ-EXE-017, REQ-OBS-005

Production live trading is intentionally enabled. Live-order test evidence still remains incomplete for any venue until every item below has evidence in the release record.

The dashboard `Full live-gated` manual run mode does not bypass this checklist. It only allows the pipeline to use the configured live setting after credentials, risk limits, persistence, venue status, and the kill switch allow it.

Implementation status: the runtime can now attach concrete Alpaca and Polymarket US submitters when live mode, venue flags, active account status, and required credentials are present. Missing adapters or credentials still produce refused intents instead of venue calls.

## Credentials and Accounts

- Confirm the target environment is correct, `development` or `production`.
- Confirm each venue, account mode, and model provider has separate wallet or brokerage credentials.
- Confirm Polymarket wallet setup is complete for the selected account mode.
- Confirm Alpaca paper or live account setup is complete for the selected account mode.
- Confirm deployed secrets exist only in AWS Secrets Manager under `/codex-poly-bot/{environment}/...`.
- Confirm production runtime exposes separate credentials for `polymarket_us / openai`, `polymarket_us / claude`, `alpaca / openai`, and `alpaca / claude` through ECS secret injection.
- For Polymarket US, confirm each provider has `POLYMARKET_{OPENAI|CLAUDE}_KEY_ID` plus either `POLYMARKET_{OPENAI|CLAUDE}_SECRET_KEY` or `POLYMARKET_{OPENAI|CLAUDE}_PRIVATE_KEY`.
- For Alpaca, confirm each provider has `ALPACA_{OPENAI|CLAUDE}_KEY_ID` and `ALPACA_{OPENAI|CLAUDE}_SECRET_KEY`.

## Dry-Run Evidence

- Run `scripts/polymarket-readonly-smoke.py --environment production` to confirm Polymarket US account and market read access without attempting order operations.
- Run `scripts/polymarket-operational-gates-smoke.py --notional 1.00` to prove Polymarket entry, exit, kill-switch, and notification wiring without a real venue call or real email.
- Run the trading loop in dry-run mode with the target venue and provider.
- Confirm simulated orders are recorded and no venue submission method is called.
- Confirm recent audit events and health indicators are visible in the dashboard.
- Confirm account balance, buying power, and market data freshness checks pass.
- Run a `Full live-gated` manual run with intentionally tiny risk caps and confirm the run either submits the expected tiny order or records a specific refusal reason. Do not treat `accepted` as enough evidence.

## Live Enablement Controls

- Require final approval before setting `LIVE_ENABLED=true`. Production approval was recorded on 2026-07-02, and production currently runs with `LIVE_ENABLED=true`.
- Enable only the intended venue flag, such as `POLYMARKET_US_ENABLED=true` or `ALPACA_ENABLED=true`; production currently has both intended venue flags enabled.
- Confirm concrete live venue submitters are attached for each intended venue and no `LIVE_SUBMITTER_NOT_CONFIGURED` refusal is present in the dry-run/live-gated evidence.
- Confirm no `LIVE_EXIT_SUBMITTER_NOT_CONFIGURED` refusal is present when open positions cross exit triggers.
- Confirm risk limits for max position size, max daily loss, max open positions, Kelly cap, and market order slippage.
- Confirm dashboard auth allows only approved operators.
- Confirm SES identity is verified and notification recipients are approved.
- Confirm the kill switch can be activated from the dashboard or API.
- Confirm the kill switch disables live trading for all venues and providers.

## Active Stock Day-Trader Profile

`active_stock_day_trader` is the default bootstrap profile. It selects and enables Alpaca, but starts in paper mode with live trading off. Moving the profile to a live account remains a separate operator decision.

| Control | Default |
| --- | --- |
| Trading loop | Every 15 minutes |
| Minimum stock quote liquidity | 0.5 |
| Stock scanner maximum spread | $1.00 |
| Stock confidence | 54% minimum |
| Stock model edge | 1.5% minimum |
| Model candidates | 4 top candidates per provider per run |
| OpenAI and Claude spend | $20 each over a rolling 24-hour window |
| Profit target | 2% |
| Stop loss | 1% |
| Trailing stop | 1% |
| Maximum hold | 6 hours |
| Trading session | Regular market hours only |
| End-of-day close | 15 minutes before the regular close |
| Maximum stock order | $100 |
| Maximum daily stock loss | $100 |
| Maximum open stock positions | 5 |
| Maximum allocation per symbol | 10% |
| Maximum estimated stock slippage | 0.5% of share price |

The stock scanner also uses lower signal thresholds for momentum, mean reversion, gaps, volatility, and unusual volume. The execution gate still requires fresh data, model approval, available buying power, acceptable percentage slippage, configured credentials, and risk capacity. The profile can produce more qualified attempts, but it does not guarantee continuous orders or profit.

Existing saved settings remain in force until an operator saves a new config version with these values. Record that config version in the release evidence before enabling live submissions.

For an existing config, use **Settings > Stock trading profile > Review and apply**. The action saves the complete profile as one audited version. It does not change `live_enabled` or `alpaca.account_mode`; the confirmation dialog shows both current values before the save.

## Final Approval

Record the operator, environment, venue, model provider, account mode, risk config version, dry-run evidence, and rollback owner before running any order-submitting live test.

## Venue Submitter Contract

- Alpaca entries submit market buy orders to `/v2/orders` using notional sizing and deterministic client order IDs.
- Alpaca exits submit market sell orders to `/v2/orders` using the tracked open quantity.
- Polymarket entries submit through the official Polymarket US SDK `orders.create` method.
- Polymarket exits submit through the official Polymarket US SDK `orders.close_position` method with configured market-order slippage tolerance.
