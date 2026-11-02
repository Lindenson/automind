#!/usr/bin/env bash
# Quality gates (constitution V, IX): lint, format, domain typing, layer contracts, tests.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
# Test database: the Docker Postgres when it runs (scripts/dev.sh starts it), else the embedded one.
if [[ -z "${TEST_DATABASE_URL:-}" && -f .env.docker ]] && docker compose ps --status running postgres 2>/dev/null | grep -q postgres; then
  set -a; . ./.env.docker; set +a
  for db in automind_test automind_mig; do
    docker compose exec -T postgres psql -U automind -d automind -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" \
      | grep -q 1 || docker compose exec -T postgres createdb -U automind "$db"
  done
  export TEST_DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@127.0.0.1:${AUTOMIND_DB_PORT:-5433}/automind_test"
fi
cd backend
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/automind/domain
uv run lint-imports
uv run pytest -q "$@"
if [ -d ../frontend/node_modules ]; then
  (cd ../frontend && npm run -s typecheck && npm test --silent)
fi
