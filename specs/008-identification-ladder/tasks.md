# Tasks: Reliable Car Identification Ladder and Used Cars Costed as Used

**Input**: design documents in `specs/008-identification-ladder/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/identification-protocol.md

**Tests**: the spec requests property tests (FR-011, SC-004) and replays. Test tasks are included.

Paths are relative to `backend/` unless they start with `specs/` or `scripts/`.

## Phase 1: Setup

- [X] T001 Bring the draft from branch `008-wip-version-ladder` into this branch: `src/automind/domain/ladder.py`, `src/automind/application/versions.py`, `alembic/versions/0013_model_versions.py`, `src/automind/orchestration/prompts/versions.md`, `config/models.yaml` (role `versions`), `src/automind/application/usage.py` (`identify_search_calls`), `tests/golden/runner.py`. Do not bring its `.importlinter` lines.
- [X] T002 [P] Add the intake config to `config/search.yaml` under `intake`: `versions_ttl_days: 60`, `versions_max_pages: 3`, `km_per_year_used: 15000`, `default_used_age: 5`. Add the reliability scale `mileage_free_km: 60000, per_10k_over: -1, mileage_max: -15` to `config/criteria.yaml`.

## Phase 2: Foundational (blocking)

- [X] T003 Move `Version`, `Generation`, `version_to_json` and `version_of_json` into `src/automind/domain/ladder.py`, and add `excerpt` to `Version`. `application/versions.py` and the repository import them from domain.
- [X] T004 Add the `VersionsStore` Protocol (`get(make, model, generation, year, new, ttl_days)`, `put(Generation)`) and `Ports.versions: VersionsStore | None = None` in `src/automind/application/ports.py`.
- [X] T005 Add `ModelVersions` to `src/automind/infrastructure/db/models.py` and `ModelVersionsRepo` (domain imports only) to `src/automind/infrastructure/db/repositories.py`. Wire `versions=ModelVersionsRepo()` in `src/automind/infrastructure/live_ports.py`.
- [X] T006 Extend `src/automind/domain/casefile.py`:
  - `Choice` gets `level`, `fuel`, `engine_cc`, `power_kw`, `gearbox`, `drive`;
  - `IntakeItem` gets `FUEL`, `POWER`, `DRIVE`;
  - `CaseCar` gets `year_assumed` and `ladder: LadderMemo | None` (levels, origin, certainty, generation);
  - `_forget_variant` resets `chosen_for_me`.
- [X] T007 [P] Integration test for the repo in `tests/integration/test_model_versions_repo.py`: put/get by generation, by year, and new; TTL expiry; upsert. Check that `tests/unit/test_architecture.py` passes with no new ignore_imports.

## Phase 3: User Story 1 — level-by-level ladder (P1) 🎯 MVP

**Goal**: settle each car through generation → engine (fuel → family → power) → gearbox → drive over the sourced versions.

**Independent test**: `tests/unit/test_version_ladder.py` scenarios (Octavia 2.0 diesel → POWER 116/150; 150 CV with FWD/AWD → DRIVE only; unambiguous Golf → no question).

- [X] T008 [P] [US1] Write the unit tests in `tests/unit/test_version_ladder.py`:
  - Octavia "2.0 diesel" asks POWER [116, 150];
  - "2.0 TDI 150" with FWD/AWD asks DRIVE only;
  - a fully stated Golf 1.5 TSI 150 DSG gives DONE;
  - more than 6 engines asks FUEL, then FAMILY, then POWER;
  - an option's structured fields narrow to the next level only;
  - a BEV has no gearbox question.
- [X] T009 [US1] Rework the pure ladder in `src/automind/domain/ladder.py`:
  - `narrow()`: year, then fuel, family/displacement, power (±3 kW, CV and hp converted), gearbox, drive; with `missing`;
  - `next_step()` with the levels FUEL/ENGINE/FAMILY/POWER/GEARBOX/DRIVE and the grouping when there are more than 6;
  - `Option` carries the structured fields;
  - `apply_option(wanted, option)`;
  - `decide(versions, wanted, asks, limit, chosen)`: a Decision of a step or a settled version, with `auto` notes (CHOSEN/LIMIT).
- [X] T010 [US1] Make `application/versions.py` cache-first through `ports.versions`:
  - search; ≤ `versions_max_pages` pages; deny-list;
  - the `versions` reader; `validate()` (power in the excerpt, the excerpt in the document, years overlap);
  - identification search calls are counted apart.
- [X] T011 [US1] Add the ladder path to `src/automind/application/identify.py`:
  - the generation from the year or on sale;
  - `versions.lookup`, then `ladder.decide` using `case.intake.attempts` and the limit;
  - a settled version is upserted through `resolve.upsert_variant` (no duplicates) and set as PROPOSED, or CONFIRMED when chosen;
  - CHOICES carry the level and the structured choices;
  - the memo is updated (levels, origin, certainty SOURCED);
  - for a car on the ladder, it is never AUTO_OK from a single catalog row.
- [X] T012 [US1] In `src/automind/domain/intake.py`:
  - `_apply_choice` sets the structured fields of a ladder choice (fuel/cc/power → engine_hint, gearbox, drive) instead of parsing the label;
  - `_need` maps a ladder `need` to the items FUEL/ENGINE/POWER/GEARBOX/DRIVE;
  - `next_step` never returns PROPOSE/REMOVE_OR_CHOOSE for a ladder item (the limit is settled in identify).
- [X] T013 [US1] In `src/automind/domain/policy.py` and `src/automind/application/ask.py`:
  - map the items FUEL/POWER/DRIVE to the question kinds FUEL/POWER/DRIVE;
  - ladder questions render the options from the structured choices;
  - each has a "choose for me" chip and a remove chip.

  Add the templates FUEL/POWER/DRIVE (with `rephrase` and `missing` variants, ru/es/en) to `config/questions.yaml`.
- [X] T014 [US1] In `src/automind/orchestration/nodes/understand.py`, make sure a typed or tapped ladder option and "choose for me" are taken by code (`intake.pick`) for every ladder kind, the gearbox and drive questions included.

## Phase 4: User Story 2 — what does not exist is said, the question moves up (P1)

**Goal**: name what does not exist and ask the nearest level with real options. The newer answer wins.

**Independent test**: "used A4 2023 2.5" → the missing text + only 2023 engines; "2023" then "B5" → a note, the year dropped.

- [X] T015 [P] [US2] Unit tests in `tests/unit/test_version_ladder.py`:
  - for A4 2023 2.5, `missing` holds "2.5" and the options are all B9 engines;
  - a new car with an engine no longer sold gives `missing` with on-sale options;
  - `reconcile` year→generation and generation→year conflicts, with the note.
- [X] T016 [US2] Add `reconcile(memo, current levels, spans)` to `src/automind/domain/ladder.py`:
  - the highest changed level;
  - hub-written lower levels cleared;
  - the newer of year and generation kept, with the note text key `level_replaced`.

  Call it at the start of the ladder path in `src/automind/application/identify.py` and add the notices.
- [X] T017 [US2] Render the `missing` variant in `src/automind/application/ask.py`: "{car} has no {missing}; there is: {options}" (ru/es/en), using the ladder's missing list (not a note string hack).

## Phase 5: User Story 3 — never loops (P1)

**Goal**: every reply is bounded; "choose for me" settles; remove works.

**Independent test**: `tests/unit/test_ladder_property.py` (≥ 1,000 seeded scenarios) and the replay of 9b5c0b0c.

- [X] T018 [P] [US3] Write the property test in `tests/unit/test_ladder_property.py`. Generate random version lists and random replies (option, choose, nonsense, remove), and drive `ladder.decide` + `apply_option` + ask counting. Check:
  - every scenario ends settled or removed;
  - each level is asked ≤ the limit;
  - no repeated identical text for the same car and level in a row;
  - options never contradict the stated levels above.
- [X] T019 [US3] Implement settling at the limit in `ladder.decide`: origin LIMIT, the notice `settled_by_rule` in identify. The `chosen_for_me` descent sets origin CHOSEN. Add the phrases to `src/automind/orchestration/phrases.py`.
- [X] T020 [US3] Update `tests/unit/test_incident_9b5c0b0c.py` with a ladder replay: with a fake versions store, "A4 2.5 used 50000" + "2023" + "выбери сам" settles the A4 B9 with no REMOVE_OR_CHOOSE and no repeated question; the Octavia 2.0 diesel asks POWER.

## Phase 6: User Story 4 — used cars costed and scored as used (P1)

**Goal**: purchase price = used price; depreciation from the value now; age never 0; reliability age/mileage; warranty status; labels.

**Independent test**: `tests/unit/test_used_costs.py`.

- [X] T021 [P] [US4] Unit tests in `tests/unit/test_used_costs.py`:
  - `assumed_age` (mileage, generation middle, default, ≥ 1);
  - `used_price_for` (covering range, nearest ±1, none);
  - `warranty_status` (remaining, expired, unknown, assumed);
  - criteria `_price` for used (used price, or no data, never new);
  - reliability mileage effect;
  - TCO depreciation from the used price.
- [X] T022 [US4] Create `src/automind/domain/used.py` with `assumed_age`, `used_price_for` and `warranty_status`. Remove `assumed_age` from `tco.py` and point the callers to `used`.
- [X] T023 [US4] In `src/automind/application/identify.py`, after one USED_AGE ask with no year, assume the year (`year_assumed=True`, `age_years`) from mileage or generation and continue the ladder.

  In `src/automind/orchestration/nodes/compute.py`, `_age` is a safety net, so a used car is never at age 0. Add the notice `used_age_assumed`.
- [X] T024 [US4] Wire the used price:
  - `compose.load_car` loads the accepted `used_price_ranges` + evidence;
  - `compose.facts` and `compose.tco_car` take `used_price_eur` (for the car's year) and `mileage_km`;
  - `metrics.CarFacts.used_price_eur` and `mileage_km`;
  - `tco.TcoCar.used_price_eur`.
- [X] T025 [US4] In `src/automind/domain/criteria.py`:
  - `_price` for USED uses `used_price_eur` ("used price €X (sourced)"), else None;
  - `_reliability` adds the mileage effect from config;
  - `_status` keeps the new price class, labelled "new".
- [X] T026 [US4] In `src/automind/domain/tco.py`, `_depreciation` for USED: value now = sourced used price when known, else new × share(age), labelled; value then = value now × share(age+years)/share(age).
- [X] T027 [US4] Add the warranty status notice and report facts in `src/automind/orchestration/nodes/compute.py`:
  - from the make's WARRANTY manufacturer fact (`value_num` years) and the first year;
  - assumed when `year_assumed`;
  - `case_facts` lists the used year (stated or assumed), mileage, price used or no data, and warranty.

  Add the phrases ru/es/en.

## Phase 7: User Story 5 — status line and corrections (P2)

- [X] T028 [P] [US5] Unit tests: `ladder.status_line` for the settled and asked levels; a correction "it's petrol" on a settled Octavia keeps make/model/generation and re-opens fuel and below (hub-written values cleared).
- [X] T029 [US5] Add `ladder.status_line(...)` in `src/automind/domain/ladder.py`, with the level words from `config/questions.yaml` `ladder_status`. In `src/automind/application/ask.py`, put the status line before the question text of each ladder question of a car not settled yet.

## Phase 8: User Story 6 — sourced version lists (P2)

- [X] T030 [P] [US6] Unit tests for `versions.validate`:
  - a power not in the excerpt is dropped;
  - an excerpt not in the document is dropped;
  - a version outside the generation years is dropped;
  - duplicates are merged, keeping source order.

  Plus a test with a fake port: a second lookup within the TTL makes no search.
- [X] T031 [US6] Fallback in `src/automind/application/identify.py`: with no list, the existing path runs; a catalog candidate without a stated power is PROPOSED (never AUTO_OK); the memo certainty is LESS_CERTAIN, with the notice `identity_less_certain`; the ENGINE question has no invented options.

## Phase 9: Polish

- [X] T031b Make the graph and golden tests pass. Fake ports leave `versions=None` (fallback), so the goldens keep their dialogues. Fix the regressions from the new items and kinds.
- [X] T032 Run `scripts/check.sh` (ruff, mypy, lint-imports, all tests, frontend) until it is green.
- [X] T033 Update `docs/next-session.md` and memory; add ADR-030 "Identification ladder over sourced version lists" in `docs/adr/`.
- [X] T034 Merge to main; restart dev (`pkill -x automind-api; scripts/dev.sh`); `scripts/deploy.sh up`; migration 0013 applied.
- [X] T035 Live check (announced, about €0.05): quickstart steps 2–3.

## Dependencies

- Setup → Foundational → US1 → (US2, US3 in any order) → US5.
- US4 is independent of US1–US3 after the foundational phase (T006 `year_assumed`).
- US6 T030 can run after T010; T031 after T011.

## Parallel opportunities

These tasks touch only new test files, so they can run in parallel:
- T007, T008, T015, T018, T021, T028, T030.

## Implementation strategy

1. The MVP is US1 + US3 (the ladder with no loops).
2. Then US2, then US4 (the used costs, the second half of the user's request).
3. Then US5 and US6, then polish and deploy.
