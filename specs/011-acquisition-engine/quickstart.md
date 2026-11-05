# Quickstart: validating spec 011

Prerequisites: `scripts/dev.sh` (Postgres in Docker, migrations to the latest (0018–0024), API on :8000, worker
started unless `--no-worker`), `ADMIN_TOKEN` in `.env` (or loopback). Paths relative to `backend/`.

## 0. Automated (every stage)
```bash
scripts/check.sh                                   # ruff, mypy, import-linter (new contracts), pytest, frontend tests
cd backend && uv run pytest tests/golden -q        # g1–g12 unchanged — after EVERY strangler step and every stage
```

## 1. Measurability (US1)
```bash
uv run pytest tests/unit/test_snapshot_codec.py tests/unit/test_gold_match.py tests/unit/test_replay_compare.py -q
uv run pytest tests/integration/test_snapshots.py tests/integration/test_gold_load.py tests/integration/test_replay.py -q
```
By hand:
1. Ask for a car report in the chat. `select count(*), sum(stored_bytes)::float/sum(raw_bytes) from page_snapshots
   join snapshot_blobs on blob_sha256=sha256 where fetched_at > now()-interval '10 min'` → rows, ratio ≈ 0.1–0.2.
2. `select producer, producer_version, model, snapshot_id is not null from claims order by created_at desc limit 10`
   → every row filled (SC-002).
3. `uv run python -m automind.acquisition.gold.load --dataset reference_set` and (network) `--dataset eea_co2`
   → `gold_datasets` rows; `select attribute, count(*) from gold_values group by 1`.
4. **Independent test (US1)**: `uv run pytest tests/integration/test_replay.py::test_v1_vs_broken_v2` — three cars'
   stored km77 pages + gold; `km77@v1` accuracy ≥ 0.9 and yield > 0; the broken v2 (labels swapped) lists the wrong
   values; the socket guard records 0 network calls.
5. `uv run python -m automind.acquisition.replay --reader km77@v1 --since 30d --json` on your own data → report in
   seconds (SC-001).

## 2. Separation and worker (US2)
```bash
uv run pytest tests/unit/test_architecture.py tests/unit/test_no_acquisition_calls_in_chat.py -q
uv run pytest tests/integration/test_task_queue.py tests/integration/test_worker.py tests/integration/test_prefetch.py -q
```
By hand:
1. `docker compose up -d worker` (or dev.sh). `select kind, state, count(*) from acq_tasks group by 1,2`.
2. **Independent test (US2)**: stop the API (`pkill -x automind-api` / `docker compose stop app`). Within 2 minutes
   `metrics_snapshot` tasks keep completing; `uv run python -m automind.acquisition.worker --once registry_review`
   journals a run. Start the API again; ask a report; `lint-imports` passes with no `research` ignore lines.
3. `wc -l src/automind/application/research.py` → the file no longer exists after S7.

## 3. Honest reputation (US3)
```bash
uv run pytest tests/unit/test_physics.py tests/unit/test_blame_vector.py tests/unit/test_thompson.py tests/unit/test_registry_lifecycle.py -q
uv run pytest tests/integration/test_honest_reputation.py -q
```
**Independent test (US3)**: fixture scenario `tests/fixtures/scenarios/honest/` — source `fastwrong.example` (yield
0.9, 30 % wrong vs gold) and `honest.example` (yield 0.5, right); after 40 simulated jobs `fastwrong` is never
`active` and ranks below `honest`; a wrong value whose right number is in the snapshot lowers
`component_reputation(parser, …)` and leaves the source's `wrong_w` unchanged.

Baseline: `select name, started_at, ended_at from kpi_baselines` → a 7-day row exists before the owner sets
`registry.autonomy: true` (T-task with owner gate).

## 4. Parsers and drift (US4)
```bash
uv run pytest tests/unit/test_parser_spec.py tests/unit/test_parser_v1_equivalence.py tests/unit/test_fingerprint.py tests/unit/test_drift.py -q
uv run pytest tests/integration/test_parser_drift.py -q
```
**Independent test (US4)**: `test_parser_drift.py` replaces one site's stored pages from day D with
`tests/fixtures/html/redesign/km77_*.html` (same data, new markup); the next `drift` task marks `km77@v1` degraded
with reason "structure changed" and the fields-per-page drop; five zero pages in a row mark it degraded at once.

## 5. Agents and gates — the simulated redesign (US5, SC-007)
```bash
uv run pytest tests/unit/test_gates.py tests/unit/test_levers.py tests/unit/test_no_self_change.py -q
uv run pytest tests/integration/test_redesign_acceptance.py -q
```
**Acceptance (spec US5 independent test)** — `test_redesign_acceptance.py`, no human action, fake LLM for the
`parser_doctor` role returning a recorded spec:
1. Seed: 50 km77 snapshots of 3 weeks (old markup) + gold for their variants; 20 snapshots after day D with the new
   markup (fixture redesign).
2. Run the worker's `rollup` + `drift` → `km77@v1` degraded, `parser_doctor` task queued.
3. The doctor proposes `km77@v2` → `acq_changes` row `proposed` → `gate_replay` passes (accuracy on gold ≥ 0.9,
   yield on new pages > old) → `gate_shadow` on the next 20 prefetch pages passes → `accepted` → `watch`.
4. The explanation reads like "km77 parser v1→v2: table labels changed on <D>; v2 reproduces 48/50 gold values;
   shadow yield 0.91 vs 0.42" (numbers from the run).
5. A second recorded proposal (`km77@v3`, better yield, worse gold accuracy) is `rejected` at replay with the reason
   journalled.
6. Simulate degradation in watch (inject 3 wrong signals blamed to `km77@v2`) → evaluator rolls back to the previous
   active version, journalled `rolled_back`.
7. `select count(*) from acq_changes where object_kind not in ('parser','prompt','role_model','rule','source')` → 0;
   no file under `config/` changed (`git status --porcelain backend/config` empty) — SC-008.

## 6. Admin (US6)
```bash
uv run pytest tests/integration/test_admin_engine_api.py -q
cd ../frontend && npm test -- admin
```
By hand: open `/admin` → **Parsers** shows `km77` with versions, daily chart, drift marker, canary; **Changes** lists
the redesign change with its one-sentence explanation; **Revert** restores the previous version. Drill-down: Accuracy
KPI → `parser:km77@v1` → a wrong value → page text with the quote highlighted (3 clicks, SC-010).

## 7. 010 leftovers (US7)
```bash
uv run pytest tests/integration/test_unverified_label.py tests/integration/test_nodata_tried.py -q
test ! -e src/automind/domain/learned.py && echo "learned rule removed"
```
A report with a candidate-sourced value shows "unverified source"; a "no data" area lists the sources tried.
