# codex-poly-bot Agent Setup

This project is safe to inspect, install, and test without production trading secrets.

Local defaults keep live trading off, select Polymarket US as the default venue, and disable every venue. Use `.env.example` files as templates for local `.env` files. Do not place production wallet keys, broker credentials, or LLM API keys in the repo.

Run backend tests from `backend/`:

```bash
./scripts/setup-local.sh
```

For direct backend work after setup:

```bash
backend/.venv/bin/python -m pytest
```
