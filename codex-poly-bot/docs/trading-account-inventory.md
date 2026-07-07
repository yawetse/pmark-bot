# Trading Account Inventory

Do not store API keys, private keys, wallet seed phrases, bank details, or account numbers in this file.

## Polymarket US

- Environment: production
- Non-secret username: `goofyrobin3284`
- Account state: operator confirmed Polymarket US is set for live trading on 2026-07-02.
- Funding evidence: operator-provided Polymarket US app screenshot on 2026-07-02 shows `$120 cash`.
- Positions at evidence time: no positions.
- Credential storage: AWS Secrets Manager under `/codex-poly-bot/{environment}/polymarket/...`.
- Read-only API evidence: `scripts/polymarket-readonly-smoke.py` authenticated with AWS Secrets Manager values and completed account and market reads without order operations.

## Alpaca

- Environment: production
- Account state: operator confirmed the live Alpaca brokerage account is created and funded.
- Funding evidence: operator-provided Alpaca dashboard screenshot showed `$100.00` portfolio value, `$100.00` buying power, and `$100.00` cash. Transfer history later showed one completed `$100` wire deposit on 2026-06-24.
- Positions and orders at evidence time: no open positions and no open orders.
- MFA: enabled with authenticator MFA marked secure and required.
- Market data: Basic subscription with runtime feed `iex`; SIP / Algo Trader Plus is not required for the current tiny-risk rollout.
- Credential storage: AWS Secrets Manager under `/codex-poly-bot/{environment}/alpaca/...`.
- Read-only API evidence: AWS-stored paper and live Alpaca credentials authenticated successfully, returned `ACTIVE` accounts, cash and buying power present, and no order operations attempted.
- Open setup note: Safari showed no connected ACH or wire funding account. The live Trading API returned shorting disabled and no options levels, while the Alpaca dashboard configuration page still showed the shorting toggle enabled; this restriction setting needs operator confirmation.
