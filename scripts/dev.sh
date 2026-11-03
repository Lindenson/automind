#!/usr/bin/env bash
# Local development: Postgres 16 in Docker (same service as the deployment, published on 127.0.0.1:5433),
# migrations, then the API on the host (http://127.0.0.1:8000; API_HOST=0.0.0.0 in .env for the network).
# AUTOMIND_EMBEDDED_DB=1 uses the old embedded database in ./.pgdata instead (no Docker).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
. scripts/lib/env.sh
if [[ "${AUTOMIND_EMBEDDED_DB:-0}" == "1" ]]; then
  scripts/db.sh
else
  docker_cmd
  ensure_db_secret
  port="${AUTOMIND_DB_PORT:-5433}"
  "${DOCKER[@]}" compose up -d postgres
  say "Waiting for Postgres on 127.0.0.1:$port"
  for _ in $(seq 1 60); do
    "${DOCKER[@]}" compose exec -T postgres pg_isready -U automind -d automind >/dev/null 2>&1 && break
    sleep 1
  done
  for db in automind_test automind_mig; do  # databases for the test suite
    "${DOCKER[@]}" compose exec -T postgres psql -U automind -d automind -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
      || "${DOCKER[@]}" compose exec -T postgres createdb -U automind "$db"
  done
  export DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@127.0.0.1:${port}/automind"
fi
# The API serves frontend/dist: rebuild it when the sources are newer (a stale build silently drops new
# message kinds, e.g. the "continue?" question had no buttons).
if [[ -d frontend/node_modules ]]; then
  if [[ ! -f frontend/dist/index.html ]] || [[ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html -print -quit)" ]]; then
    say "Building the frontend (sources changed)"
    (cd frontend && npm run -s build >/dev/null)
  fi
fi
cd backend
uv run python -m automind.infrastructure.db.migrate
exec uv run automind-api
