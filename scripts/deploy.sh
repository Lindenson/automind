#!/usr/bin/env bash
# AutoMind deployment with Docker Compose (app + Postgres 16; optional Prometheus/Alertmanager and Caddy).
#
#   scripts/deploy.sh [up] [--monitoring] [--public]
#                                 build the image, start/upgrade the stack, run migrations, wait until healthy;
#                                 --monitoring also starts Prometheus + Alertmanager, --public also starts Caddy (TLS)
#   scripts/deploy.sh down        stop the stack, all profiles (data volumes are kept)
#   scripts/deploy.sh restart     restart the app container
#   scripts/deploy.sh status      containers and the health endpoint
#   scripts/deploy.sh logs        follow the app logs
#   scripts/deploy.sh backup      pg_dump into ./backups/automind-<time>.sql.gz
#   scripts/deploy.sh restore F   restore a dump made by `backup` (replaces the current data)
#   scripts/deploy.sh destroy     stop and DELETE the database volume (asks for confirmation)
#   scripts/deploy.sh monitoring up|down|status
#                                 Prometheus (127.0.0.1:9090) + Alertmanager (127.0.0.1:9093); writes
#                                 deploy/prometheus/metrics_token (mode 600) from METRICS_TOKEN in .env.docker
#   scripts/deploy.sh export [FILE] [--encrypt]
#                                 one bundle (mode 600, default backups/automind-bundle-<time>.tar.gz): fresh DB dump,
#                                 .env, .env.docker, metrics token, deploy/ config, BUNDLE_INFO (git commit, date);
#                                 --encrypt: passphrase with `age -p` or `gpg -c`
#   scripts/deploy.sh import BUNDLE [--force] [--monitoring]
#                                 on a fresh clone: check out the bundle's commit (clean tree only), restore secrets
#                                 (--force overwrites existing .env/.env.docker and a non-empty database), build,
#                                 restore the dump, start, wait until healthy
#   scripts/deploy.sh move USER@HOST [DIR]
#                                 copy this installation to another server over SSH (DIR default ~/automind): clone the
#                                 origin at the same commit, send a fresh bundle, import it there. This stack keeps
#                                 running; stop it with `down` once the new one is verified (docs/deploy.md)
#   scripts/deploy.sh bootstrap   check Docker, the compose plugin and git on this server (prints install commands,
#                                 never runs sudo) and create .env from .env.example (interactive terminals only)
#
# Settings (environment or .env.docker): AUTOMIND_PORT (default 8080), AUTOMIND_BIND (default 127.0.0.1),
#   AUTOMIND_DB_PORT (5433), AUTOMIND_DOMAIN (profile public), COMPOSE_PROJECT_NAME (default automind).
# Secrets: API keys are read from .env and never printed or baked into the image. The required model keys follow
#   the providers in backend/config/models.yaml (+ MODEL_<ROLE> overrides): google_genai -> GOOGLE_API_KEY or
#   GEMINI_API_KEY, openai -> OPENAI_API_KEY, anthropic -> ANTHROPIC_API_KEY; the search key follows
#   backend/config/search.yaml `provider:` (or SEARCH_PROVIDER): SERPER_API_KEY / SERPAPI_API_KEY / TAVILY_API_KEY.
#   POSTGRES_PASSWORD, ADMIN_TOKEN and METRICS_TOKEN are generated into .env.docker when missing.
set -euo pipefail
cd "$(dirname "$0")/.."

. scripts/lib/env.sh

HELP_LINES=38
usage() { sed -n "2,${HELP_LINES}p" "$0" | sed 's/^# \{0,1\}//'; }

