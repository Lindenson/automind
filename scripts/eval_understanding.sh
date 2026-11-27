#!/usr/bin/env bash
# Spec 013 T006: the nightly understanding eval — the golden message set (148 cases) on today's interpreter.
#
# Paid (≈ €1.15 per run on gemini-3.6-flash, one interpreter call per case). Writes, under eval-runs/understanding/
# (gitignored): <date>.md (the report, same format as specs/013-dialogue-quality/baseline.md), <date>.json (per case)
# and latest.json (the summary). The app reads latest.json (mounted at /eval-runs) and exports
# automind_understanding_eval_* gauges; the rule AutomindUnderstandingEvalStale fires when no run finished for 36 h.
# Usage rows of the model calls go to the pre-prod database (chat_id empty), so the spend shows in /admin.
#
# Cron (host, owner's machine): 30 3 * * * <repo>/scripts/eval_understanding.sh >> <repo>/eval-runs/understanding/cron.log 2>&1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/eval-runs/understanding"
mkdir -p "$OUT"
exec 9>"$OUT/.lock"
flock -n 9 || { echo "$(date -Is) another eval is running"; exit 0; }
set -a; . "$ROOT/.env.docker"; set +a
export DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@127.0.0.1:${AUTOMIND_DB_PORT:-5433}/automind"
DAY="$(date +%F)"
cd "$ROOT/backend"
echo "$(date -Is) understanding eval start"
"${UV:-$HOME/.local/bin/uv}" run python -m tests.eval.understanding.runner \
  --out "$OUT/$DAY.md" --summary "$OUT/latest.json.tmp"
mv "$OUT/latest.json.tmp" "$OUT/latest.json"
echo "$(date -Is) understanding eval done: $(head -c 300 "$OUT/latest.json" | tr -d '\n')"
