#!/usr/bin/env bash
# Start the local dev stack: embedded Postgres (./.pgdata) + migrations + backend API
# (serves frontend/dist if built) on http://127.0.0.1:8000.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
scripts/db.sh
cd backend
uv run python -m automind.infrastructure.db.migrate
exec uv run automind-api
