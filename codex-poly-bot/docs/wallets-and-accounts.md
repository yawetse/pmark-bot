# Wallets and Accounts

REQ: REQ-WAL-001, REQ-WAL-002, REQ-WAL-003, REQ-WAL-004, REQ-WAL-006, REQ-EXE-017

Live trading requires separate credentials by environment, venue, and model provider. A development wallet or paper brokerage account must not share private key material with production.

## Local Development

Local development may read private keys and API credentials from gitignored `.env` files. Keep local values non-production. Tests and dry-runs must continue to pass with empty credential values.

## Deployed Environments

Deployed environments must read private keys, brokerage credentials, LLM API keys, dashboard secrets, and SES settings from AWS Secrets Manager. Secret names use this prefix:

```text
/codex-poly-bot/{environment}/
```

Examples:

```text
/codex-poly-bot/development/polymarket/openai/private-key
/codex-poly-bot/production/alpaca/anthropic/api-key
```

## Live Order Gate

Before a live venue call, the execution service must verify that the required wallet secret, brokerage credential, and API credential are present for the environment, venue, account mode, and model provider. Missing or invalid credentials must refuse the order and record the refusal reason.
