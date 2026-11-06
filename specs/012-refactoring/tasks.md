# Tasks: Structural Refactoring — Human-Readable Backend

**Input**: `specs/012-refactoring/` — spec.md (US1–US5, clarifications), plan.md (steps S0–S15, after review),
research.md (R1–R16), data-model.md (target tree + module map), contracts/ (import-contracts.md, code-shape.md),
quickstart.md (gate per step)

**Tests**: no new feature tests. Test tasks here are (a) tooling self-tests, (b) characterisation tests required by
R11 before a restructure step whose modules are below 80 % branch coverage.

**Organisation**: phases follow the PR order of plan.md (one phase or sub-phase = one PR, merged to main after the
quickstart gate). Each task carries the user story it serves. Paths are relative to the repo root; `src/` =
`backend/src/automind/` after S3a, the old path is given where the task runs before S3a.

**Gate of every PR** (quickstart §1–3, §1a from S3a, §1b before restructure steps): `scripts/check.sh` green,
`alembic check` empty, behaviour diff empty, structure baseline only shrinks, test count not lower.
**Deploy**: none before 2026-11-12; then only after S3a, S6, S9, S12, S15 (quickstart §6).
**Self-check before every PR** (memory "refactoring clarity criterion"): one concept per module, no logic in nodes,
no helper "somewhere convenient", no flag arguments added, names say what the thing is.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup — S0 Repository hygiene (PR 1)

