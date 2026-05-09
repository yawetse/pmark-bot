# claude-poly-bot

Dual-LLM (Claude + OpenAI) trading bot for Polymarket and Alpaca.

See `requirements.md`, `design-hld.md`, `design-lld.md`, `plan.md`, `tasks.md`, `test-spec.md` for the full specification.

## Local development

Prerequisites: Docker, Python 3.12, Node 22, uv.

```bash
# 1. Copy env
cp .env.example .env
# Fill in real values for ANTHROPIC_API_KEY, OPENAI_API_KEY, POLYGON_RPC_URL.
# Wallet + Alpaca + OAuth keys are populated by setup CLIs (M4–M8).

# 2. Bring up the local stack
docker compose up --build

# 3. Run Python tests
cd python
uv pip install --system -e ".[dev]"
pytest -v
```

LIVE_ENABLED defaults to `false`; the bot only ever simulates trades locally.

## Working from Claude Code Web

Open the repo in GitHub Codespaces; the `.devcontainer/devcontainer.json` provisions Python + Node + AWS CLI + Docker-in-Docker automatically.

## Status

Build is in progress per the milestone plan in `plan.md`. M0 (foundation) is complete; later milestones land per the implementation cadence.
