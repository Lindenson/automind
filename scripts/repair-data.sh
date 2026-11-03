#!/usr/bin/env bash
# Re-check stored values with the current verification rules (spec 004 FR-027) and recompute selected values.
# Usage: scripts/repair-data.sh   (uses DATABASE_URL from .env; the Docker Postgres must be running)
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env.docker ]]; then set -a; . ./.env.docker; set +a; fi
export DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@127.0.0.1:${AUTOMIND_DB_PORT:-5433}/automind"
cd backend
uv run python - <<'PY'
import asyncio, json
from automind.infrastructure.config import configure_domain, reference
from automind.orchestration.prompts import load_all
from automind.application.repair import repair_claims

configure_domain()
print(json.dumps(asyncio.run(repair_claims(reference(load_all()))), indent=1, sort_keys=True))
PY
