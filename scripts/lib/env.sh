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

ensure_db_secret() {
  if [[ ! -f .env.docker ]]; then
    say "Creating .env.docker with a generated database password"
    (umask 077; printf 'POSTGRES_PASSWORD=%s\n' "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" > .env.docker)
  fi
  set -a; . ./.env.docker; set +a
}
