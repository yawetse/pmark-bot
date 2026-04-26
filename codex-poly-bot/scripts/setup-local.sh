#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "Python 3 is required for local setup." >&2
    exit 1
  fi
fi

echo "Checking codex-poly-bot local scaffold..."
test -f "$ROOT_DIR/.env.example"
test -f "$ROOT_DIR/backend/.env.example"
test -f "$ROOT_DIR/frontend/.env.example"
test -f "$ROOT_DIR/infra/.env.example"
test -d "$ROOT_DIR/docs"

echo "Installing backend test dependencies in a local virtual environment..."
"$PYTHON_BIN" -m venv "$ROOT_DIR/backend/.venv"
"$ROOT_DIR/backend/.venv/bin/python" -m pip install --upgrade pip
"$ROOT_DIR/backend/.venv/bin/python" -m pip install -e "$ROOT_DIR/backend"

echo "Running TASK-001 safe setup tests..."
"$ROOT_DIR/backend/.venv/bin/python" -m pytest -q \
  -k "req_dep_001 or req_dep_007 or req_dep_008 or req_dep_009 or req_exe_001 or req_ven_002 or req_ven_003 or req_exe_012 or req_alp_013" \
  "$ROOT_DIR/backend/tests"

echo "Safe defaults are dry-run only. No production trading secrets are required."
