# Tasks: Self-Observing AutoMind and an Autonomous Source Registry

**Input**: design documents in `specs/010-self-observing-registry/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (admin-api, ws-feedback, metrics, registry-port), quickstart.md

**Tests**: the spec gives an Independent Test per story and asks for pure, testable cores (constitution IX); test tasks are included and written before the code they cover.

Paths are relative to `backend/` unless they start with `frontend/`, `deploy/`, `specs/`, `docs/` or `scripts/`.

**Hard rule for every task** (constitution XII, spec FR-010, FR-024): nothing written here may give the system a write path to code, prompts, parsers, rules or YAML configuration. Source registry rows are the only thing the system changes by itself.

## Phase 1: Setup

- [X] T001 Add `prometheus-client` to `pyproject.toml` dependencies (`uv add prometheus-client`), lock it, and confirm `scripts/check.sh` still passes.
- [X] T002 [P] Create package skeletons with `__init__.py`: `src/automind/insight/{domain,application,infrastructure,metrics}/`, `src/automind/acquisition/__init__.py`, `src/automind/acquisition/registry/{domain,application,infrastructure}/`.
- [X] T003 [P] Add import-linter contracts to `.importlinter`: `insight-domain-pure` and `registry-domain-pure` (same forbidden list as `domain-pure`); `registry-boundary` (forbid `automind.application`, `automind.orchestration`, `automind.api` from importing `automind.acquisition.registry.*` except `automind.acquisition.registry.api`); `registry-no-chat` (forbid `automind.acquisition` from importing `automind.orchestration`, `automind.domain.casefile`); `insight-independent` (forbid `automind.insight` from importing `automind.orchestration` and `automind.acquisition.registry.application`). Keep `tests/unit/test_architecture.py` ignore count unchanged.
- [X] T004 [P] Add config files with defaults from research.md: `config/outcome.yaml` (R3 signal weights, start 0.6, class severities of R15), `config/insight.yaml` (R6 thresholds per component, `budget_eur: 0.30`, early-run trigger `new_failures: 10`, top N 10, impact formula weights, `levers:` map of R15, `files:` map component → likely files), `config/registry.yaml` (R9 priors, weights 1/0.7/0.3, `half_life_days: 90`, lifecycle thresholds, `candidate_slots: 1`, `retired_retry_days: 30`, `recheck_days: {active: 90, blocked: 180}`, `discovery_eur_per_day: 0.20`, `discovery_per_gap_per_day: 3`, `min_active_per_area_market: 2`, `autonomy: false`). Load each through `src/automind/infrastructure/config.py` (`load_yaml`, typed accessors) and expose them on `Reference`.

## Phase 2: Foundational (blocking)

- [X] T005 Write migration `alembic/versions/0014_observation.py` (revision `0014`, down `0013`): add to `llm_calls` `primary_model text null`, `fallback bool not null default false`, `prompt_name text null`, `prompt_version text null`, `prompt_hash text null`; create `turn_outcomes` and `feedback` exactly as in data-model.md (`turn_id` PK FK turns cascade; `feedback.kind` in `rating, wrong_value, bad_source, complaint, rephrase, correction`; `feedback.text` ≤ 1000 chars; indexes on `chat_id`, `created_at`). Add matching models to `src/automind/infrastructure/db/models.py`; add both tables to `ChatRepo.CHAT_SCOPED` deletion in `src/automind/infrastructure/db/repositories.py`.
- [X] T006 Write migration `alembic/versions/0015_insight.py`: `issues` (`fingerprint` unique; `status` in `open, acknowledged, fixed, wontfix, regression`; `impact real`; `diagnosis jsonb` shaped `{summary, likely_cause, fix: {kind: code|config, files[], config_file, config_key, suggested_value, direction}, verify}`; `examples jsonb` ≤ 10 items; `source` `auto` or `seed:009`) and `insight_runs`; models in `models.py`.
- [X] T007 Write migration `alembic/versions/0016_registry.py`: `sources`, `capabilities` (unique `(domain, area, market)`; `status` in `discovered, candidate, active, degraded, retired, blocked`), `registry_attempts` (`outcome` in `accepted, rejected, robots, junk, empty, error`), `truth_signals` (`kind` in `challenge, bad_source, replacement, agreement, gold`; `verdict` right|wrong; `blame` in `source, parser, extractor, relevance, check, fusion`), `registry_changes` (`author` system|owner; `held bool default false`; `reverted_by uuid null`), `registry_runs`; models in `models.py`. Extend `infrastructure/retention.py` to delete `registry_attempts` older than 180 days.
- [X] T008 Extend `tests/integration/test_migrations.py` so upgrade to `0016` and downgrade to `0013` both run on `automind_mig`.
- [X] T009 Create the Prometheus registry module `src/automind/insight/metrics/prom.py`: all counters and histograms of contracts/metrics.md (names, types, labels exactly as listed), a `Snapshot` dataclass holding the gauge values, and a custom collector that yields the gauges from the last snapshot only (no DB access, FR-031). Add `src/automind/insight/metrics/heartbeat.py`: `beat(loop, ok: bool, interval_s)` updating in-memory `last_success`, `fails_in_row`, `interval` for `automind_loop_*`.
- [X] T010 Add `GET /metrics` in `src/automind/api/metrics.py` and include it in `api/app.py`: `Authorization: Bearer <METRICS_TOKEN>` (new setting `metrics_token` in `src/automind/config.py`), else allow only clients in `AUTOMIND_METRICS_NETS` (default `127.0.0.0/8,172.16.0.0/12`); 403 otherwise. Wrap `retention_loop` with `heartbeat.beat("retention", …)`. Add `METRICS_TOKEN=` and `ALERT…` none — only `METRICS_TOKEN` — to `.env.example`.
- [X] T011 [P] Unit test `tests/unit/test_metrics_endpoint.py`: token accepted, wrong token 403, loopback allowed without token, scrape does not touch the DB (patch the session factory to raise).

## Phase 3: User Story 1 — every turn leaves a scored outcome (P1) 🎯 MVP

**Goal**: one `turn_outcomes` row per turn with classes, signals and a 0–1 score; `relation` from the interpreter; prompt identity and fallback per model call.

**Independent test**: graph replay with recorded answers: rephrase after turn 1 → turn 1 `not_understood`, score < 0.5; "thanks" after turn 2 → score > 0.5; a failing turn → `process_failure`.

- [X] T012 [P] [US1] Unit tests `tests/unit/test_outcome.py` for `domain/outcome.py`: rating 5 → 1.0 and rating 1 → 0.0 regardless of signals; each class rule of the spec US1 table; rephrase lowers and thanks raises; clamp to [0,1]; last turn without a next message uses only its own signals.
- [X] T013 [US1] Implement `src/automind/domain/outcome.py` (pure): `FailureClass` enum (`not_understood, wrong_car, no_data, wrong_data, bad_text, process_failure, too_costly`), `TurnFacts` dataclass (status, action, limits_reached, guard_removed, nodata items, intake corrections/card edits/refusals, not_found, feedback counts, relation_next, rating), `classes(facts)`, `score(facts, weights)` per research R3, weights from `config/outcome.yaml`.
- [X] T014 [US1] Add `relation` to `Interpretation` in `src/automind/application/interpret.py` (`Literal["continues","rephrase","correction","complaint","thanks","new_topic"]`, default `continues`, description of each value); add the relation rules and six few-shots (ru/es/en) to `src/automind/orchestration/prompts/interpreter.md` and bump its header to `interpreter v3`. Carry `relation` into the turn's final state in `orchestration/nodes/understand.py`.
- [X] T015 [US1] Record prompt identity in `src/automind/infrastructure/llm_gateway.py`: a contextvar `current_prompt` set in `structured()` (and the other public call helpers) to `(prompt_name=role, prompt_version parsed from the first-line comment "<!-- prompt: <name> v<N> …", prompt_hash=sha256(system)[:12])`; `UsageCallbackHandler` in `infrastructure/usage_callback.py` writes `primary_model=model_name(role)`, `fallback=(model != primary_model)` and the prompt fields via `UsageRepo.record_llm` (extend its signature in `repositories.py`). Increment `automind_llm_calls_total`, `automind_llm_cost_eur_total`, and `automind_llm_errors_total{kind}` in `on_llm_error`/`mark_exhausted`.
- [X] T016 [US1] Add `OutcomeRepo` to `src/automind/infrastructure/db/repositories.py`: `create(turn_id, chat_id, facts, score, classes, path, …)`, `patch_previous(chat_id, relation)`, `add_signal(turn_id, key, delta)`, `facts(turn_id)`, all recomputing `score` through `domain/outcome.py`; `settings_version` = hash of `models.yaml` text + prompt hashes loaded at startup. Add an `OutcomeStore` Protocol and `Ports.outcomes: OutcomeStore | None = None` in `application/ports.py`, wired in `infrastructure/adapters.py:live_ports`.
- [X] T017 [US1] Collect the turn path: append node names to a reducer list field `path` in `orchestration/state.py` (one `add` reducer), set by a tiny wrapper in `orchestration/graph.py` around each node; record `guard_removed` count in final state from `orchestration/nodes/report.py` (where `guard.sentences_removed` is logged); record the "no data" items composed into the report.
- [X] T018 [US1] Write outcomes in `src/automind/orchestration/runner.py`: in `_done`, the FAILED path, `_waiting` and `cancel`, call `ports.outcomes.create(...)`; at the start of a new turn, after interpretation, call `patch_previous(chat_id, relation)` so the previous turn gets `relation_next`; increment `automind_turns_total`, `automind_turn_duration_seconds`, `automind_turn_failures_total{class}`. Errors in outcome writing are logged and never fail the turn.
- [X] T019 [US1] Graph test `tests/graph/test_turn_outcomes.py` implementing the independent test above with the fake LLM (cassettes include `relation`), plus a check that `llm_calls` rows carry `prompt_name`, `prompt_version` and `fallback` (fake quota error on the primary model → `fallback=true`).
- [X] T020 [US1] Re-record or extend golden cassettes in `tests/golden/cassettes/*/` so interpreter outputs include `relation` (default `continues` where absent is fine — verify `tests/golden` passes unchanged).

**Checkpoint**: every turn has an outcome; Prometheus shows turn counters.

## Phase 4: User Story 2 — "bad source" and one feedback table (P1)

**Goal**: all user signals in `feedback`; a new "bad source" action.

**Independent test**: press "bad source", "wrong?", and rate 2 with a note on one stored report → three `feedback` rows with car, attribute, source; the outcome of that turn gets `wrong_data`.

- [ ] T021 [P] [US2] Integration test `tests/integration/test_feedback.py`: rating writes `report_ratings` and `feedback(kind=rating)` and patches the turn score; challenge writes `feedback(kind=wrong_value, outcome)` and fills `value_challenges.turn_id` and `claim_id`; `bad_source` for a deny-listed URL is acked with `ignored: true`; > 20 bad_source per chat per hour ignored.
- [ ] T022 [US2] Add `FeedbackRepo.add(...)` in `repositories.py`; make `RatingRepo.save` also write feedback and call `OutcomeRepo.add_signal(turn_of(message_id), "rating", r)`; increment `automind_feedback_total{kind}`.
- [ ] T023 [US2] Update `src/automind/application/challenge.py`: resolve the latest DONE turn of the chat and the first claim behind the value; store them in `value_challenges`; write `feedback(kind=wrong_value, outcome)`; patch the outcome (`wrong_data` on CORRECTED/REMOVED); keep the result shape unchanged. Leave `rs._check` use as is (the registry signals come in T060).
- [ ] T024 [US2] Handle WS `bad_source` in `src/automind/api/ws.py` per contracts/ws-feedback.md: validate fields (url required, text ≤ 1000), rate limit 20/chat/hour in memory, write feedback, patch outcome (`bad_source` signal, class `wrong_data`), publish `feedback_ack`. Registry truth signal is added in T060.
- [ ] T025 [US2] Write `complaint`, `rephrase`, `correction` feedback rows from the runner when `relation` is one of them or `request_kind=critique` (`runner.py`, same place as T018).
- [ ] T026 [P] [US2] Frontend: add `BadSourceOut` and `FeedbackAckSchema` (zod) to `frontend/src/lib/protocol.ts`; a `badSource(url, carId?, attribute?, area?)` action in `frontend/src/store/chat.ts`; a small "bad source" button on accepted items in `SourceItem` (`frontend/src/components/badges.tsx`) that turns into "noted" on ack; ru/es/en strings in `frontend/src/i18n`. Component test in `frontend/src/components/__tests__/badSource.test.tsx`.

**Checkpoint**: all feedback in one table; `automind_feedback_total` moves.

## Phase 5: User Story 9 (part 1) — Prometheus snapshot and loop health (P1)

**Goal**: the slow KPIs and loop heartbeats exported; no DB on scrape.

**Independent test**: seed outcomes, feedback and capabilities; run the snapshot once; `/metrics` shows the matching `automind_satisfaction_index`, `automind_complaints_24h`, `automind_accuracy_share`, `automind_loop_last_success_timestamp_seconds`.

- [ ] T027 [P] [US9] Integration test `tests/integration/test_metrics_snapshot.py` implementing the independent test.
- [ ] T028 [US9] Implement `src/automind/insight/metrics/snapshot.py`: `async refresh() -> Snapshot` with SQL over `turn_outcomes` (index per kind/language/persona, 7d and 30d), `feedback` (24h, 30-day daily average), `truth_signals` (accuracy per area), outcomes `no_data` (nodata share per area), `capabilities` (counts, active per area×market, per-source score/acc_lb/yield for candidate/active/degraded), `llm_calls` (fallback share per role 1h/7d), `site_reader_stats` (zero streak per reader), spend today (reuse `TurnRepo.spent_today`) and `daily_cap_eur`, background spend per loop, `issues` by component/status. Tables that do not exist yet return empty sets.
- [ ] T029 [US9] Add `metrics_loop()` (every 60 s, `heartbeat.beat("metrics")`) in `src/automind/insight/metrics/snapshot.py` and start it in `api/app.py` lifespan next to `retention_loop`; cancel it on shutdown like retention.
- [ ] T030 [US9] Increment live counters at the remaining write points: `automind_search_calls_total` in `infrastructure/search/cache.py` (`record_search`), `automind_fetch_total{outcome}` in `infrastructure/fetch.py` (ok, robots, denied, error, timeout), `automind_research_jobs_total` in `application/research.py:run_job` via a port-free callback set by adapters (keep `application` free of `prometheus_client`: add `Ports.metrics: Any = None` with `inc(name, **labels)`; `live_ports` passes `insight.metrics.prom.inc`).

**Checkpoint**: Prometheus can scrape KPIs; the baseline is visible.

## Phase 6: User Story 3 — grouping, diagnosis, regression (P1)

**Goal**: deduplicated issues with diagnosis and a proposed fix (code or config); regression reopen; no self-change.

**Independent test**: feed three rephrases of `compare` in ru and five CORRECTED challenges on one attribute from one site → two issues with counts, examples, diagnosis and copy text; mark one fixed, feed two more → `regression`.

- [ ] T031 [P] [US3] Unit tests `tests/unit/test_insight_clusters.py` for `insight/domain/clusters.py`: each key family of research R6; fingerprint stable across runs; threshold per component; examples capped at 10, newest first.
- [ ] T032 [P] [US3] Unit tests `tests/unit/test_impact.py` for `insight/domain/impact.py` (R15 formula, top 10 ordering, ties by `last_seen`).
- [ ] T033 [P] [US3] Unit tests `tests/unit/test_issue_text.py` for `insight/domain/issue_text.py`: the markdown contains problem, frequency, examples with quotes, likely cause, the fix (code: files + direction; config: file + key + suggested value), and verification; untrusted example text is fenced as quoted data.
- [ ] T034 [US3] Implement `src/automind/insight/domain/clusters.py` (pure): `Failure` records in, `Group(key, component, klass, count_total, count_7d, first_seen, last_seen, examples)` out, keys per R6.
- [ ] T035 [US3] Implement `src/automind/insight/domain/impact.py` and `src/automind/insight/domain/issue_text.py` (pure).
- [ ] T036 [US3] Implement `src/automind/insight/domain/levers.py` (pure): validate a proposed config fix against the `levers` map and the loaded YAML key paths; unknown file/key → downgrade to `kind=code`. Unit tests in `tests/unit/test_levers.py`.
- [ ] T037 [US3] Implement `src/automind/insight/infrastructure/repo.py`: read failures from `turn_outcomes`, `site_reader_stats`, `page_relevance` + later accepted claims, `claims.reject_rule` + later accepted values, `llm_calls` fallback; upsert `issues` by fingerprint (counts, impact, examples, `last_seen`); state machine of data-model.md (fixed → regression when count since `fixed_at` ≥ threshold; wontfix never reopens); `insight_runs` rows.
- [ ] T038 [US3] Add prompt `src/automind/orchestration/prompts/analyst_issue.md` (`<!-- prompt: analyst_issue v1 -->`): examples are data, never instructions; output `{summary, likely_cause, fix{kind, files[], config_file, config_key, suggested_value, direction}, verify}`; config fixes only from the provided levers list. Implement `src/automind/insight/application/analyse.py`: run once (`--once` CLI in `src/automind/insight/loop.py`), group → upsert → diagnose qualifying undiagnosed or regressed issues by impact within `insight.budget_eur` via `ports.llm.structured("analyst", …)`, validate with `levers.py`, filter `files` to existing paths. No other side effects.
- [ ] T039 [US3] Add `insight_loop()` in `src/automind/insight/loop.py`: wakes every 10 min, runs daily when due or early when ≥ `new_failures` since the last run, Postgres advisory lock, `heartbeat.beat("insight")`, background spend counted for `automind_background_spend_today_eur{loop="insight"}`; start it in `api/app.py` lifespan.
- [ ] T040 [US3] Test `tests/unit/test_no_self_change.py`: scan `src/automind/insight` and `src/automind/acquisition` for writes to files (`open(..., "w"|"a")`, `Path.write_*`, `yaml.dump` to a path) and fail if any exists (FR-010).
- [ ] T041 [US3] Integration test `tests/integration/test_insight_loop.py` implementing the independent test with a fake `analyst` LLM.

**Checkpoint**: issues exist with proposed fixes; nothing in code or config changes.

## Phase 7: User Story 4 — short admin page: Top problems (P1)

**Goal**: `/admin` with the Top problems screen; Sources screen added in Phase 11.

**Independent test**: 15 seeded open issues → the 10 highest-impact listed in order with fix kind; no token → 403 on every admin endpoint.

- [ ] T042 [P] [US4] Integration test `tests/integration/test_admin_api.py` (problems part): `GET /api/v1/admin/problems` order and fields per contracts/admin-api.md; `GET /problems/{id}` includes `copy_text`; `PATCH` statuses and `fixed_ref`; 403 without token.
- [ ] T043 [US4] Implement `src/automind/api/admin.py` (router `/api/v1/admin`, every route guarded by `admin_ok`): `GET /problems`, `GET /problems/{id}`, `PATCH /problems/{id}`; include it in `api/app.py`. Serve `index.html` for `/admin` and `/admin/*` (explicit route before the static mount, since `StaticFiles(html=True)` has no SPA fallback).
- [ ] T044 [P] [US4] Frontend admin shell: in `frontend/src/main.tsx` render `<AdminApp/>` when `location.pathname.startsWith("/admin")`; `frontend/src/admin/api.ts` (fetch with `Authorization: Bearer` from `sessionStorage`, token prompt on 403), `frontend/src/admin/store.ts` (zustand), `frontend/src/admin/AdminApp.tsx` (two tabs: Top problems, Sources; Sources placeholder until Phase 11), styles reusing existing Tailwind tokens.
- [ ] T045 [US4] `frontend/src/admin/Problems.tsx` (ranked list: title, frequency, example chat link, fix badge `code`/`config` with file or file+key) and `frontend/src/admin/ProblemCard.tsx` (examples, diagnosis, "copy for Claude Code" using `navigator.clipboard` with a textarea fallback, status buttons, commit ref input). Tests in `frontend/src/admin/__tests__/problems.test.tsx`.

**Checkpoint**: the owner reads top problems and copies tasks.

## Phase 8: User Story 5 — spec 009's open fixes as issues (P2)

**Goal**: the known flaws are in the queue.

**Independent test**: the queue lists every 009 item with its chat and a copy text.

- [ ] T046 [US5] Add `config/seed_issues.yaml` with one entry per 009 flaw and per UX finding F7–F15 of `docs/ux-audit-2026-11-05.md` not covered by US10 (component `ui`, fix kind `code`, files from the report) (spec US5 list; chats 20b5b7f9, 8c6a2a58; component, class, title, examples as quotes from spec 009, proposed fix: code (files from docs/baseline.md) or config (`sense.yaml`/`plausibility.yaml`/`queries.yaml` keys where they apply), verify step) and an idempotent seeder `src/automind/insight/application/seed.py` (`source=seed:009`, fingerprint `seed:<slug>`), run from the insight loop on start.
- [ ] T047 [US5] Test `tests/integration/test_seed_issues.py`: seeding twice gives one row per item; seeded issues appear in `GET /problems` ranked by a fixed seed impact.

## Phase 9: User Story 8 — registry seeded, same behaviour (P2)

**Goal**: registry in DB from favourites, the 009 survey and learned sources; research reads it; reports unchanged.

**Independent test**: after seeding, classifieds and terms-forbid sites are blocked with evidence; goldens unchanged with `autonomy: false`.

- [ ] T048 [P] [US8] Unit tests `tests/unit/test_registry_seed_rules.py` for `acquisition/registry/domain/seed_rules.py`: survey verdict → access/status mapping (`candidate`→candidate, `classifieds`/`tos_forbids`/`blocked`→blocked with evidence, `paywall`/`js_only`/`dead`→retired with access set); favourites → active with `priority_seed`; learned rows meeting the spec-007 rule → active, others candidate; deny-list always wins.
- [ ] T049 [US8] Implement `src/automind/acquisition/registry/domain/{model.py,seed_rules.py,families.py}` (pure): `Source`, `Capability`, `Change` dataclasses; family = configured mirror groups (auto-data/ultimatespecs etc. in `config/registry.yaml: families`) else domain.
- [ ] T050 [US8] Implement `src/automind/acquisition/registry/infrastructure/repo.py` (`RegistryRepo`: sources, capabilities, attempts, signals, changes, runs) and `src/automind/acquisition/registry/application/seed.py` (idempotent; reads `config/sources.yaml` favourites, `specs/009-source-registry/registry-survey.yaml` copied to `config/registry_seed_survey.yaml` so the container has it, and `learned_sources`; journals each insert as `added` with author `system`, reason "seed"). CLI `python -m automind.acquisition.registry.application.seed`.
- [ ] T051 [US8] Implement `src/automind/acquisition/registry/api.py` per contracts/registry-port.md (`PlannedSource`, `Plan`, `Attempt`, `TruthSignalIn`, `RegistryPort`) and `application/planner.py`: with `autonomy: false` the plan reproduces favourites priorities and the learned rule; never returns blocked/deny-listed domains; `record()`/`signal()` never raise.
- [ ] T052 [US8] Reroute `src/automind/application/research.py`: `favourite_priority` reads the job's plan priorities; `learned_sites` returns active non-favourite capabilities from the plan; `_record_learned` → `registry.record(attempts)` with outcomes `accepted/rejected(reason)/robots/junk/empty/error` and `via_learned_query`; add `Ports.registry: RegistryPort | None` (None → today's behaviour from YAML, for test fakes); wire in `live_ports`; remove `Ports.learned` use and mark `domain/learned.py` deprecated (delete in the polish phase once tests no longer import it).
- [ ] T053 [US8] Run seed on startup when the registry is empty (`api/app.py` lifespan, after migrations).
- [ ] T054 [US8] Integration test `tests/integration/test_registry_seed.py` (independent test, counts by verdict) and run `tests/golden` with the registry port wired: results unchanged.

**Checkpoint**: storage changed, behaviour not.

## Phase 10: User Story 6 — score per capability, order by score (P1)

**Goal**: yield, decayed weighted accuracy with Wilson lower bound and priors, cost; blame routing.

**Independent test**: fixture runs where A is confirmed and B corrected → A before B; B's card shows the corrections.

- [ ] T055 [P] [US6] Unit tests `tests/unit/test_registry_score.py`: Wilson bound monotonic in sample size (3 vs 30 signals, same mean → 30 ranks first); decay halves weight at 90 days; priors by type; score formula of R9; per-area independence.
- [ ] T056 [P] [US6] Unit tests `tests/unit/test_registry_blame.py`: excerpt holds corrected value → blame `parser`/`extractor` (by `extracted_by`), else `source`; agreement counted once per family.
- [ ] T057 [US6] Implement `src/automind/acquisition/registry/domain/score.py` and `domain/blame.py` (pure).
- [ ] T058 [US6] Recompute scores in `RegistryRepo` on `record()` and `signal()` (decay to now, add, store `score, acc_mean, acc_lb, yield`); with `autonomy: true` the planner orders by score (seed priority only breaks ties), candidates limited to `candidate_slots`, `unverified=True` for candidates.
- [ ] T059 [US6] Label candidate values "unverified source" and count them as half an independent source towards an area's minimum: pass `unverified` from the plan into evidence in `application/research.py` (`_evidence`) and into the area-minimum count (`_area_met`); show the label in `frontend/src/components/badges.tsx` (`SourceItem`).
- [ ] T060 [US6] Emit truth signals: in `challenge.py` (CONFIRMED → right, CORRECTED/REMOVED → wrong, blame via `domain/blame.py`; blame ≠ source → no source penalty, counted as a `check`/`parser` failure for insight), WS `bad_source` (wrong, weight 1, blame source), `reselect` in `research.py` when a value is replaced by a more confident one (`replacement`, 0.7, on the old claim's capability), and agreement of ≥ 2 families on an accepted value (`agreement`, 0.3). Increment `automind_wrong_values_total{area, blame}`.
- [ ] T061 [US6] Fixture scenario `tests/fixtures/scenarios/registry/` (search.json + docs) and test `tests/integration/test_registry_order.py` implementing the independent test.

## Phase 11: User Story 7 — autonomous registry and the Sources screen (P1)

**Goal**: lifecycle, discovery, admission, journal, hard limits, revert/freeze/block; Sources screen (FR-028).

**Independent test**: discovery finds a classifieds site, a terms-forbid site and a usable one → blocked, blocked (clause quoted), candidate → active after N runs; revert returns it to candidate.

- [ ] T062 [P] [US7] Unit tests `tests/unit/test_registry_lifecycle.py` (all transitions of R9 with thresholds and minimum samples; retired retry cadence) and `tests/unit/test_registry_limits.py` (seeded property test, 1,000 random histories: a blocked/classifieds/terms-forbid/deny-listed capability never leaves `blocked`; a frozen source never changes and yields `held=true`; a reverted change is not repeated without a newer signal; discovery spend never exceeds the budget).
- [ ] T063 [US7] Implement `src/automind/acquisition/registry/domain/lifecycle.py` and `domain/limits.py` (pure); every proposed change passes `limits.check(change, state)` → apply / held / refused.
- [ ] T064 [US7] Implement `src/automind/acquisition/registry/domain/admission.py` (pure verdict from facts: deny-list/classifieds markers, robots result per path, terms verdict with clause, content length) and `infrastructure/terms.py`: find the terms page (`/terms`, `/aviso-legal`, `/legal`, `/impressum`, `/condiciones`, `/mentions-legales`, links with those words), read it through the existing page store/fetcher (robots and rate limits respected), ask role `terms_reader` (new `prompts/terms_reader.md`, web reader, no tools, `{forbids_automated: bool, clause: str}`), accept the verdict only if `evidence.occurs(clause, text)`, else `unknown` (candidate with 0 slots). Add role `terms_reader: google_genai:gemini-3.1-flash-lite` to `config/models.yaml`.
- [ ] T065 [US7] Implement `src/automind/acquisition/registry/application/discovery.py`: gaps = (area, market) with `no_data` outcomes in 7 days or active < `min_active_per_area_market`; build queries from `queries.yaml` `open` templates for a popular variant with the gap (from recent outcomes) in the market's language; bounded by `discovery_eur_per_day` and `discovery_per_gap_per_day`; new domains → `discovered` → admission; prices only for European markets (FR-020).
- [ ] T066 [US7] Implement `src/automind/acquisition/registry/application/review.py` + `registry_loop()` (daily + early on N attempts; advisory lock; `heartbeat.beat("registry")`): decay, lifecycle transitions, re-checks of robots/terms (90/180 days; a new forbidding clause → blocked at once), discovery; journal every change with a one-sentence reason built by code (e.g. "acc_lb 0.68 over 11 attempts; 3 values confirmed by independent families") and evidence; increment `automind_registry_changes_total{change, author}`. Only when `autonomy: true`; CLI `--once`. Start the loop in `api/app.py`.
- [ ] T067 [US7] "No data" only after active sources and bounded discovery failed, and the report names the sources tried (FR-022): pass the plan's tried domains for an area into the composed "no data" item in `application/compose.py` and render them in `frontend/src/components/blocks/DataPanel.tsx`.
- [ ] T068 [US7] Admin endpoints in `src/automind/api/admin.py` per contracts/admin-api.md: `GET /sources?area=`, `GET /sources/changes?days=&area=` (change kinds `promoted|demoted|retired|reordered|added|blocked|unblocked|frozen|reverted`), `GET /sources/{domain}`, `POST /sources/{domain}/freeze|unfreeze|block`, `POST /sources/changes/{id}/revert` (409 on hard limits and when a later change exists). Extend `tests/integration/test_admin_api.py`.
- [ ] T069 [US7] Frontend `frontend/src/admin/Sources.tsx` (area selector; table: rank, domain, market, status, score, acc_lb, accuracy, yield, attempts, frozen/access marks; counts by status; "recent changes (30 days)" list with reason and revert button) and `frontend/src/admin/SourceCard.tsx` (capabilities, history, admission evidence with quotes, freeze/block). Tests in `frontend/src/admin/__tests__/sources.test.tsx`.
- [ ] T070 [US7] Integration test `tests/integration/test_registry_autonomy.py` implementing the independent test with the `registry` fixture scenario and a fake `terms_reader`.

**Checkpoint**: the registry runs itself; the owner sees quality and changes.

## Phase 12: User Story 9 (part 2) — shipped Prometheus rules and monitoring profile (P1)

**Goal**: alert rules for every US9 condition; optional Prometheus + Alertmanager.

**Independent test**: rules parse and reference only exported metrics; with seeded data the complaint-spike and source-degraded conditions evaluate true.

- [ ] T071 [P] [US9] Write `deploy/prometheus/automind-rules.yml` with the 16 rules of contracts/metrics.md (expressions with full `automind_` names, `for`, `severity` label, `annotations.summary`, `annotations.admin`).
- [ ] T072 [P] [US9] Write `deploy/prometheus/prometheus.yml` (job `automind`, `app:8000/metrics`, bearer token from file `/etc/prometheus/metrics_token`, rule file) and `deploy/prometheus/alertmanager.yml` (placeholder webhook receiver, grouping by `alertname`, `area`).
- [ ] T073 [US9] Add profile `monitoring` to `docker-compose.yml`: `prometheus` (`prom/prometheus:v3.5.0`, 127.0.0.1:9090, volumes for config, rules and token) and `alertmanager` (`prom/alertmanager:v0.28.1`, 127.0.0.1:9093); `scripts/deploy.sh monitoring up|down` writes the token file from `.env`.
- [ ] T074 [US9] Test `tests/unit/test_prom_rules.py`: YAML parses; every `automind_[a-z_]+` in an expression is a registered metric family in `insight/metrics/prom.py`; every rule has `severity` and `summary`. If `promtool` is on PATH, also run `promtool check rules` (skip otherwise).

## Phase 13: Polish & cross-cutting

- [ ] T075 [P] Delete `src/automind/domain/learned.py` and `LearnedSourceRepo` once nothing imports them; keep the `learned_sources` table (drop in a later spec); update `config/search.yaml` comment for `learned:` as superseded by `registry.yaml`.
- [ ] T076 [P] Update `docs/baseline.md` (registry, outcomes, insight, Prometheus), `docs/next-session.md`, `README.md` (admin page, `/metrics`, `METRICS_TOKEN`, monitoring profile) and add ADR `docs/adr/ADR-031-self-observation-and-source-autonomy.md`.
- [ ] T077 Run `scripts/check.sh` and `tests/golden`; then walk `specs/010-self-observing-registry/quickstart.md` sections 1–5 on `scripts/dev.sh` and record the results in `specs/010-self-observing-registry/checklists/requirements.md` notes.
- [ ] T078 Turn `registry.autonomy: true` in `config/registry.yaml` after T077 passes, with a note in `docs/next-session.md` (the first live week is the baseline).

## Phase 14: Everything in Docker, portable to another server (cross-cutting; can start right after Phase 1)

Owner's requirement (2026-11-05): the whole project runs in Docker and moves to another server with one deployment script. Today `app` + `postgres` are already containers, but `scripts/deploy.sh` still demands `OPENAI_API_KEY` although `models.yaml` uses Gemini, there is no way to move a running installation, tests and dev run on the host, and Prometheus is not containerised yet.

- [X] T079 Fix `ensure_env` in `scripts/deploy.sh`: derive the required keys from the providers used in `backend/config/models.yaml` (+ `MODEL_<ROLE>` overrides in `.env`): `google_genai` → `GOOGLE_API_KEY` or `GEMINI_API_KEY`, `openai` → `OPENAI_API_KEY`, `anthropic` → `ANTHROPIC_API_KEY`; search key from `config/search.yaml` provider. Generate `ADMIN_TOKEN` and `METRICS_TOKEN` into `.env.docker` when missing (like `POSTGRES_PASSWORD`). Update `.env.example` (Gemini first, tokens documented).
- [ ] T080 Add `scripts/deploy.sh export [file]`: one archive (`automind-bundle-<time>.tar.gz`, mode 600) with a fresh DB dump, `.env`, `.env.docker`, the git commit id, and `deploy/prometheus/metrics_token`; and `scripts/deploy.sh import <bundle>` on a fresh clone: checks out the commit, restores secrets, `up`, restores the dump, waits healthy. Optionally `--encrypt` with `age`/`gpg` when available.
- [ ] T081 Add `scripts/deploy.sh move user@host [dir]`: over SSH, installs nothing but requires Docker + git on the target, clones the repo at the same commit, copies the bundle via `scp`, runs `import` remotely, prints the target URL; the source stack keeps running until the owner runs `down` (no silent cut-over).
- [ ] T082 Add `scripts/deploy.sh bootstrap` for an empty Ubuntu/Debian server: checks Docker and the compose plugin, prints the exact install commands if missing (never runs `sudo` silently), creates `.env` from `.env.example` interactively.
- [ ] T083 Optional reverse proxy with TLS: compose profile `public` with Caddy (`caddy:2.10`, automatic HTTPS for `AUTOMIND_DOMAIN`), app bound to the internal network only when the profile is on; documented in README. (Public exposure still requires the security list in `docs/review-2026-11-03.md`.)
- [ ] T084 Tests and checks in Docker: `scripts/check.sh --docker` runs ruff, mypy, import-linter, pytest (against the compose Postgres, test DBs `automind_test`, `automind_mig`) and the frontend tests inside a `check` stage of the `Dockerfile` (dev dependencies), so the host needs only Docker. Keep the host mode as the default for speed.
- [ ] T085 `scripts/dev.sh --docker`: run the API from the image with the source mounted and `uvicorn --reload`, frontend via Vite in a node container; host `uv`/`node` become optional.
- [ ] T086 Monitoring profile (T073) and the bundle (T080) include Prometheus/Alertmanager config; `deploy.sh up --monitoring` starts both profiles. Document a full move in `docs/deploy.md`: export → move → verify `/api/v1/health`, `/metrics`, admin login → `down` on the old host.
- [ ] T087 Rehearse a move on a throwaway target (local VM or a second compose project name on the same host via `COMPOSE_PROJECT_NAME=automind-move`): export → import → the same chats, issues and registry visible; record the result in `docs/deploy.md`.

## Phase 15: User Story 10 — the user sees what was understood and corrects it cheaply (P1)

**Goal**: UI audit F1–F6 + quick wins + English interface (`docs/ux-audit-2026-11-05.md`). Independent of the backend phases except T090 (car edit endpoint).

**Independent test**: see spec US10; plus an axe scan with no critical/serious issues and light-theme badge contrast ≥ 4.5:1.

- [X] T088 [P] [US10] Quick wins (audit list 1–13): scroll a new answer to its start (`frontend/src/App.tsx`), theme tokens `--prov-*`/`--basis-*` with light variants in `frontend/src/index.css` used by `IntakeCard.tsx`, `CasePanel/CasePanel.tsx`, `badges.tsx`; composer keeps text on failed send (`Composer.tsx`, `onSend` returns boolean); connection banner on phones (`Header.tsx`); short mobile placeholder; remove `capitalize` (`Message.tsx`, `ProgressGrid.tsx`); intake option `aria-pressed` + selected style; accessibility fixes (persona select label, `role="img"` on the confidence dot, sources button `aria-label`, Escape on CaseSheet/ChatList); rating scale anchors + three reason chips on ratings ≤ 2 (sent as the note); one "find the missing data" action per report; hide `UsageBadge` outside debug; progress grid legend + elapsed time.
- [X] T089 [US10] English interface (FR-042): pin the UI language to `en` in `frontend/src/i18n` (`useLang`), keep reply language untouched; move the ~50 hard-coded strings the audit lists into the i18n table so a later decision can re-enable translation in one place.
- [ ] T090 [US10] Backend structured car edit (FR-037): WS message `car_edit {car_key, field: generation|engine|gearbox|trim|not_this_car|remove, value?}` in `api/ws.py` → `runner.run_turn(..., preset={"kind": "car_edit", ...})` stored with role `edit`; in `orchestration/nodes/understand.py` a `car_edit` preset builds the `CaseDelta` by code (`replace_cars` / `set_car_context` / remove) with no interpreter call, then the normal identify → assess → policy path re-researches or recomputes. Offer the choices from the cached version ladder (`application/versions.py`). Graph test `tests/graph/test_car_edit.py`: no `interpreter` call recorded; case file changed; `intake_events` gets `CARD_EDITED`; outcome class `wrong_car` recorded on the previous turn.
- [ ] T091 [US10] "Agreed" entry (FR-035): when a confirm/intake request is answered, the runner saves an assistant message of kind `agreed` (blocks: cars with version line and basis) so it survives reloads; render it collapsed in `frontend/src/components/Message.tsx` (new `blocks/Agreed.tsx`). Add `variant_label` (engine · gearbox · trim · year) to `case_file.cars` and `case_summary.cars` in the backend payload (`application/compose.py`, case file serialisation) and show it in `blocks/CaseSummary.tsx`, the case panel car row and a subtitle under the verdict headline (FR-036).
- [ ] T092 [US10] "Change" action (FR-037) in the case panel car row and the spec-table column header: chips for generation/engine/gearbox/trim from the payload's options, plus "Not this car" and "Remove"; `PROPOSED`/`UNKNOWN_MODEL` badges become buttons; inline text edit for intake fields without options. Sends `car_edit`. Tests in `frontend/src/components/__tests__/carEdit.test.tsx`.
- [ ] T093 [US10] Case panel speaks up (FR-038): auto-open on ≥1280 px on the first case file (`store/case.ts`), unseen-changes badge on "Your case" (`Header.tsx`), a one-line "Noted: … — Edit" transcript entry per `case_file.changes` set that opens the panel at the field.
- [ ] T094 [US10] "Based on: …" strip above the verdict with an Edit link (FR-039): render `case_summary` slim before `Verdict` in `Message.tsx`.
- [ ] T095 [US10] Legible data quality (FR-040): confidence as text (high/med/low) next to the dot; tap/keyboard-expandable reasons replacing `title` in `DataPanel.tsx`, `IntakeCard.tsx`, `Verdict.tsx`, `ProgressGrid.tsx`; legend line above the spec table (`SpecTable.tsx`).
- [ ] T096 [US10] "wrong?" with reason and in-cell result (FR-041): mini menu (wrong for this version / outdated / wrong value / note) in `ChallengeButton.tsx`, reason sent as `text` and stored in feedback (US2); store `challenge_result` by `car_id|attribute` in `store/chat.ts` and render it in the cell (old value struck, new value, "re-checked"), row label instead of key, reset "checking…".
- [ ] T097 [US10] Extend the mock transport (`frontend/src/mock/`) with intake card, case file, progress grid, verdict, error and limit messages (audit F15), and add a Playwright smoke script `frontend/scripts/ux-smoke.mjs` (screenshots at 1280/390, light/dark, axe scan; fails on critical/serious) runnable in Docker (`scripts/check.sh --docker`, T084).

## Dependencies & execution order

- Phase 1 → Phase 2 → stories.
- US1 (Phase 3) before US2 (feedback patches outcomes) and US9-part1 (snapshot reads outcomes).
- US3 needs US1 + US2 data; US4 needs US3; US5 needs US3 (seeder) and shows in US4.
- US8 needs Phase 2 (0016) only; US6 needs US8; US7 needs US6; the Sources screen (T068–T069) needs US7 and the admin shell (T044).
- US9-part2 (rules) needs all gauges to exist: after US7 for source gauges (rules can be written earlier, the test T074 passes once T009 registers all families, which it does up front).

```text
Setup → Foundational → US1 → US2 → US9a → US3 → US4 → US5
                    └→ US8 → US6 → US7 ─┘(Sources screen)   → US9b → Polish
```

## Parallel opportunities

- Phase 1: T002, T003, T004 together.
- Within each story, the [P] test tasks are written together before implementation (T012; T021; T027; T031–T033; T048; T055–T056; T062).
- After Phase 2, the registry track (US8 → US6 → US7) can run in parallel with the observation track (US1 → US2 → US9a → US3 → US4 → US5): they meet only in T060 (truth signals from challenge/bad source) and T068–T069 (admin shell).
- T071 and T072 in parallel; T075 and T076 in parallel.
- Phase 15 (US10) is a third independent track (frontend), meeting the backend only in T090/T091 and in T096 (feedback reason, US2).

## Implementation strategy

1. **MVP** = Phases 1–3 + Phase 5 (US1 + Prometheus snapshot): every turn measured and visible in Prometheus — the baseline the owner asked for. Release.
2. **Add** US2 (feedback) → US3 + US4 + US5 (top problems with fixes). Release: complaints stop going through the coder.
3. **Add** US8 (same behaviour) → release and compare goldens/live runs.
4. **Add** US6 + US7 (autonomy behind the flag) + US9b rules → release with `autonomy: false`, then T078.

Every release: `scripts/check.sh`, restart dev (`pkill -x automind-api; scripts/dev.sh`), `scripts/deploy.sh up`; commit, push and merge to main (owner's standing instruction).
