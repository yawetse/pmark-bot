# Codex Web Setup

REQ: REQ-DEP-008, REQ-DEP-009, REQ-DEP-007, REQ-EXE-001

Codex web can inspect, install, and test this repository without production trading secrets. Keep the environment in dry-run mode unless a separate live enablement checklist has been completed.

## Setup Steps

1. Start from the project root, `codex-poly-bot`.
2. Run `./scripts/setup-local.sh`. This installs backend dependencies into `backend/.venv` and runs the safe setup tests.
3. Install the dashboard dependencies with `cd frontend && npm install`.
4. Run backend tests with `backend/.venv/bin/python -m pytest`.
5. Run frontend checks with `cd frontend && npm run typecheck && npm run test:auth-boundary && npm run test:dashboard-controls && npm run test:dashboard-operations`.

## Secret Boundary

Production trading secrets are not required for setup, tests, or code inspection. Do not add Polymarket private keys, Alpaca live keys, OpenAI or Anthropic production keys, GitHub OAuth secrets, or AWS secret access keys to Codex web. Use empty values from `.env.example` or local placeholders for tests.

## Expected Defaults

- `LIVE_ENABLED=false`
- `POLYMARKET_US_ENABLED=false`
- `POLYMARKET_INTERNATIONAL_ENABLED=false`
- `ALPACA_ENABLED=false`
- `DEFAULT_SELECTED_VENUE=polymarket_us`

Any work that needs live credentials belongs in AWS Secrets Manager for the target environment, not in Codex web or checked-in files.
