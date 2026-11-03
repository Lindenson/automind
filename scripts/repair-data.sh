#!/usr/bin/env bash
# Re-check stored values with the current verification rules (spec 004 FR-027) and recompute selected values.
# Usage: scripts/repair-data.sh [--engine]   (Docker Postgres must run; take a backup first)
#   --engine: only fill engine_cc / power_kw / fuel of stored variants from their names (spec 005)
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env.docker ]]; then set -a; . ./.env.docker; set +a; fi
export DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@127.0.0.1:${AUTOMIND_DB_PORT:-5433}/automind"
cd backend
if [[ "${1:-}" == "--engine" ]]; then
  uv run python -c 'import asyncio, json; from automind.application.backfill import backfill_engines; print(json.dumps(asyncio.run(backfill_engines())))'
  exit 0
fi
uv run python - <<'PY'
import asyncio, json
from automind.infrastructure.config import configure_domain, reference
from automind.orchestration.prompts import load_all
from automind.application.repair import repair_claims

configure_domain()
print(json.dumps(asyncio.run(repair_claims(reference(load_all()))), indent=1, sort_keys=True))
PY
