# Local Setup

`codex-poly-bot` runs locally with safe defaults. Live trading is disabled unless explicitly changed through runtime configuration.

1. Run `./scripts/setup-local.sh` from the project root. The script creates `backend/.venv`, installs backend test dependencies from `backend/pyproject.toml`, and runs the TASK-001 safe setup tests.
2. Copy `.env.example` files to local `.env` files if overrides are needed.
3. Install frontend dependencies with `cd frontend && npm install`.
4. Start local services with `docker compose up`.
5. Run backend tests directly with `backend/.venv/bin/python -m pytest`.
6. Run frontend checks with `cd frontend && npm run typecheck && npm run test:auth-boundary && npm run test:dashboard-controls`.
7. Run the backend API with `backend/.venv/bin/uvicorn app.main:create_app --factory --app-dir backend --reload --port 8000`.
8. Run the dashboard with `cd frontend && npm run dev`.

Production trading secrets are not required for dependency installation, tests, or code inspection.
