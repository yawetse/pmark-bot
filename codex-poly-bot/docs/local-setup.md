# Local Setup

`codex-poly-bot` runs locally with safe defaults. Live trading is disabled unless explicitly changed through runtime configuration.

1. Run `./scripts/setup-local.sh` from the project root. The script creates `backend/.venv`, installs backend test dependencies from `backend/pyproject.toml`, and runs the TASK-001 safe setup tests.
2. Copy `.env.example` files to local `.env` files if overrides are needed.
3. Start local services with `docker compose up`.
4. Run backend tests directly with `backend/.venv/bin/python -m pytest`.

Production trading secrets are not required for dependency installation, tests, or code inspection.
