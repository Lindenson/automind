# Quickstart: validating spec 010

Prerequisites: `scripts/dev.sh` (Postgres in Docker, migrations to 0016, API on :8000), `ADMIN_TOKEN` in `.env` (or loopback).

## 1. Automated
```bash
scripts/check.sh                       # ruff, mypy domain + new pure packages, import-linter (new contracts), pytest, frontend tests
cd backend && uv run pytest tests/golden -q          # g1–g12 unchanged (registry.autonomy: false)
uv run pytest tests/unit/test_outcome.py tests/unit/test_registry_*.py tests/unit/test_insight_clusters.py -q
uv run pytest tests/integration/test_registry_seed.py tests/integration/test_insight_loop.py tests/integration/test_admin_api.py -q
uv run pytest tests/graph/test_turn_outcomes.py -q   # rephrase → not_understood; thanks → score > 0.5; error → process_failure
```
Expected: all green; the scenario test `fixtures/scenarios/registry` shows classifieds and terms-forbid sites blocked with evidence, a usable site candidate → active after N runs, a revert restoring candidate.

## 2. Observation by hand
1. Open a chat, ask a comparison, then write a rephrase of the same question.
2. `psql … -c "select request_kind, relation_next, failure_classes, score from turn_outcomes order by created_at desc limit 3"` → first turn `relation_next=rephrase`, class `not_understood`.
3. In the report press "bad source" on one source and "wrong?" on one value, rate the report 2 with a note → three rows in `feedback`.
4. `select role, model, primary_model, fallback, prompt_name, prompt_version from llm_calls order by created_at desc limit 5` → filled.

## 3. Admin page
1. Open `http://127.0.0.1:8000/admin`, enter the token.
2. Overview shows the index per kind of request and the class shares; without the token the API answers 403.
3. Issues: run the analysis now (`POST` not exposed; use `uv run python -m automind.insight.loop --once`) → seeded 009 issues and any new groups appear; "copy for Claude Code" gives a markdown task with examples and a verify step.
4. Mark an issue fixed; feed two more failures of the same key (test helper) and run once more → status `regression`.

## 4. Registry
1. `uv run python -m automind.acquisition.registry.application.seed` (idempotent) → Sources tab lists ~200 sites; classifieds/terms-forbid are `blocked` with quotes.
2. With `registry.autonomy: false` run a research chat → same favourites order as before (compare `research_jobs.queries`).
3. Set `registry.autonomy: true`, run `uv run python -m automind.acquisition.registry.application.review --once` → Changes tab lists changes with reasons; freeze a source, re-run → its change shows "held: frozen"; revert a change → capability returns to its previous status.

## 5. Metrics and alerts
1. `curl -H "Authorization: Bearer $METRICS_TOKEN" http://127.0.0.1:8000/metrics | grep automind_` → counters and gauges of `contracts/metrics.md`; without the token from outside the local network → 403.
2. Admin: Complaints, Inaccuracies, Self-diagnostics and Sources tabs show daily series (`/api/v1/admin/series`).
3. Test helper `uv run python -m automind.insight.alerts.evaluate --once` after seeding a complaint spike and a degraded source → two firing alerts, badge on every tab; webhook (e.g. `ALERT_WEBHOOK_URL=http://127.0.0.1:9999` with `nc -l 9999`) receives two JSON posts; clearing the seed and re-running resolves both.
4. Stop the insight loop (test flag) for > 2 intervals → `loop_stale` fires in-app and `AutomindLoopStale` fires in Prometheus.
5. `docker compose --profile monitoring up -d` → Prometheus on :9090 shows the target UP and the rules loaded from `deploy/prometheus/automind-rules.yml`.
6. `uv run pytest tests/unit/test_alert_rules_sync.py` → generated rules equal the committed file.
