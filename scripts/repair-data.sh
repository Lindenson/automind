#!/usr/bin/env bash
# Re-check stored values with the current verification rules (spec 004 FR-027) and recompute selected values.
# Usage: scripts/repair-data.sh [--duplicates [--apply] | --sources]   (Docker Postgres must run; take a backup first)
#   --duplicates [--apply]: fold catalog rows that are one car (dry run without --apply)
#   --sources: only type the stored sources again (official maker domains, favourites' own types) and reselect
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env.docker ]]; then set -a; . ./.env.docker; set +a; fi
export DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@127.0.0.1:${AUTOMIND_DB_PORT:-5433}/automind"
cd backend
if [[ "${1:-}" == "--duplicates" ]]; then
  APPLY=$([[ "${2:-}" == "--apply" ]] && echo True || echo False)
  uv run python -c "import asyncio, json; from automind.shared.infrastructure.config.loader import configure_domain; configure_domain(); from automind.chat.application.maintenance.repair import merge_duplicates; print(json.dumps(asyncio.run(merge_duplicates($APPLY)), indent=1, sort_keys=True, default=str))"
  exit 0
fi
if [[ "${1:-}" == "--sources" ]]; then
  uv run python -c 'import asyncio, json; from automind.shared.infrastructure.config.loader import configure_domain; configure_domain(); from automind.chat.application.maintenance.repair import reclassify_sources; print(json.dumps(asyncio.run(reclassify_sources()), indent=1, sort_keys=True))'
  exit 0
fi
uv run python - <<'PY'
import asyncio, json
from automind.shared.infrastructure.config.loader import configure_domain, reference
from automind.chat.dialog.prompts import load_all
from automind.chat.application.maintenance.repair import repair_claims

configure_domain()
print(json.dumps(asyncio.run(repair_claims(reference(load_all()))), indent=1, sort_keys=True))
PY
