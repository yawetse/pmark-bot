# Local Setup

REQ: REQ-DEP-001, REQ-DEP-007, REQ-DEP-008, REQ-DEP-009, REQ-WAL-004, REQ-EXE-001

`codex-poly-bot` runs locally with safe defaults. Live trading is disabled unless explicitly changed through runtime configuration.

## Safe Local Files

Copy the checked-in examples only when local overrides are needed:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
cp infra/.env.example infra/.env
```

The `.env` and `.env.local` paths are gitignored. Keep local wallet keys, broker credentials, GitHub OAuth secrets, and LLM API keys out of commits. Leave `LIVE_ENABLED=false` and all venue flags set to `false` unless a local dry-run test requires a different non-production setting.

## Setup

1. Run `./scripts/setup-local.sh` from the project root. The script creates `backend/.venv`, installs backend test dependencies from `backend/pyproject.toml`, and runs the safe setup tests.
2. Install frontend dependencies with `cd frontend && npm install`.
3. Start local services with `docker compose up`. The compose contract starts Postgres, the FastAPI backend on port `8000`, and the Next.js dashboard on port `3000`.
4. Run backend tests directly with `backend/.venv/bin/python -m pytest`.
5. Run frontend checks with `cd frontend && npm run typecheck && npm run test:auth-boundary && npm run test:dashboard-controls && npm run test:dashboard-operations`.
6. Run the backend API with `backend/.venv/bin/uvicorn app.main:create_app --factory --app-dir backend --reload --port 8000`.
7. Run the dashboard with `cd frontend && npm run dev`.

For local dashboard testing without GitHub OAuth secrets, start the frontend with `ALLOW_LOCAL_AUTH_BYPASS=true`, `DASHBOARD_ALLOWED_USERS=yaw`, and local session secrets. This bypass is disabled in production.

## Local Trading Safety

Local setup is safe for dependency installation, code inspection, and tests. The default runtime mode is dry-run, venue adapters are disabled, and missing live credentials must block live orders before a venue call.

Production trading secrets are not required for dependency installation, tests, or code inspection.
