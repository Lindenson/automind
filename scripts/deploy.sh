#!/usr/bin/env bash
# AutoMind deployment with Docker Compose (app + Postgres 16).
#
#   scripts/deploy.sh [up]        build the image, start/upgrade the stack, run migrations, wait until healthy
#   scripts/deploy.sh down        stop the stack (data volume is kept)
#   scripts/deploy.sh restart     restart the app container
#   scripts/deploy.sh status      containers and the health endpoint
#   scripts/deploy.sh logs        follow the app logs
#   scripts/deploy.sh backup      pg_dump into ./backups/automind-<time>.sql.gz
#   scripts/deploy.sh restore F   restore a dump made by `backup` (replaces the current data)
#   scripts/deploy.sh destroy     stop and DELETE the database volume (asks for confirmation)
#
# Settings (environment or .env.docker): AUTOMIND_PORT (default 8080), AUTOMIND_BIND (default 127.0.0.1).
# Secrets: API keys are read from .env and never printed or baked into the image. The required model keys follow
#   the providers in backend/config/models.yaml (+ MODEL_<ROLE> overrides): google_genai -> GOOGLE_API_KEY or
#   GEMINI_API_KEY, openai -> OPENAI_API_KEY, anthropic -> ANTHROPIC_API_KEY; the search key follows
#   backend/config/search.yaml `provider:` (or SEARCH_PROVIDER): SERPER_API_KEY / SERPAPI_API_KEY / TAVILY_API_KEY.
#   POSTGRES_PASSWORD, ADMIN_TOKEN and METRICS_TOKEN are generated into .env.docker when missing.
set -euo pipefail
cd "$(dirname "$0")/.."

. scripts/lib/env.sh

# --- docker access ------------------------------------------------------------------------------
docker_cmd
compose() { "${DOCKER[@]}" compose "$@"; }

# --- configuration ------------------------------------------------------------------------------
ensure_env() {
  [[ -f .env ]] || die ".env is missing: copy .env.example to .env and set GOOGLE_API_KEY and SERPER_API_KEY."
  check_api_keys .env backend/config/models.yaml backend/config/search.yaml || die "set the keys above in .env"
  if grep -Eq '^DATABASE_URL=' .env; then
    echo "note: DATABASE_URL in .env is ignored by the containers (compose sets it)." >&2
  fi
  ensure_db_secret  # POSTGRES_PASSWORD, ADMIN_TOKEN, METRICS_TOKEN and optional AUTOMIND_PORT / AUTOMIND_BIND
  export AUTOMIND_PORT="${AUTOMIND_PORT:-8080}" AUTOMIND_BIND="${AUTOMIND_BIND:-127.0.0.1}"
}

url() { echo "http://${AUTOMIND_BIND/0.0.0.0/127.0.0.1}:${AUTOMIND_PORT}"; }

wait_healthy() {
  say "Waiting for the app to become healthy"
  for _ in $(seq 1 60); do
    state=$(compose ps --format '{{.Health}}' app 2>/dev/null || true)
    if [[ "$state" == "healthy" ]]; then
      health=$(curl -fsS "$(url)/api/v1/health" 2>/dev/null || true)
      say "Healthy: $(url)"
      [[ -n "$health" ]] && echo "$health" | python3 -c 'import json,sys; h=json.load(sys.stdin); print("   keys:", h["keys"], "| mcp tools:", len(h["mcp_tools"]))' 2>/dev/null || true
      return 0
    fi
    [[ "$state" == "unhealthy" ]] && break
    sleep 2
  done
  compose logs --tail 60 app >&2
  die "the app did not become healthy (logs above)"
}

port_free() {
  if command -v ss >/dev/null && ss -ltn "sport = :$AUTOMIND_PORT" | grep -q LISTEN; then
    compose ps --format '{{.Service}}' 2>/dev/null | grep -qx app && return 0  # it is our own container
    die "port $AUTOMIND_PORT is in use; set AUTOMIND_PORT=... in .env.docker or stop the other service"
  fi
}

cmd="${1:-up}"
case "$cmd" in
  up)
    ensure_env
    port_free
    say "Building the image"
    compose build --pull app
    say "Starting Postgres and the app (migrations run at container start)"
    compose up -d --remove-orphans
    wait_healthy
    ;;
  down)    ensure_env; compose down ;;
  restart) ensure_env; compose restart app; wait_healthy ;;
  status)  ensure_env; compose ps; curl -fsS "$(url)/api/v1/health" >/dev/null && say "health: ok ($(url))" || echo "health: unreachable" ;;
  logs)    ensure_env; compose logs -f --tail 200 app ;;
  backup)
    ensure_env
    mkdir -p backups
    f="backups/automind-$(date +%Y%m%d-%H%M%S).sql.gz"
    compose exec -T postgres pg_dump -U automind -d automind --clean --if-exists | gzip > "$f"
    say "Backup written: $f"
    ;;
  restore)
    ensure_env
    f="${2:-}"; [[ -f "$f" ]] || die "usage: scripts/deploy.sh restore backups/<file>.sql.gz"
    compose stop app
    gunzip -c "$f" | compose exec -T postgres psql -q -U automind -d automind -v ON_ERROR_STOP=1 >/dev/null
    compose start app
    wait_healthy
    ;;
  destroy)
    ensure_env
    read -r -p "Delete the AutoMind database volume? Type 'yes': " a
    [[ "$a" == "yes" ]] || die "aborted"
    compose down -v
    ;;
  *) sed -n '2,18p' "$0"; exit 2 ;;
esac
