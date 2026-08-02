# Wallets and Accounts

REQ: REQ-WAL-001, REQ-WAL-002, REQ-WAL-003, REQ-WAL-004, REQ-WAL-006, REQ-EXE-017, REQ-KAL-004, REQ-KAL-012

Live trading requires separate credentials by environment, venue, and model provider. A development wallet or paper brokerage account must not share private key material with production.

## Local Development

Local development may read private keys and API credentials from gitignored `.env` files. Keep local values non-production. Tests and dry-runs must continue to pass with empty credential values.

Use `scripts/sync-env-files.py` to normalize `.env.local`, `.env.development`, and `.env.production` without printing credential values. The script preserves existing values by default and can fill missing values from AWS Secrets Manager after `aws login` succeeds.

## Deployed Environments

Deployed environments must read private keys, brokerage credentials, LLM API keys, dashboard secrets, and SES settings from AWS Secrets Manager. Secret names use this prefix:

```text
/codex-poly-bot/{environment}/
```

Examples:

```text
/codex-poly-bot/development/polymarket_us/openai/wallet
/codex-poly-bot/development/polymarket_us/claude/wallet
/codex-poly-bot/production/alpaca/openai/api-key
/codex-poly-bot/production/alpaca/claude/api-key
/codex-poly-bot/production/kalshi/market-data/key-id
/codex-poly-bot/production/kalshi/openai/private-key
/codex-poly-bot/production/kalshi/claude/private-key
```

The deployed backend reads separate runtime variables for the four live account slots:

```text
POLYMARKET_OPENAI_KEY_ID
POLYMARKET_OPENAI_SECRET_KEY
POLYMARKET_OPENAI_PRIVATE_KEY
POLYMARKET_CLAUDE_KEY_ID
POLYMARKET_CLAUDE_SECRET_KEY
POLYMARKET_CLAUDE_PRIVATE_KEY
KALSHI_MARKET_DATA_KEY_ID
KALSHI_MARKET_DATA_PRIVATE_KEY
KALSHI_OPENAI_KEY_ID
KALSHI_OPENAI_PRIVATE_KEY
KALSHI_CLAUDE_KEY_ID
KALSHI_CLAUDE_PRIVATE_KEY
ALPACA_OPENAI_KEY_ID
ALPACA_OPENAI_SECRET_KEY
ALPACA_CLAUDE_KEY_ID
ALPACA_CLAUDE_SECRET_KEY
```

These values let OpenAI and Claude use separate Polymarket US wallets, Kalshi accounts, and Alpaca accounts, so comparison metrics are not mixed across models. Kalshi also uses a separate read credential for authenticated batch order books. The runtime verifies that the two provider credentials report different authenticated API-key membership fingerprints before allowing new exposure. The dashboard displays only status, variable names, and secret references. It must not display private keys, API secrets, tokens, seed phrases, or raw `.env` values.

## Live Order Gate

Before a live venue call, the execution service must verify that the required wallet secret, brokerage credential, and API credential are present for the environment, venue, account mode, and model provider. Missing or invalid credentials must refuse the order and record the refusal reason.