# --- temporary files and the SSH master connection are removed on exit --------------------------------------------
CLEANUP=(); SSH_CTL=""; SSH_TARGET=""
cleanup() {
  if [[ -n "$SSH_CTL" ]]; then ssh -o ControlPath="$SSH_CTL" -O exit "$SSH_TARGET" >/dev/null 2>&1 || true; fi
  if ((${#CLEANUP[@]})); then rm -rf "${CLEANUP[@]}"; fi
}
trap cleanup EXIT
mktmp() { local d; d=$(mktemp -d); chmod 700 "$d"; CLEANUP+=("$d"); printf -v "$1" %s "$d"; }  # mktmp VAR

# --- docker access (not needed by bootstrap/help) -----------------------------------------------------------------
compose() { "${DOCKER[@]}" compose "$@"; }
ALL_PROFILES=(--profile monitoring --profile public)

# --- configuration ------------------------------------------------------------------------------------------------
ensure_env() {
  [[ -n "${DOCKER+x}" ]] || docker_cmd
  if [[ ! -f .env ]]; then  # keys may live in .env.docker only; compose still needs the file
    (umask 077; printf '# AutoMind settings; API keys may be here or in .env.docker\n' > .env)
  fi
  local merged
  merged="$(mktemp)"; chmod 600 "$merged"
  cat .env > "$merged"; [[ -f .env.docker ]] && cat .env.docker >> "$merged"
  if ! check_api_keys "$merged" backend/config/models.yaml backend/config/search.yaml; then
    rm -f "$merged"; die "set the keys above in .env or .env.docker"
  fi
  rm -f "$merged"
  if grep -Eq '^DATABASE_URL=' .env; then
    echo "note: DATABASE_URL in .env is ignored by the containers (compose sets it)." >&2
  fi
  ensure_db_secret  # POSTGRES_PASSWORD, ADMIN_TOKEN, METRICS_TOKEN and optional AUTOMIND_PORT / AUTOMIND_BIND
  export AUTOMIND_PORT="${AUTOMIND_PORT:-8080}" AUTOMIND_BIND="${AUTOMIND_BIND:-127.0.0.1}"
  export AUTOMIND_UID="${AUTOMIND_UID:-$(id -u)}"  # Prometheus runs as this user to read the token file
}

url() { echo "http://${AUTOMIND_BIND/0.0.0.0/127.0.0.1}:${AUTOMIND_PORT}"; }

wait_healthy() {
  say "Waiting for the app to become healthy"
  for _ in $(seq 1 90); do
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

wait_postgres() {
  for _ in $(seq 1 60); do
    compose exec -T postgres pg_isready -U automind -d automind >/dev/null 2>&1 && return 0
    sleep 1
  done
  die "Postgres did not become ready"
}

running() { [[ -n "$(compose "${ALL_PROFILES[@]}" ps -q --status running "$1" 2>/dev/null)" ]]; }

# --- monitoring (profile `monitoring`) ----------------------------------------------------------------------------
TOKEN_FILE=deploy/prometheus/metrics_token

write_metrics_token() {
  [[ -n "${METRICS_TOKEN:-}" ]] || die "METRICS_TOKEN is empty in .env.docker"
  if [[ -d "$TOKEN_FILE" ]]; then
    die "$TOKEN_FILE is a directory (Docker created it when the file was missing); remove it (it may need sudo) and retry"
  fi
  (umask 077; printf '%s' "$METRICS_TOKEN" > "$TOKEN_FILE.tmp")
  chmod 600 "$TOKEN_FILE.tmp"
  mv -f "$TOKEN_FILE.tmp" "$TOKEN_FILE"
}

monitoring_up() {
  write_metrics_token
  say "Starting Prometheus and Alertmanager (profile monitoring)"
  compose --profile monitoring up -d prometheus alertmanager
  # config and rules are bind-mounted files: reload them when the containers already ran
  curl -fsS -X POST "http://127.0.0.1:${AUTOMIND_PROMETHEUS_PORT:-9090}/-/reload" >/dev/null 2>&1 || true
  say "Prometheus: http://127.0.0.1:${AUTOMIND_PROMETHEUS_PORT:-9090}  Alertmanager: http://127.0.0.1:${AUTOMIND_ALERTMANAGER_PORT:-9093}"
}

monitoring_status() {
  compose --profile monitoring ps prometheus alertmanager
  local p="http://127.0.0.1:${AUTOMIND_PROMETHEUS_PORT:-9090}"
  if curl -fsS "$p/-/ready" >/dev/null 2>&1; then
    curl -fsS "$p/api/v1/targets?state=active" | python3 -c '
import json, sys
for t in json.load(sys.stdin)["data"]["activeTargets"]:
    print("   scrape", t["labels"].get("job"), t["scrapeUrl"], "->", t["health"], t.get("lastError") or "")'
    curl -fsS "$p/api/v1/rules" | python3 -c '
import json, sys
rules = [r for g in json.load(sys.stdin)["data"]["groups"] for r in g["rules"]]
firing = [r["name"] for r in rules if r.get("state") == "firing"]
print("   rules loaded:", len(rules), "| firing:", ", ".join(firing) or "none")'
  else
    echo "prometheus: not reachable at $p"
  fi
}

# --- bundles: export / import -------------------------------------------------------------------------------------
BUNDLE_CONFIG=(deploy/prometheus/prometheus.yml deploy/prometheus/automind-rules.yml deploy/prometheus/alertmanager.yml
               deploy/caddy/Caddyfile)

encryptor() {  # prints the tool used for --encrypt, or fails
  if command -v age >/dev/null; then echo age
  elif command -v gpg >/dev/null; then echo gpg
  else return 1
  fi
}

# do_export OUT ENCRYPT(0|1): writes the bundle (OUT.age / OUT.gpg when encrypting); sets EXPORTED to its path
do_export() {
  local out="$1" enc="$2" tool="" tmp commit f
  if [[ "$enc" == 1 ]]; then
    tool=$(encryptor) || die "--encrypt needs 'age' (apt install age) or 'gpg' (apt install gnupg); neither is installed"
  fi
  running postgres || die "the stack is not running here (scripts/deploy.sh up first): a bundle needs a fresh dump"
  commit=$(git rev-parse HEAD)
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "warning: tracked files have local changes; the bundle records commit ${commit:0:12} only (deploy/ config is included)." >&2
  fi
  mktmp tmp
  say "Dumping the database"
  compose exec -T postgres pg_dump -U automind -d automind --clean --if-exists | gzip > "$tmp/automind.sql.gz"
  cp .env "$tmp/env"; cp .env.docker "$tmp/env.docker"
  if [[ -f "$TOKEN_FILE" ]]; then cp "$TOKEN_FILE" "$tmp/metrics_token"; fi
  mkdir -p "$tmp/config"
  for f in "${BUNDLE_CONFIG[@]}"; do if [[ -f "$f" ]]; then install -D -m 600 "$f" "$tmp/config/$f"; fi; done
  {
    echo "format=1"
    echo "commit=$commit"
    echo "date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "source_host=$(hostname)"
    echo "origin=$(git remote get-url origin 2>/dev/null || true)"
    echo "dirty=$([[ -n "$(git status --porcelain --untracked-files=no)" ]] && echo yes || echo no)"
  } > "$tmp/BUNDLE_INFO"
  mkdir -p "$(dirname "$out")"
  (umask 077; tar -czf "$out" -C "$tmp" .)
  chmod 600 "$out"
  case "$tool" in
    age) age -p -o "$out.age" "$out" </dev/tty && rm -f "$out" && out="$out.age" ;;
    gpg) gpg --symmetric --cipher-algo AES256 -o "$out.gpg" "$out" && rm -f "$out" && out="$out.gpg" ;;
  esac
  chmod 600 "$out"
  EXPORTED="$out"
}

# unpack_bundle BUNDLE DIR: decrypts when needed and extracts into DIR
unpack_bundle() {
  local b="$1" d="$2"
  case "$b" in
    *.age) command -v age >/dev/null || die "the bundle is encrypted with age; install it (apt install age)"
           age -d "$b" | tar -xzf - -C "$d" ;;
    *.gpg) command -v gpg >/dev/null || die "the bundle is encrypted with gpg; install it (apt install gnupg)"
           gpg -d "$b" | tar -xzf - -C "$d" ;;
    *)     tar -xzf "$b" -C "$d" ;;
  esac
  [[ -f "$d/BUNDLE_INFO" && -f "$d/automind.sql.gz" && -f "$d/env" && -f "$d/env.docker" ]] \
    || die "not an AutoMind bundle (BUNDLE_INFO, automind.sql.gz, env, env.docker expected)"
}

