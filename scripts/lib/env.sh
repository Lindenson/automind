# Shared by scripts/dev.sh and scripts/deploy.sh: Docker access, .env checks and .env.docker (DB password).
say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

docker_cmd() {
  command -v docker >/dev/null || die "Docker is not installed (https://docs.docker.com/engine/install/)."
  DOCKER=(docker)
  if ! docker info >/dev/null 2>&1; then
    if docker info 2>&1 | grep -q "permission denied"; then
      echo "No access to the Docker daemon for this session (join the 'docker' group and log in again)." >&2
      echo "Falling back to sudo for now." >&2
      DOCKER=(sudo docker)
      "${DOCKER[@]}" info >/dev/null || die "cannot reach the Docker daemon"
    else
      die "the Docker daemon is not running (sudo systemctl start docker)"
    fi
  fi
  "${DOCKER[@]}" compose version >/dev/null 2>&1 || die "Docker Compose v2 plugin is missing (docker compose)."
}

# Value of KEY in an env file (last assignment wins, surrounding quotes stripped); empty when absent.
env_value() {  # env_value FILE KEY
  [[ -f "$1" ]] || return 0
  sed -n "s/^[[:space:]]*\(export[[:space:]]\+\)\?$2=//p" "$1" | tail -n 1 \
    | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

# Model providers in use: role -> "provider:model" lines of models.yaml (top level, plus the models listed in
# `fallbacks:`; the keys of `options:`/`fallbacks:` are not roles) and MODEL_<ROLE> overrides in the env file.
model_providers() {  # model_providers MODELS_YAML ENV_FILE
  {
    awk '
      /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
      /^[^[:space:]]/ { section = ""; if ($0 ~ /^(options|fallbacks):/) { section = $1; next } }
      { sub(/[[:space:]]+#.*/, "") }
      section == "" && /^[A-Za-z_][A-Za-z0-9_]*:[[:space:]]*[A-Za-z_]+:/ {
        v = $0; sub(/^[^:]*:[[:space:]]*/, "", v); sub(/:.*/, "", v); print v; next }
      section == "fallbacks:" {
        v = $0; sub(/^[^:]*:[^:]*:/, "", v); n = split(v, a, /[][,[:space:]]+/)
        for (i = 1; i <= n; i++) if (a[i] ~ /^[A-Za-z_]+:/) { sub(/:.*/, "", a[i]); print a[i] } }
    ' "$1"
    if [[ -f "$2" ]]; then
      sed -n "s/^[[:space:]]*\(export[[:space:]]\+\)\?MODEL_[A-Z0-9_]*=[\"']\?\([A-Za-z_]*\):.*/\2/p" "$2"
    fi
  } | sort -u
}

# Returns 1 and names exactly the missing keys (values are never printed).
check_api_keys() {  # check_api_keys ENV_FILE MODELS_YAML SEARCH_YAML
  local env="$1" missing=() p sp key
  for p in $(model_providers "$2" "$env"); do
    case "$p" in
      google_genai) [[ -n "$(env_value "$env" GOOGLE_API_KEY)" || -n "$(env_value "$env" GEMINI_API_KEY)" ]] \
                      || missing+=("GOOGLE_API_KEY (or GEMINI_API_KEY) for google_genai models") ;;
      openai)       [[ -n "$(env_value "$env" OPENAI_API_KEY)" ]] || missing+=("OPENAI_API_KEY for openai models") ;;
      anthropic)    [[ -n "$(env_value "$env" ANTHROPIC_API_KEY)" ]] || missing+=("ANTHROPIC_API_KEY for anthropic models") ;;
      *)            echo "note: unknown model provider '$p'; its key is not checked." >&2 ;;
    esac
  done
  sp="$(env_value "$env" SEARCH_PROVIDER)"
  [[ -n "$sp" ]] || sp="$(sed -n 's/^provider:[[:space:]]*\([A-Za-z_]*\).*/\1/p' "$3" | head -n 1)"
  case "$sp" in
    serper)  key=SERPER_API_KEY ;;
    serpapi) key=SERPAPI_API_KEY ;;
    tavily)  key=TAVILY_API_KEY ;;
    *)       key=""; echo "note: unknown search provider '$sp'; its key is not checked." >&2 ;;
  esac
  [[ -z "$key" || -n "$(env_value "$env" "$key")" ]] || missing+=("$key for search provider $sp")
  if ((${#missing[@]})); then
    printf '\033[31merror:\033[0m missing in %s:\n' "$env" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    return 1
  fi
}

# .env.docker: generated secrets (POSTGRES_PASSWORD, ADMIN_TOKEN, METRICS_TOKEN); existing values are kept.
ensure_db_secret() {
  local item name len
  [[ -f .env.docker ]] || say "Creating .env.docker with generated secrets"
  for item in POSTGRES_PASSWORD:24 ADMIN_TOKEN:16 METRICS_TOKEN:16; do
    name="${item%%:*}"; len="${item#*:}"
    if ! grep -Eq "^${name}=.+" .env.docker 2>/dev/null; then
      [[ -f .env.docker ]] && say "Adding a generated $name to .env.docker"
      (umask 077; printf '%s=%s\n' "$name" "$(head -c "$len" /dev/urandom | od -An -tx1 | tr -d ' \n')" >> .env.docker)
    fi
  done
  set -a; . ./.env.docker; set +a
}
