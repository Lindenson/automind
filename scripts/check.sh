#!/usr/bin/env bash
# Quality gates (constitution V, IX): lint, format, domain typing, layer contracts, tests.
#   scripts/check.sh [pytest args]            on the host (uv, node), the default
#   scripts/check.sh --docker [pytest args]   the same steps in the Dockerfile's `check` stage against the compose
#                                             Postgres; the host needs only Docker
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

if [[ "${1:-}" == "--docker" ]]; then
  shift
  . scripts/lib/env.sh
  docker_cmd
  ensure_db_secret
  "${DOCKER[@]}" compose up -d postgres
  say "Waiting for Postgres"
  for _ in $(seq 1 60); do
    "${DOCKER[@]}" compose exec -T postgres pg_isready -U automind -d automind >/dev/null 2>&1 && break
    sleep 1
  done
  for db in automind_test automind_mig; do
    "${DOCKER[@]}" compose exec -T postgres psql -U automind -d automind -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
      || "${DOCKER[@]}" compose exec -T postgres createdb -U automind "$db"
  done
  pg=$("${DOCKER[@]}" compose ps -q postgres)
  net=$("${DOCKER[@]}" inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$pg" | awk '{print $1}')
  image="${COMPOSE_PROJECT_NAME:-automind}-check:latest"
  say "Building the check image ($image)"
  "${DOCKER[@]}" build --target check -t "$image" .
  say "Running the checks in Docker (network $net)"
  # passed by name from this environment, so the password is not on the docker command line
  export TEST_DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@postgres:5432/automind_test"
  exec "${DOCKER[@]}" run --rm --network "$net" -e TEST_DATABASE_URL "$image" scripts/check.sh "$@"
fi

# Test database: the Docker Postgres when it runs (scripts/dev.sh starts it), else the embedded one.
if [[ -z "${TEST_DATABASE_URL:-}" && -f .env.docker ]]; then set -a; . ./.env.docker; set +a; fi
if [[ -z "${TEST_DATABASE_URL:-}" && -f .env.docker ]] && docker compose ps --status running postgres 2>/dev/null | grep -q postgres; then
  for db in automind_test automind_mig; do
    docker compose exec -T postgres psql -U automind -d automind -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" \
      | grep -q 1 || docker compose exec -T postgres createdb -U automind "$db"
  done
  export TEST_DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@127.0.0.1:${AUTOMIND_DB_PORT:-5433}/automind_test"
fi
cd backend
uv run ruff check src tests
uv run ruff format --check src tests
# the former domain package (spec 012 moved its modules into the areas; same strict scope)
uv run mypy src/automind/chat/domain src/automind/chat/dialog/policy src/automind/shared/vehicle/identity.py src/automind/shared/vehicle/markets.py src/automind/shared/vehicle/engine.py src/automind/shared/text src/automind/shared/vehicle/specs \
  src/automind/shared/vehicle/units.py src/automind/shared/evidence src/automind/shared/research_order \
  src/automind/acquisition/domain/plausibility.py src/automind/acquisition/domain/sense_ev.py \
  src/automind/acquisition/domain/relevance.py src/automind/observability/domain/outcome.py \
  src/automind/chat/application/services/research \
  src/automind/chat/application/services/identification src/automind/chat/application/services/report \
  src/automind/shared/contracts/json.py
# spec 012: mypy over all of src in report mode (the strict scope grows step by step, research R16)
echo "mypy report (all of src): $(uv run mypy src/automind 2>/dev/null | tail -1)"
uv run lint-imports
uv run python ../scripts/check_structure.py  # spec 012: shape rules with a shrinking baseline (ratchet)
# the frontend is checked even when a backend test fails, so one failure never hides another
rc=0
uv run pytest -q "$@" || rc=$?
if [ -d ../frontend/node_modules ]; then
  (cd ../frontend && npm run -s typecheck && npm test --silent) || rc=$?
fi
exit "$rc"
