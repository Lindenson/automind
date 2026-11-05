#!/usr/bin/env bash
# Local development: Postgres 16 in Docker (same service as the deployment, published on 127.0.0.1:5433),
# migrations, then the API on the host (http://127.0.0.1:8000; API_HOST=0.0.0.0 in .env for the network).
# AUTOMIND_EMBEDDED_DB=1 uses the old embedded database in ./.pgdata instead (no Docker).
#
# scripts/dev.sh --docker: no uv or node needed on the host. The API runs from the app image with backend/ mounted
# and `uvicorn --reload` (http://127.0.0.1:8000), Vite runs in a node:22 container (http://127.0.0.1:5173, proxied
# to the API). Both use the host network (Linux), so the API sees browser requests from 127.0.0.1 as in host mode.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
. scripts/lib/env.sh
in_docker=0
if [[ "${1:-}" == "--docker" ]]; then in_docker=1; shift; fi
if [[ "$in_docker" == 1 && "${AUTOMIND_EMBEDDED_DB:-0}" == "1" ]]; then die "--docker uses the Docker Postgres; unset AUTOMIND_EMBEDDED_DB"; fi
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
if [[ "$in_docker" == 1 ]]; then
  [[ -f .env ]] || die ".env is missing: copy .env.example to .env and set the API keys"
  image="${COMPOSE_PROJECT_NAME:-automind}:latest"
  say "Building the app image ($image)"
  "${DOCKER[@]}" compose build app
  api="${COMPOSE_PROJECT_NAME:-automind}-dev-api"; web="${COMPOSE_PROJECT_NAME:-automind}-dev-web"
  stop() { "${DOCKER[@]}" rm -f -v "$api" "$web" >/dev/null 2>&1 || true; }
  trap stop EXIT INT TERM
  stop
  # backend/ is mounted over the image's copy; an anonymous volume keeps the image's .venv (Linux packages)
  export DATABASE_URL
  "${DOCKER[@]}" run -d --name "$api" --network host --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e DATABASE_URL \
    -v "$PWD/backend:/app/backend" -v /app/backend/.venv -v "$PWD/.env:/app/.env:ro" \
    "$image" sh -c "python -m automind.infrastructure.db.migrate && exec uvicorn automind.api.app:app \
      --host ${API_HOST:-127.0.0.1} --port ${API_PORT:-8000} --reload --reload-dir /app/backend/src \
      --reload-dir /app/backend/config" >/dev/null
  say "Vite in node:22 (npm ci into a volume on first start)"
  nm="${COMPOSE_PROJECT_NAME:-automind}-dev-node-modules"
  "${DOCKER[@]}" run --rm -v "$nm:/m" node:22-bookworm-slim chown "$(id -u):$(id -g)" /m
  "${DOCKER[@]}" run -d --name "$web" --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$PWD/frontend:/web" -v "$nm:/web/node_modules" -w /web \
    node:22-bookworm-slim sh -c '[ -f node_modules/.package-lock.json ] && cmp -s package-lock.json node_modules/.lock-copy \
      || { npm ci --no-audit --no-fund && cp package-lock.json node_modules/.lock-copy; }; exec npx vite --host 127.0.0.1 --port 5173' >/dev/null
  say "API http://127.0.0.1:${API_PORT:-8000}  UI http://127.0.0.1:5173  (Ctrl-C stops both)"
  "${DOCKER[@]}" logs -f "$api" &
  "${DOCKER[@]}" logs -f "$web"
  exit 0
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