do_import() {
  local bundle="$1" force="$2" monitoring="$3" tmp commit f
  [[ -f "$bundle" ]] || die "usage: scripts/deploy.sh import <bundle> [--force] [--monitoring]"
  docker_cmd
  if [[ "$force" != 1 ]]; then
    for f in .env .env.docker; do
      if [[ -e "$f" ]]; then die "$f already exists here; import is meant for a fresh clone (use --force to overwrite it)"; fi
    done
  fi
  mktmp tmp
  unpack_bundle "$bundle" "$tmp"
  commit=$(sed -n 's/^commit=//p' "$tmp/BUNDLE_INFO")
  say "Bundle: commit ${commit:0:12}, made $(sed -n 's/^date=//p' "$tmp/BUNDLE_INFO") on $(sed -n 's/^source_host=//p' "$tmp/BUNDLE_INFO")"

  # the code: the bundle's commit
  if [[ "$(git rev-parse HEAD)" != "$commit" ]]; then
    [[ -z "$(git status --porcelain --untracked-files=no)" ]] \
      || die "the working tree has local changes; commit or discard them before checking out ${commit:0:12}"
    git cat-file -e "$commit^{commit}" 2>/dev/null || { say "Fetching from origin"; git fetch --quiet origin; }
    git cat-file -e "$commit^{commit}" 2>/dev/null \
      || die "commit ${commit:0:12} is not in this repository (push it to origin on the old host first)"
    say "Checking out ${commit:0:12}"
    git -c advice.detachedHead=false checkout --quiet "$commit"
  fi

  # secrets and configuration
  say "Restoring .env, .env.docker and the metrics token"
  (umask 077; cp "$tmp/env" .env; cp "$tmp/env.docker" .env.docker)
  chmod 600 .env .env.docker
  if [[ -f "$tmp/metrics_token" ]]; then
    if [[ -d "$TOKEN_FILE" ]]; then die "$TOKEN_FILE is a directory; remove it and retry"; fi
    (umask 077; cp "$tmp/metrics_token" "$TOKEN_FILE"); chmod 600 "$TOKEN_FILE"
  fi
  for f in "${BUNDLE_CONFIG[@]}"; do
    if [[ -f "$tmp/config/$f" ]] && ! cmp -s "$tmp/config/$f" "$f"; then
      install -D -m 644 "$tmp/config/$f" "$f"
      echo "note: $f restored from the bundle (it differs from the commit: the owner's local settings)." >&2
    fi
  done

  ensure_env
  port_free
  say "Building the image"
  compose build --pull app
  say "Starting Postgres"
  compose up -d postgres
  wait_postgres
  local tables
  tables=$(compose exec -T postgres psql -U automind -d automind -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" | tr -d '[:space:]')
  if [[ "$tables" != 0 && "$force" != 1 ]]; then
    die "the database here already has $tables tables; use --force to replace them with the bundle"
  fi
  say "Restoring the database dump"
  compose stop app >/dev/null 2>&1 || true
  gunzip -c "$tmp/automind.sql.gz" | compose exec -T postgres psql -q -U automind -d automind -v ON_ERROR_STOP=1 >/dev/null
  say "Starting the app"
  compose up -d --remove-orphans
  wait_healthy
  if [[ "$monitoring" == 1 ]]; then monitoring_up; fi
}

# --- move to another server ---------------------------------------------------------------------------------------
do_move() {
  local target="$1" dir="$2" origin commit rdir sshdir name bundle q
  ensure_env
  origin="${AUTOMIND_MOVE_ORIGIN:-$(git remote get-url origin 2>/dev/null || true)}"
  [[ -n "$origin" ]] || die "this clone has no 'origin' remote (set AUTOMIND_MOVE_ORIGIN=<git url>)"
  commit=$(git rev-parse HEAD)
  git fetch --quiet origin 2>/dev/null || echo "warning: git fetch origin failed; checking known remote branches only" >&2
  [[ -n "$(git branch -r --contains "$commit" 2>/dev/null)" ]] \
    || die "commit ${commit:0:12} is not on origin yet: push it first (the target clones from $origin)"
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] \
    || echo "warning: local changes to tracked files are not moved (only deploy/ config travels in the bundle)." >&2

  mktmp sshdir; SSH_CTL="$sshdir/cm"; SSH_TARGET="$target"
  local SSH=(ssh -o ControlMaster=auto -o ControlPath="$SSH_CTL" -o ControlPersist=120)
  say "Checking $target"
  "${SSH[@]}" "$target" true || die "cannot connect to $target over SSH"
  local missing
  missing=$("${SSH[@]}" "$target" 'm=""; command -v git >/dev/null || m="$m git"; command -v curl >/dev/null || m="$m curl";
    if ! command -v docker >/dev/null; then m="$m docker"; elif ! docker compose version >/dev/null 2>&1; then
      if docker info 2>&1 | grep -q "permission denied"; then m="$m docker-group"; else m="$m compose"; fi; fi; echo $m')
  if [[ -n "$missing" ]]; then
    echo "The target is missing:$missing. Run these on $target (nothing is installed by this script):" >&2
    if [[ " $missing " == *" git "* || " $missing " == *" curl "* ]]; then echo "  sudo apt-get update && sudo apt-get install -y git curl ca-certificates" >&2; fi
    if [[ " $missing " == *" docker "* ]]; then echo "  curl -fsSL https://get.docker.com | sudo sh" >&2; fi
    if [[ " $missing " == *" docker "* || " $missing " == *" docker-group "* ]]; then echo "  sudo usermod -aG docker \$USER   # then log out and in again" >&2; fi
    if [[ " $missing " == *" compose "* ]]; then echo "  sudo apt-get install -y docker-compose-plugin" >&2; fi
    die "install the above on $target and run move again"
  fi

  # the target directory, with ~ resolved on the target
  # shellcheck disable=SC2088  # a literal ~ given by the user, resolved on the target
  if [[ "$dir" == "~" || "$dir" == "~/"* ]]; then
    rdir="$("${SSH[@]}" "$target" 'printf %s "$HOME"')${dir#\~}"
  else
    rdir="$dir"
  fi
  q=$(printf '%q' "$rdir")
  if "${SSH[@]}" "$target" "[ -e $q ] && [ -n \"\$(ls -A $q 2>/dev/null)\" ]"; then
    die "$target:$rdir exists and is not empty; choose another directory (scripts/deploy.sh move $target <dir>)"
  fi
  say "Cloning $origin at ${commit:0:12} into $target:$rdir"
  "${SSH[@]}" "$target" "git clone --quiet $(printf '%q' "$origin") $q && cd $q && git -c advice.detachedHead=false checkout --quiet $commit" \
    || die "clone on $target failed (for a private repo give $target read access, e.g. a deploy key, or set AUTOMIND_MOVE_ORIGIN to an https URL)"

  say "Making a fresh bundle"
  name="automind-bundle-$(date +%Y%m%d-%H%M%S).tar.gz"
  do_export "$sshdir/$name" 0; bundle="$EXPORTED"
  "${SSH[@]}" "$target" "mkdir -p $q/backups && chmod 700 $q/backups"
  scp -q -o ControlPath="$SSH_CTL" "$bundle" "$target:$rdir/backups/$name" || die "scp to $target failed"
  rm -f "$bundle"
  say "Importing on $target"
  "${SSH[@]}" -t "$target" "cd $q && scripts/deploy.sh import backups/$name && rm -f backups/$name" \
    || die "import on $target failed; the bundle stays in $rdir/backups/$name (it holds secrets: delete it when done)"

  local port bind host="${target#*@}"
  port=$(env_value .env.docker AUTOMIND_PORT); port="${port:-8080}"
  bind=$(env_value .env.docker AUTOMIND_BIND); bind="${bind:-127.0.0.1}"
  say "Moved. This stack is still running here: verify the new one, then run scripts/deploy.sh down here."
  if [[ "$bind" == "127.0.0.1" ]]; then
    echo "   The app on $host listens on 127.0.0.1:$port only. Open it with an SSH tunnel:"
    echo "     ssh -L $port:127.0.0.1:$port $target   ->  http://127.0.0.1:$port"
  else
    echo "   http://$host:$port"
  fi
  echo "   Checklist: docs/deploy.md (health, /metrics, /admin)"
}

# --- bootstrap an empty server ------------------------------------------------------------------------------------
do_bootstrap() {
  local ok=1
  say "Checking this server"
  if [[ -r /etc/os-release ]]; then echo "   OS: $(. /etc/os-release; echo "${PRETTY_NAME:-unknown}")"; fi
  for t in git curl; do
    command -v "$t" >/dev/null || { echo "missing: $t   ->  sudo apt-get update && sudo apt-get install -y $t ca-certificates"; ok=0; }
  done
  if ! command -v docker >/dev/null; then
    echo "missing: Docker   ->  curl -fsSL https://get.docker.com | sudo sh"
    echo "                      sudo usermod -aG docker \$USER   # then log out and in again"
    ok=0
  else
    if ! docker info >/dev/null 2>&1; then
      if docker info 2>&1 | grep -q "permission denied"; then
        echo "no access to Docker  ->  sudo usermod -aG docker \$USER   # then log out and in again"
      else
        echo "Docker is not running  ->  sudo systemctl enable --now docker"
      fi
      ok=0
    fi
    docker compose version >/dev/null 2>&1 \
      || { echo "missing: Docker Compose v2 plugin  ->  sudo apt-get install -y docker-compose-plugin"; ok=0; }
  fi
  if [[ ! -f .env ]]; then
    if [[ -t 0 ]]; then
      say "Creating .env from .env.example (values are not echoed; Enter skips)"
      (umask 077; cp .env.example .env)
      local key val
      for key in GOOGLE_API_KEY SERPER_API_KEY TAVILY_API_KEY; do
        read -r -s -p "   $key: " val; echo
        [[ -n "$val" ]] || continue
        KEY="$key" VAL="$val" python3 - .env <<'PY'
import os, re, sys
p, k, v = sys.argv[1], os.environ["KEY"], os.environ["VAL"]
s = open(p, encoding="utf-8").read()
s, n = re.subn(rf"(?m)^#?\s*{k}=.*$", lambda _: f"{k}={v}", s, count=1)
open(p, "w", encoding="utf-8").write(s if n else s + f"\n{k}={v}\n")
PY
      done
      chmod 600 .env
    else
      echo ".env is missing and stdin is not a terminal: cp .env.example .env, then set GOOGLE_API_KEY and SERPER_API_KEY"
      ok=0
    fi
  fi
  if [[ -f .env ]]; then
    check_api_keys .env backend/config/models.yaml backend/config/search.yaml || ok=0
  fi
  if [[ "$ok" == 1 ]]; then say "Ready: scripts/deploy.sh up   (or import a bundle: scripts/deploy.sh import <bundle>)"
  else die "fix the items above and run scripts/deploy.sh bootstrap again"; fi
}

# --- commands -----------------------------------------------------------------------------------------------------
cmd="${1:-up}"; [[ $# -gt 0 ]] && shift
case "$cmd" in
  up|--monitoring|--public)
    [[ "$cmd" == up ]] || set -- "$cmd" "$@"
    profiles=()
    for a in "$@"; do
      case "$a" in
        --monitoring) profiles+=(--profile monitoring) ;;
        --public)     profiles+=(--profile public) ;;
        *) usage; exit 2 ;;
      esac
    done
    ensure_env
    # keep optional services that already run
    if running prometheus && [[ " ${profiles[*]-} " != *" monitoring "* ]]; then profiles+=(--profile monitoring); fi
    if running caddy && [[ " ${profiles[*]-} " != *" public "* ]]; then profiles+=(--profile public); fi
    if [[ " ${profiles[*]-} " == *" public "* ]]; then
      [[ -n "${AUTOMIND_DOMAIN:-}" ]] || die "--public needs AUTOMIND_DOMAIN=<your domain> in .env.docker (see docs/review-2026-11-03.md first)"
    fi
    if [[ " ${profiles[*]-} " == *" monitoring "* ]]; then write_metrics_token; fi
    port_free
    say "Building the image"
    compose build --pull app
    say "Starting Postgres and the app (migrations run at container start)"
    compose ${profiles[@]+"${profiles[@]}"} up -d --remove-orphans
    wait_healthy
    if [[ " ${profiles[*]-} " == *" monitoring "* ]]; then
      curl -fsS -X POST "http://127.0.0.1:${AUTOMIND_PROMETHEUS_PORT:-9090}/-/reload" >/dev/null 2>&1 || true
      say "Prometheus: http://127.0.0.1:${AUTOMIND_PROMETHEUS_PORT:-9090}  Alertmanager: http://127.0.0.1:${AUTOMIND_ALERTMANAGER_PORT:-9093}"
    fi
    if [[ " ${profiles[*]-} " == *" public "* ]]; then say "Public: https://${AUTOMIND_DOMAIN}"; fi
    ;;
  down)    ensure_env; compose "${ALL_PROFILES[@]}" down ;;
  restart) ensure_env; compose restart app; wait_healthy ;;
  status)
    ensure_env
    compose "${ALL_PROFILES[@]}" ps
    curl -fsS "$(url)/api/v1/health" >/dev/null && say "health: ok ($(url))" || echo "health: unreachable"
    ;;
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
    f="${1:-}"; [[ -f "$f" ]] || die "usage: scripts/deploy.sh restore backups/<file>.sql.gz"
    compose stop app
    gunzip -c "$f" | compose exec -T postgres psql -q -U automind -d automind -v ON_ERROR_STOP=1 >/dev/null
    compose start app
    wait_healthy
    ;;
  destroy)
    ensure_env
    read -r -p "Delete the AutoMind database volume (project ${COMPOSE_PROJECT_NAME:-automind})? Type 'yes': " a
    [[ "$a" == "yes" ]] || die "aborted"
    compose "${ALL_PROFILES[@]}" down -v
    ;;
  monitoring)
    ensure_env
    case "${1:-up}" in
      up)     monitoring_up ;;
      down)   compose --profile monitoring rm -f -s prometheus alertmanager ;;
      status) monitoring_status ;;
      *)      die "usage: scripts/deploy.sh monitoring up|down|status" ;;
    esac
    ;;
  export)
    out=""; enc=0
    for a in "$@"; do
      case "$a" in
        --encrypt) enc=1 ;;
        -*) usage; exit 2 ;;
        *) out="$a" ;;
      esac
    done
    out="${out:-backups/automind-bundle-$(date +%Y%m%d-%H%M%S).tar.gz}"
    ensure_env
    do_export "$out" "$enc"
    say "Bundle written: $EXPORTED (mode 600; it holds your API keys and passwords: keep it private)"
    ;;
  import)
    bundle=""; force=0; mon=0
    for a in "$@"; do
      case "$a" in
        --force) force=1 ;;
        --monitoring) mon=1 ;;
        -*) usage; exit 2 ;;
        *) bundle="$a" ;;
      esac
    done
    do_import "$bundle" "$force" "$mon"
    ;;
  move)
    [[ -n "${1:-}" ]] || die "usage: scripts/deploy.sh move user@host [dir]"
    do_move "$1" "${2:-~/automind}"
    ;;
  bootstrap) do_bootstrap ;;
  help|-h|--help) usage ;;
  *) usage; exit 2 ;;
esac
