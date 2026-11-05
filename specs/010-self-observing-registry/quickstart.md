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
1. Open `http://127.0.0.1:8000/admin`, enter the token; without it the API answers 403.
2. Run the analysis now: `uv run python -m automind.insight.loop --once` → **Top problems** lists at most 10 issues by impact (seeded 009 issues included), each with a fix marked `code` or `config` (config fixes name an existing file and key); opening one gives examples and "copy for Claude Code".
3. Mark an issue fixed; feed two more failures of the same key (test helper) and run once more → status `regression`.

## 4. Registry
1. `uv run python -m automind.acquisition.registry.application.seed` (idempotent) → Sources tab lists ~200 sites; classifieds/terms-forbid are `blocked` with quotes.
2. With `registry.autonomy: false` run a research chat → same favourites order as before (compare `research_jobs.queries`).
3. Set `registry.autonomy: true`, run `uv run python -m automind.acquisition.registry.application.review --once` → **Sources** shows scores per kind of data and recent changes with reasons; freeze a source, re-run → its change shows "held: frozen"; revert a change → capability returns to its previous status.

## 5. Prometheus
1. `curl -H "Authorization: Bearer $METRICS_TOKEN" http://127.0.0.1:8000/metrics | grep automind_` → metrics of `contracts/metrics.md`; without the token from outside the local network → 403.
2. `uv run pytest tests/unit/test_prom_rules.py` → rules parse; every metric they use is exported.
3. `docker compose --profile monitoring up -d` → Prometheus on :9090: target `automind` UP, rules loaded.
4. Seed a complaint spike and a demoted source → `AutomindComplaintSpike` and `AutomindSourceDegraded` fire; stop the insight loop (test flag) for > 2 intervals → `AutomindLoopStale` fires.
