#!/usr/bin/env bash
# One-time copy of the embedded development database (./.pgdata, pgserver) into the Docker Postgres
# (spec 003 US5, FR-025). Compares row counts of every table before and after and fails on a mismatch.
# ./.pgdata is left untouched; delete it yourself once you are happy.
#   scripts/migrate-embedded.sh          copy (replaces the data in the Docker database)
#   scripts/migrate-embedded.sh --check  only print the counts of both databases
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
. scripts/lib/env.sh
check_only=0; [[ "${1:-}" == "--check" ]] && check_only=1

[[ -d .pgdata/pg ]] || die "no embedded database in ./.pgdata/pg"
if pgrep -x automind-api >/dev/null && [[ $check_only == 0 ]]; then
  die "the API is running; stop it first (it may write while the copy runs)"
fi
docker_cmd
ensure_db_secret
"${DOCKER[@]}" compose up -d postgres >/dev/null
for _ in $(seq 1 60); do
  "${DOCKER[@]}" compose exec -T postgres pg_isready -U automind -d automind >/dev/null 2>&1 && break; sleep 1
done

PG=(uv run --no-project --python 3.12 --with pgserver python)
BIN=$("${PG[@]}" -c "import pgserver, pathlib; s=pgserver.get_server('.pgdata/pg', cleanup_mode=None); \
print(pathlib.Path(pgserver.__file__).parent / 'pginstall' / 'bin')" 2>/dev/null | tail -1)
SOCK="$PWD/.pgdata/pg"
[[ -x "$BIN/pg_dump" ]] || die "pg_dump not found in $BIN"

counts_src() {
  "$BIN/psql" -h "$SOCK" -U postgres -d automind -tAF'|' -c \
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1" |
  while read -r t; do printf '%s|%s\n' "$t" "$("$BIN/psql" -h "$SOCK" -U postgres -d automind -tAc "SELECT count(*) FROM \"$t\"")"; done
}
counts_dst() {
  local tables
  tables=$("${DOCKER[@]}" compose exec -T postgres psql -U automind -d automind -tAc \
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1")
  for t in $tables; do
    printf '%s|%s\n' "$t" "$("${DOCKER[@]}" compose exec -T postgres psql -U automind -d automind -tAc "SELECT count(*) FROM \"$t\"")"
  done
}

before=$(counts_src)
if [[ $check_only == 1 ]]; then
  echo "embedded:"; echo "$before"; echo; echo "docker:"; counts_dst; exit 0
fi
dump=$(mktemp --suffix=.dump)
trap 'rm -f "$dump"' EXIT
say "Dumping the embedded database"
"$BIN/pg_dump" -h "$SOCK" -U postgres -d automind --format=custom --no-owner --no-privileges -f "$dump"
say "Restoring into the Docker database (replaces its data)"
"${DOCKER[@]}" compose exec -T postgres psql -q -U automind -d postgres -c "DROP DATABASE IF EXISTS automind WITH (FORCE)" \
  -c "CREATE DATABASE automind OWNER automind" >/dev/null
"${DOCKER[@]}" compose exec -T postgres pg_restore -U automind -d automind --no-owner --no-privileges --exit-on-error < "$dump"
after=$(counts_dst)
if [[ "$before" != "$after" ]]; then
  diff <(echo "$before") <(echo "$after") >&2 || true
  die "row counts differ (see above); the embedded database is untouched"
fi
say "Copied $(echo "$before" | wc -l) tables, counts match:"
echo "$before" | column -t -s'|'
say "Next: scripts/dev.sh uses the Docker database; scripts/deploy.sh deploys with it."