- [x] T001 (30 of 31; one locked by a live Claude session, branch merged, left as is) Remove all 31 worktrees under `.claude/worktrees/` (`git worktree remove --force` each, then `git worktree prune`); verify `git worktree list` shows only the main tree
- [x] T002 Delete all local branches merged into main except `main` (`git branch --merged main`), then all remote branches merged into `origin/main` except `main` (`git push origin --delete …`, owner's yes 2026-11-06); record counts in the PR body
- [x] T003 [P] Move `sec.md` to `docs/history/sec.md` (name kept: specs and ADRs cite it by name)
- [x] T004 [P] Move closed review documents `docs/history/review-2026-11-03.md`, `docs/history/review-2026-11-05-acquisition.md`, `docs/history/sources-revision-2026-11-05.md`, `docs/history/ux-audit-2026-11-05.md` to `docs/history/` after checking each has no open item still referenced from `docs/next-session.md`; fix links
- [x] T005 Update `docs/next-session.md` §1–2: refactoring runs by `specs/012-refactoring/tasks.md`; S0 done

---

## Phase 2: Foundational — safety net, shrink, the tree (blocking all stories)

### S1 Tooling and safety net (PR 2)

- [x] T006 Add `pytest-cov` to dev dependencies in `backend/pyproject.toml` (`uv add --dev pytest-cov`), branch coverage config `[tool.coverage.run] branch = true, source = ["automind"]`
- [x] T007 Record branch coverage of `application/compose.py`, `application/identify.py`, `application/resolve.py`, `application/interpret.py`, `orchestration/nodes/compute.py`, `orchestration/nodes/understand.py`, `orchestration/nodes/confirm.py`, `domain/policy.py`, `domain/intake.py`, `acquisition/pipeline/job.py` into `specs/012-refactoring/coverage-before.txt` (per module %, uncovered branch lines)
- [x] T008 [P] Create `scripts/refactor/metrics.py` (lines total src/tests, modules > 400 lines, `type: ignore`, `# fmt: skip`, `ignore_imports` lines in `backend/.importlinter`, contracts count, `re.compile` inside functions, coverage from T007) and generate `specs/012-refactoring/metrics-before.md`
- [x] T009 [P] Create `scripts/table_owners.yaml` mapping every table in `backend/src/automind/infrastructure/db/models.py` and raw SQL to its area per research R13 (chat / acquisition / observability; observability read-access listed per table)
- [x] T010 Create `scripts/check_structure.py` with rules of research R6 (1 module size ≤ 400, 2 package docstring + `__all__`, 3 public-before-private at top level, 4 no `re.compile`/regex literal inside functions and no word tables in logic modules, 5 node ≤ 30 / use case `run` ≤ 30 / service `run` ≤ 60 lines, 6 no raw SQL naming another area's table via `scripts/table_owners.yaml`); reads `scripts/structure_exceptions.txt` (path, limit, reason) and `scripts/structure_baseline.txt`; fails on a new violation and on a fixed-but-still-listed baseline entry; `--report` and `--write-baseline` modes
- [x] T011 [P] Unit tests for the checker in `backend/tests/unit/tools/test_check_structure.py` (one fixture tree per rule, ratchet behaviour)
- [x] T012 Generate `scripts/structure_baseline.txt` with `--write-baseline`; create empty `scripts/structure_exceptions.txt` with a header explaining format; call the checker from `scripts/check.sh` after `lint-imports`
- [x] T013 Create `scripts/refactor/move.py MAP.yaml`: for each `old.module: new.module` moves the file (`git mv`), rewrites `import`/`from` statements, dotted string paths (`mock.patch("…")`, `importlib`, `_engine("…")`, `python -m …` in `docker-compose.yml`, `Dockerfile`, `scripts/*.sh`, `backend/alembic/env.py`, `docs/**/*.md`, `.importlinter`), relative imports inside moved packages; then `ruff check --fix --select I` and `ruff format`; `--dry-run` prints the diff summary
- [x] T014 [P] Tests for the codemod in `backend/tests/unit/tools/test_move.py` (absolute/relative imports, `from x import y as z`, patch strings, compose command, a package move)
- [x] T015 Behaviour corpus. Revised 2026-11-06: real chats cannot be replayed — `llm_calls` stores no model outputs and the production DB has 11 chats. The corpus is every existing scripted test, dumped by `scripts/refactor/behaviour_dump_plugin.py`: tests/graph (58 files — they already cover the intake card `test_intake_card`, limit pause `test_limit_pause`, "find it" `test_find_it`, car edit `test_car_edit`, rescore `test_rescore`/`test_rescore_queue`, China/CLTC `test_china_cars`, cancel/resume, corrections, feasibility, candidates), tests/golden (12 dialogues), tests/integration. New golden dialogues only if a restructure step touches a path no test covers (checked per step with coverage). Live recording stays possible with `-m live --record` (costs money, owner's yes)
- [x] T016 Create `scripts/refactor/diff_behaviour.py --base REF --head REF`: in two temporary worktrees runs goldens + recorded chats with an output dump hook (report JSON + WebSocket event stream per turn), normalises timestamps/uuids/durations, compares byte for byte, prints the first differing event; exit 1 on difference
- [x] T017 `scripts/check_checkpoints.py` (read-only, production DB by default): 0 blobs/pending writes with `automind.` module paths; the latest state of every thread loads with the current graph and its pending nodes exist (2026-11-06: 358 blobs, 0 paths, 10 threads load, 0 pending)
- [ ] T017a (before S6) Cross-version resume: a pytest scenario that pauses one turn per confirm kind (intake, variants, cost, feasibility, limit) on the base commit and resumes it on the head commit against the same checkpoint tables (extends `diff_behaviour.py` with a `--resume` phase); production has no pending interrupt to use
- [x] T018 Run mypy over all of `src` in report mode in `scripts/check.sh` (non-failing, count printed), keep strict failing scope as today (`domain`)
- [ ] T019a (observed 2026-11-06: failed once in a full run on main; passed alone ×4, in integration-only and eval+golden+graph+merge runs, and in the next full run — where instead `tests/graph/test_rescore.py` failed its 2.5 s timing assert at 2.78 s while the host load average was 35–70; flaky under load, root cause of the merge failure not found yet) Fix the order-dependent failure of `backend/tests/integration/test_catalog_merge.py::test_dry_run_changes_nothing_and_apply_folds_the_duplicate` (passes alone, fails in the full suite on main 0457d91: another test's rows enter the plan via `_canonical_makes`/`_merge_plan`); isolate its data so the gate is deterministic before the behaviour diff relies on it
- [x] T019 Coverage gate prepared (`coverage-before.txt`): `domain/policy.py` 94 %, `domain/intake.py` 91 % already ≥ 80 % — no new tests needed now. Below 80 % (characterisation before their step): `orchestration/nodes/confirm.py` 47 % (S6/S9), `acquisition/pipeline/job.py` 61 % (S11), `application/ask.py` 74 % (S9), `orchestration/nodes/feasibility.py` 75 % (S9), `orchestration/nodes/report.py` 80 % borderline (S8)

### S2 Shrink and the typed facade (PR 3)

- [x] T020 [P] [US5] Remove zero-caller functions after re-checking callers incl. strings and decorators: `acquisition/agents/rule_auditor.py:by_rule`, `acquisition/gates/evaluate.py:version_number`, `acquisition/pipeline/merge.py:same_model_generations`, `application/compose.py:completeness`, `application/ports.py:selected_values`, `domain/casefile.py:_legacy_basis`, `domain/criteria.py:_normalize`, `domain/identification.py:all_settled`, `orchestration/guard.py:removal_notice`, `acquisition/registry/api.py:_domain_from_url`, `__init__.py:hello`; plus any further zero-caller function `uvx vulture src --min-confidence 60` reports that is not a framework entry point (routes, MCP tools, LangChain callbacks, HTML parser hooks, worker handlers)
- [x] T021 [US5] (revised) `application/backfill.py` and `repair-data.sh --engine` removed (applied: every production variant has engine data). `application/repair.py` KEPT: it is a data-maintenance tool (claims re-checked after rule changes, catalog duplicates folded, sources re-typed), not a one-off — it moves to the engine in S3a (catalogue/claims are engine-owned) and its `ignore_imports` go with it
- [x] T022 [P] [US5] Config single source: delete code copies of YAML defaults in `acquisition/worker/prefetch.py:21-29`, `acquisition/worker/config.py:10-24` (`DEFAULTS`), `acquisition/snapshots/codec.py:34-37`, `application/lineup.py:134,145`, `application/versions.py:121,146,159,163`, `application/identify.py:643`, `infrastructure/search/cache.py:49`, `infrastructure/config.py:282`, `domain/feasibility.py:129,267,275,299`, `domain/outcome.py:67`, `domain/weights.py:64`, `acquisition/reputation/rollup.py:143`, `acquisition/worker/handlers.py:135`, `acquisition/agents/scout.py:580`; values come from the loader (domain functions receive them as arguments, as today); a missing key fails loudly at startup
- [x] T023 [US5] `acquisition/pipeline/locate.py:41,161`: remove `MAX_DOCS_PER_JOB = 8` default, read `search.yaml limits.max_pages_per_job` (6 — the value that runs today); add a unit test asserting the loaded value is used
- [x] T024 [P] [US5] (no change needed) The three direct reads are not config duplicates: `adapters.py` hashes the raw text of models.yaml for a version id; `registry_seed_survey.yaml` is a top-level list of seed data (load_yaml takes mappings); `fit_physics` reads the eval reference set outside config/
- [x] T025 [P] [US5] Removed unread keys `insights.tie_margin_points`, `search.limits.max_fetch_bytes_per_turn`, `outcome.weights.left_after_answer` (no signal of that name exists). Kept: `energy.prices.home_pvpc` (sourced reference price), `rates.base_reserve_eur_per_year.age_bands` (column headers; tco.py repeats the bands in code — moved to YAML in S5 with the tco package). Remaining `.get(key, literal)` config defaults outside the listed files (sense, physics, lifecycle, score, agents …) are converted when their package is restructured (S5, S11, S12)
- [x] T026 [P] [US5] `domain/intake.py`: remove the duplicate `_NUM` (:181 vs :564) keeping one definition with identical behaviour (verify both regexes are equal; if not, rename the second by meaning)
- [x] T027 [US3] Typed facade `acquisition/api.py`: replace `_engine(module) -> ModuleType` returns by typed lazy accessors (`TYPE_CHECKING` imports + typed wrapper functions) so all 15 `type: ignore` go; mypy strict on `acquisition/api.py`
- [ ] T028 [US3] (moved to S7/S8, where they get their callers) Read model `car_data(variant_id) -> CarData` (S8, replaces compose.load_car's ORM reads) and catalogue calls `find_variants`/`get_variant`/`upsert_variant` (S7, replaces resolve's ORM access) in `acquisition/api`
- [ ] T029 [US3] (revised, done in S3a) The engine depends on the chat's `application.ports` (WebDoc, Page, LLM, Searcher, PageStore, SiteReaders, ReadingRow, SiteReading, Reference) and `application.usage` (TurnBudget, Limits, BudgetExceeded, current_budget/current_job) in 20 modules: these are shared contracts and metering, not chat logic. S3a moves them to `shared/contracts/` and `shared/metering/`; the engine's budget then needs no chat import and no extra Budget protocol (YAGNI); contract `engine-knows-no-chat` follows in S11
- [x] T030 Update `scripts/structure_baseline.txt` (shrinks), metrics in PR body vs `metrics-before.md`

### S3a Tree move of src — move-only (PR 4)

- [x] T031 Write `specs/012-refactoring/moves/S3a.yaml`: every module of `backend/src/automind/` → its area per `data-model.md` *as a whole file* (no splits): `shared/…`, `chat/{domain,dialog,application,infrastructure}/…`, `acquisition/…` (unchanged paths stay), `observability/…` (← `insight/`, `domain/outcome.py`, `infrastructure/db/outcomes.py`), `delivery/{web,mcp,cli}/…` (← `api/`, `mcp_server.py`, `__main__` modules); every new package gets an `__init__.py` with a one-line placeholder docstring (texts come in S3c)
- [x] T032 Run `scripts/refactor/move.py specs/012-refactoring/moves/S3a.yaml`; fix only what the codemod cannot (report each manual edit in the PR body)
- [x] T033 Retarget `backend/.importlinter` to the new paths, same meaning: the old `automind.infrastructure` = exactly its new homes, old `automind.domain`/`application` sources = their new modules. `delivery.web.app -> acquisition.infrastructure.retention` kept as an explicit, commented ignore (it was allowed while retention lived in infrastructure; the loop moves to the worker in S12). New contracts `delivery-is-outermost`, `observability-is-a-leaf` deferred: the chat adapters still build the observability OutcomeRepo (composition moves in S10/S12)
- [x] T034 Create stable CLI `src/delivery/cli/__main__.py` → `python -m automind.cli <worker|replay|baseline|migrate|fit-physics>` (module `automind/cli.py` delegating to `delivery.cli`); update `docker-compose.yml`, `Dockerfile`, `scripts/deploy.sh`, `scripts/dev.sh`, `docs/next-session.md` §3.1 (owner's 2026-11-12 command → `python -m automind.cli baseline close --name pre-autonomy`), research R14
- [x] T035 Alembic: env.py imports `shared.infrastructure.db.models` (models not split yet; the per-area collector comes with the split in S12); `alembic check` empty
- [ ] T036 Gate: quickstart §1, §1a (behaviour diff vs pre-move main, `check_checkpoints.py` on a fresh `deploy.sh checkpoints-dump`); after 2026-11-12: deploy + live replay (quickstart §4)

### S3b Tests to the mirror tree (PR 5)

- [x] T037 Write `specs/012-refactoring/moves/S3b.yaml` mapping `backend/tests/unit/**` to mirror the new src tree (`tests/unit/<area>/<package>/test_<module>.py`); `graph/`, `golden/`, `eval/`, `integration/`, `fakes/`, `fixtures/` keep their kind folders
- [x] T038 Run the codemod; gate (test count identical, behaviour diff empty)

### S3c Package docs and constitution (PR 6)

- [ ] T039 [P] [US3] Write the `__init__.py` docstring (template in data-model.md: purpose, owns, flow, depends on / must not, public API) and exact `__all__` for every package of `shared/`, `observability/`, `delivery/`
- [ ] T040 [P] [US3] Same for every package of `chat/`
- [ ] T041 [P] [US3] Same for every package of `acquisition/`
- [ ] T042 [US3] Amend constitution principle V (MINOR, version bump, sync impact report) in `.specify/memory/constitution.md` per research R10 (layers per bounded context, shared kernel, delivery adapters, `dialog` = chat orchestration layer, observability as leaf area)

**Checkpoint**: the tree shows five areas; every package documents itself; behaviour unchanged.

---

## Phase 3: User Story 1 — Find where a concept lives from the tree alone (P1)

**Goal**: one concept per module, domain objects in their own modules with their mappers, no grab-bag modules.
**Independent test**: 10 glossary concepts placed from the tree (quickstart §5, partial: chat domain + shared).

### S4 Shared kernel split (PR 7)

- [ ] T043 [P] [US1] Split `shared/evidence/evidence.py` (427) into `provenance.py`, `confidence.py`, `conflicts.py` by concept (codemod map `moves/S4.yaml` for callers)
- [ ] T044 [P] [US1] Split `shared/vehicle/specs.py` (567) into package `shared/vehicle/specs/` (`registry.py`, `tiers.py`, `transmission.py`, …) by concept
- [ ] T045 [US1] Add contract `shared-is-kernel` to `backend/.importlinter`; gate

### S5 Chat domain (PR 8; characterisation tests first where T019 listed gaps)

- [ ] T046 [US1] Characterisation tests for `chat/domain/case` delta application and `chat/domain/intake` (pick, rank_lineup, parsers) up to ≥ 80 % branch coverage in `backend/tests/unit/chat/domain/`
- [ ] T047 [US1] `chat/domain/casefile.py` (804) → package `chat/domain/case/`: `model.py` (CaseFile, CaseCar, Choice, enums), `delta.py` (`apply` + `_apply_*`), `weights.py` (`set_weights`); package `__all__` keeps the public names
- [ ] T048 [US1] Move `fit_of` from `chat/application/identify.py:56` to `Fit.from_case(case)` in `chat/domain/case/fit.py` (Fit moves from intake); callers updated
- [ ] T049 [US1] `chat/domain/intake.py` (786) → `chat/domain/intake/{pick.py, lineup_rank.py, body.py, names.py}`; step machine (23-147) → `chat/dialog/intake_steps.py`; markets cluster (676-728) → `shared/vehicle/markets.py`; text parsers (149-215, 505-675) → `chat/domain/understanding/{distance.py, region.py, condition.py, charging.py, energy_figures.py, cars_in_text.py}`
- [ ] T050 [P] [US1] `chat/domain/tco.py` (566) → `chat/domain/cost/tco/{engine.py, inputs.py, periods.py}`; `energy.py` (550) → `chat/domain/cost/energy/` per powertrain; `cost.py` → `cost/turn_cost.py`
- [ ] T051 [P] [US1] `chat/domain/ladder.py` (540) → `chat/domain/identification/ladder/` by concept (levels, narrowing, equal-level)
- [ ] T052 [P] [US1] Group remaining chat domain modules into `assessment/` (criteria, weights, metrics, dragrace, feasibility, profile_gaps, ask_value, reliability, reviews) and `verdict/` (verdict, insights, suggestions, report_layout) per data-model.md
- [ ] T053 [US1] Vocabulary by concept (research R7): move word tables and shared language patterns of `chat/domain/**` and `chat/dialog/nodes/understand.py` helpers into `chat/domain/vocabulary/{distance,charging,gearbox,condition,region,brands,…}.py`; single-use technical regexes become named module constants with example comments; no regex inside functions
- [ ] T054 [US1] Gate; baseline shrinks (all chat domain modules ≤ 400 or listed in `structure_exceptions.txt` with reason)

### S12a Acquisition admin and agents packages (PR 16 — runs after S11, listed here because it serves US1)

- [ ] T055 [P] [US1] `acquisition/admin_api.py` (1049) → package `acquisition/admin/{parsers.py, changes.py, accuracy.py, snapshots.py, engine.py, _common.py}`; `delivery/web/admin.py` imports from `acquisition.admin`
- [ ] T056 [P] [US1] One package per agent: `acquisition/agents/{scout, parser_doctor, rule_auditor, extractor_tuner, blame_judge}/` with `contracts.py`, `agent.py` (`run()` listing stages), stage modules; `evaluator.py`, `levers.py`, `budget.py` stay shared in `agents/`
- [ ] T057 [US1] Persistence split per area: `chat/infrastructure/persistence/models/`, `acquisition/infrastructure/persistence/models/`, `observability/infrastructure/models.py` from `shared`'s former `models.py` (1202), cross-area FKs by table-name strings; `repositories.py` (698) → one module per aggregate under `chat/infrastructure/persistence/repositories/`; `alembic check` empty
- [ ] T058 [US1] Observability contracts `observability-reads-only`; check rule 6 (foreign-table SQL) enforced with observability's read list; gate

---

## Phase 4: User Story 2 — Read a use case as a sequence of named stages (P1)

**Goal**: explicit dialog state machine, services with stages and strategies, use cases per user action, staged
acquisition pipeline. **Independent test**: identify, report composition and acquisition job readable from their
entry points (≤ 60 lines), every stage named.

### S6 Dialog state machine (PR 9; deploy checkpoint)

- [ ] T059 [US2] Characterisation tests for `chat/dialog` routing: every `Action.kind` → node path, every confirm kind prepare/wait/apply round-trip, limit pause/continue, hops limit, in `backend/tests/graph/test_dialog_paths.py` (cassette-free, fake services)
- [ ] T060 [US2] `chat/dialog/phases.py` (`Phase`, `ConfirmKind` enums) and `chat/dialog/contracts.py` (TypedDicts `DecisionState`, `ConfirmPayloadState`, `ResearchProgressState`, … for every nested state value; DTOs with `to_state()`/`from_state()` where code needs behaviour); `state.py` types every `TurnState` key with them — values stay plain dicts (research R4, review B3)
- [ ] T061 [US2] `domain/policy.py` → `chat/dialog/policy/`: `contracts.py` (`Rule` Protocol, `Policy` Protocol, `Action`, `CarState`), `rules/{early,intake,confirm,research,answer}.py` grouped by phase, `chain.py` (ordered list + `decide()` implementing `Policy`); one implementation, no factory/registry (review I10); `fingerprint*` → `chat/dialog/policy/fingerprint.py`
- [ ] T062 [US2] `chat/dialog/confirmation.py`: `Confirmation` (prepare, apply, routes per `ConfirmKind`) and `add_confirmation(graph, kind, spec)` wiring `prepare_X → wait_X → apply_X` with **unchanged node ids**; the five confirmations (intake, variants, cost, feasibility, limit) become configurations; the shared `wait_confirm` stays one function
- [ ] T063 [US2] `chat/dialog/graph.py` as a transitions table (≤ 80 lines): understand chain, policy routes table `Action.kind → node`, confirmations via `add_confirmation`, research fan-out; node ids identical to today (assert in a test comparing the compiled graph's node and edge set with a stored snapshot `backend/tests/graph/graph_shape.json` taken before the step)
- [ ] T064 [US2] `chat/dialog/runner.py` (← orchestration/runner.py), `retry.py`, `tracing.py` (← outcomes.py), `context.py` (← nodes/common.py); nodes keep calling existing application functions (logic moves out in S7–S9)
- [ ] T065 [US2] Gate incl. `check_checkpoints.py` on a fresh dump; after 2026-11-12 deploy + live replay

### S7 Identification service (PR 10)

- [ ] T066 [US2] Characterisation tests to ≥ 80 % branch coverage for `chat/application/identify.py` and `resolve.py` (fallback order, ladder narrowing, gearbox handling, catalogue hit/miss) in `backend/tests/unit/chat/application/services/identification/`
- [ ] T067 [US2] Package `chat/application/services/identification/`: `contracts.py` (`IdentifyRequest`, `Identified`, `Fallback` Protocol), `service.py` (`IdentificationService(ports)` with `run()` ≤ 60 lines listing stages), `stages/{normalise_name, catalogue_lookup, run_fallbacks, narrow_ladder, settle}.py`, `strategies/{catalogue, registered, open_world}.py`; sources `identify.py`, `resolve.py`, `lineup.py`, `versions.py`, `makes.py`, `candidates.py`; pure matching (`fits`, `same_model`, `engine_of_fits`, `_rank`, `model_line`) → `chat/domain/identification/variant_match.py`
- [ ] T068 [US2] Port `VariantCatalogue` in `chat/application/ports.py`, adapter `chat/infrastructure/engine_adapters.py` over `acquisition.api` catalogue calls (T028); remove `resolve`/`lineup` `ignore_imports` from `backend/.importlinter`
- [ ] T069 [US2] `chat/dialog/nodes/identify.py` ≤ 30 lines calling the service; gate + behaviour diff

### S8 Report service (PR 11)

- [ ] T070 [US2] Characterisation tests to ≥ 80 % for `compose.py` blocks and `nodes/compute.py` helpers (period totals, verdict extras, used lines, assumption lines) in `backend/tests/unit/chat/application/services/report/`
- [ ] T071 [US2] Package `chat/application/services/report/`: `service.py` (`ReportService.run()` listing load → facts → blocks → persist), `facts/` (car accessors, race inputs, prices, warranty ← compose.py 25-360, 1218-1228), `blocks/` one module per block (spec table, metric bars, race, sources, data panel, criteria, engineering, manufacturer, tco, reliability, reviews, value retention, electric ← electric_block.py, car view ← car_view.py, intake card ← intake_card.py), `tco_inputs.py`, `case_facts.py` (← nodes/compute.py pure helpers 47-430, 575-633)
- [ ] T072 [US2] Port `CarRepository` over `acquisition.api.car_data()` (T028) in `chat/infrastructure/engine_adapters.py`; computations persistence behind a port; remove `compose` `ignore_imports`; `insight_values`/`short_name` take domain values, not `db.Variant`
- [ ] T073 [US2] `chat/dialog/nodes/report.py` and the compute node ≤ 30 lines each; gate + behaviour diff

### S9 Interpretation, research, feasibility, usage services (PR 12; deploy checkpoint)

- [ ] T074 [US2] Characterisation tests to ≥ 80 % for `interpret.py`, `ask.py`, `nodes/understand.py`, `nodes/confirm.py`, `nodes/research.py`, `nodes/feasibility.py`
- [ ] T075 [P] [US2] `chat/application/services/interpretation/` (← interpret.py, ask.py, understand node's `_*_from_text` safety nets as stages using `chat/domain/understanding`)
- [ ] T076 [P] [US2] `chat/application/services/research/` (plan jobs, order via `acquisition.api.acquire(…, budget)`, collect rounds, limit handling ← nodes/research.py logic)
- [ ] T077 [P] [US2] `chat/application/services/feasibility/` (← application/feasibility.py + nodes/feasibility.py logic) and `services/usage/` (← usage.py)
- [ ] T078 [US2] All `chat/dialog/nodes/*.py` ≤ 30 lines (read state → call service → write state); `ChallengeValue` use case + port (← challenge.py), remove its `ignore_imports` (none left); purity contracts for `chat.dialog` and `chat.application` (contracts/import-contracts.md); gate; after 2026-11-12 deploy + live replay

### S10 Use cases (PR 13)

- [ ] T079 [US2] `chat/application/usecases/{send_message, confirm_answer, find_more, edit_car, rescore, open_chat, delete_chats, challenge_value}.py`: class per action, ports in constructor, `run()` ≤ 30 lines, command DTOs with their mappers (`ResearchPreset.from_command`, …) in `chat/application/usecases/contracts.py`; logic taken from `ChatRunner.run_turn` branches and `delivery/web/ws.py` `_resume_payload`/`_car_edit_preset`
- [ ] T080 [US2] `delivery/web/ws.py` and `rest.py` call use cases only; composition root `delivery/web/app.py` wires them; `chat` layers contract in `backend/.importlinter`; gate

### S11 Staged acquisition pipeline (PR 14)

- [ ] T081 [US2] Characterisation tests to ≥ 80 % for `acquisition/pipeline/job.py`
- [ ] T082 [US2] `acquisition/pipeline/contracts.py` (Job, StageResult, Page, …) and `job.py` whose `run()` lists plan → locate → fetch → parse → relevance → validate → merge → persist; stage modules under `acquisition/pipeline/stages/`; `identity.py` + `gold/versions.py` → `acquisition/identity_readers/`
- [ ] T083 [US2] Contract `engine-knows-no-chat` in `backend/.importlinter`; gate

---

## Phase 5: User Story 4 — All parsing knowledge in one place (P2)

**Goal**: "page → fields → claims → validated values" in one package; no regex in functions anywhere.
**Independent test**: "where is the pattern for X" answered from `acquisition/parsing/__init__` in < 2 minutes.

- [ ] T084 [US4] (PR 14, with S11) `acquisition/parsing/`: `readers/` (spec, interpreter, registry, store, fingerprint, legacy, migrate_v1), `extraction/` (`contracts.py` ← schemas/DTOs of `pipeline/extract.py`; `extract.py` logic only), `normalise/` (units, test cycles, Chinese units, CLTC — from `shared/vehicle/units` callers in the pipeline, `sense_ev`, `validate.py` helpers), patterns by concept; package docstring draws the flow; remove empty `infrastructure/site_readers/`
- [ ] T085 [P] [US4] Remaining regexes inside functions across `acquisition/**`, `observability/**`, `delivery/**` → named module constants or `normalise/` vocabulary (checker rule 4 baseline for these areas empty)
- [ ] T086 [P] [US4] Reply phrases: `orchestration/phrases.py` (597) and phrase tables of `report_text.py` (590) → `chat/dialog/phrases/<lang>.py` + `chat/dialog/phrases/report_text/` by block; checker rule 4 baseline for `chat/**` empty

---

## Phase 6: User Story 3 — Every package's purpose and public API (P2)

**Goal**: contracts first, public before private, exact `__all__`, typed.
**Independent test**: checker rules 2 and 3 report nothing; mypy strict green in the narrowed scope.

- [ ] T087 [US3] (S13, PR 17) Reorder every module: docstring, imports, contracts, public, private (checker rule 3 baseline empty); remove cross-package imports of private names / non-exported names
- [ ] T088 [US3] mypy strict for `shared`, every `domain`, `acquisition/api.py`, `chat/application`, `chat/dialog` in `scripts/check.sh` (research R16); report mode + ratchet for the rest
- [ ] T089 [US3] `__all__` audit: every package exports exactly what other packages import (script in `scripts/refactor/metrics.py --exports`)

---

## Phase 7: User Story 5 — Documentation, metrics, acceptance (P3 + feature close)

- [ ] T090 [US5] (S14, PR 18) `docs/architecture.md`: areas and packages with responsibilities, diagrams of the three flows (chat turn through the dialog machine; acquisition job stages; worker loop and observability loop), table owners, import contracts summary, glossary concept → module (≥ 40 concepts)
- [ ] T091 [P] [US5] Update `docs/baseline.md` and `docs/deploy.md` for the engine and the new CLI; README links
- [ ] T092 [US5] `specs/012-refactoring/shims.md` empty; `scripts/structure_baseline.txt` empty (only justified `structure_exceptions.txt` entries remain); `metrics-after.md` vs `metrics-before.md` per SC-002…SC-008 in the PR body
- [ ] T093 (S15, PR 19) Acceptance: `check_checkpoints.py` on a fresh live dump; deploy; live replay of chat ccd5f7d8 shown to the owner first; readability walk-through with the owner (quickstart §5); `docs/next-session.md` handoff (refactoring done, parked backlog §4 resumes)

---

## Dependencies & Execution Order

PR order (strict): S0 → S1 → S2 → S3a → S3b → S3c → S4 → S5 → S6 → S7 → S8 → S9 → S10 → S11 (+T084) → S12a →
S13 → S14 → S15.

- S1 blocks everything (safety net). S2 before S3a (shrink first; facade read model needed by S7/S8).
- S3a/b/c block all story phases (every later diff lands in final packages).
- S5 before S6 (intake step machine moves into dialog). S6 before S7–S9 (nodes become adapters against the new
  dialog). S7, S8 need T028 (S2). S10 after S9. S11 independent of S6–S10 but kept after them (one big change at a time).
- Restructure steps start only when their characterisation task is done (≥ 80 % branch coverage).

## Parallel Opportunities

Inside one PR, tasks marked [P] touch different files: T003/T004; T008/T009; T020/T022/T024/T025/T026; T039/T040/T041;
T043/T044; T050/T051/T052; T055/T056; T075/T076/T077; T085/T086. PRs themselves are sequential (one big change at a time
on main; no feature work in parallel).

## Implementation Strategy

- **MVP = Phase 1–2 + S5**: safety net, shrink, the five-area tree with documented packages and a readable chat
  domain — the owner can already navigate; show it to the owner after S3c and after S5.
- Then the use-case readability core (S6–S10), then the engine (S11, S12a), then polish and docs.
- Stop rule: if a behaviour diff appears that is not explained by a test-only name change, the step is reverted or
  fixed before anything else; never edit golden expectations.
