# Live Trading Checklist

REQ: REQ-WAL-001, REQ-WAL-002, REQ-WAL-003, REQ-WAL-006, REQ-EXE-001, REQ-EXE-014, REQ-EXE-017, REQ-OBS-005

Live trading remains blocked until every item below has evidence in the release record.

The dashboard `Full live-gated` manual run mode does not bypass this checklist. It only allows the pipeline to use the configured live setting after credentials, risk limits, persistence, venue status, and the kill switch allow it.

## Credentials and Accounts

- Confirm the target environment is correct, `development` or `production`.
- Confirm each venue, account mode, and model provider has separate wallet or brokerage credentials.
- Confirm Polymarket wallet setup is complete for the selected account mode.
- Confirm Alpaca paper or live account setup is complete for the selected account mode.
- Confirm deployed secrets exist only in AWS Secrets Manager under `/codex-poly-bot/{environment}/...`.

## Dry-Run Evidence

- Run the trading loop in dry-run mode with the target venue and provider.
- Confirm simulated orders are recorded and no venue submission method is called.
- Confirm recent audit events and health indicators are visible in the dashboard.
- Confirm account balance, buying power, and market data freshness checks pass.

## Live Enablement Controls

- Keep `LIVE_ENABLED=false` until final approval.
- Enable only the intended venue flag, such as `POLYMARKET_US_ENABLED=true` or `ALPACA_ENABLED=true`.
- Confirm concrete live venue submitters are attached for each intended venue and no `LIVE_SUBMITTER_NOT_CONFIGURED` refusal is present in the dry-run/live-gated evidence.
- Confirm risk limits for max position size, max daily loss, max open positions, Kelly cap, and market order slippage.
- Confirm dashboard auth allows only approved operators.
- Confirm SES identity is verified and notification recipients are approved.
- Confirm the kill switch can be activated from the dashboard or API.
- Confirm the kill switch disables live trading for all venues and providers.

## Final Approval

Record the operator, environment, venue, model provider, account mode, risk config version, dry-run evidence, and rollback owner before setting live mode.
