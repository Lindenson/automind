---
description: "Task list for 004 — Report experience"
---

# Tasks: Report Experience

**Input**: Design documents from `/specs/004-report-experience/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R13), data-model.md, contracts/report-blocks-and-protocol.md, quickstart.md

**Tests**: REQUIRED. Constitution IX (test-first core) and the plan say so: the 2026-11-02 defect regression set,
unit tests for the pure modules and golden dialogues G12–G20 are written before the code they cover.

**Organization**: tasks are grouped by user story. US3 (insights, consistency) comes before US1 (verdict)
because the verdict is built from insights. Both are P1 and together they are the MVP.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1–US7 from spec.md
- Paths are relative to the repository root (`backend/`, `frontend/`)

---

## Phase 1: Setup (configuration, migration, protocol skeleton)

**Purpose**: the files every later phase reads.

- [X] T001 [P] Create `backend/config/insights.yaml` with per-attribute `threshold_abs`, `threshold_rel`, `unit`, `direction` (higher/lower is better) and money conversion: boot 30 L, consumption 0.5 l/100 km or 5%, 0–100 km/h 0.5 s, power 10%, price 5%, yearly cost €150, value retention 5 points, reliability score 10 points (research R1)
- [X] T002 [P] Create `backend/config/sense.yaml`. It holds magnitude ranges per attribute (service interval km 1,000–300,000, "3–300 read as thousands", months 1–240 with "years" in the excerpt ×12, seats ≥ 1, boot > 0) and meaning rules ("1 speed" + CVT/hybrid → e-CVT with no gear count; gear_count ≥ 2 except BEV). It also holds result ranges: TCO per year €800–€15,000 for cars under 15 years, maintenance cap per class. Every rule has an id (research R4)
- [X] T003 [P] Create `backend/config/report_layouts.yaml`. List sections per profile (BUYER, PERFORMANCE, EXPERT, UNKNOWN): verdict, comparison, engineering, cost_over_time, value_retention, reliability, reviews, manufacturer, data_panel, sources. Each section has `open_by_default` and `depth` summary|full (research R7)
- [X] T004 [P] Create `backend/config/tech_explainers.yaml` with entries for power-split hybrid, series hybrid, e-CVT, DCT, torque-converter automatic, manual, MHEV, PHEV and BEV single-speed. Each entry has a short explanation, its consequences (consumption, reliability, feel) and a source or `editorial` (research R6)
- [X] T005 [P] Add the optional `transmissions` and `drives` lists per generation to `backend/config/generations.yaml`, for the models sold with several (CX-5 KF: manual, automatic; FWD, AWD; RAV4 XA60 and CR-V where they apply) (research R5)
- [X] T006 [P] Add the `depreciation` area to `backend/config/queries.yaml` and `backend/config/sources.yaml`, using the analyst favourites (Autovista24, cap hpi, iSeeCars, editorial buying guides). Add manufacturer queries for market share, financial results, reliability reputation and network in Spain, and `model_year_changes` queries for the engineering area (research R6)
- [X] T007 Write migration `backend/alembic/versions/0007_report_experience.py`:
  - `vehicle_variants` gains `transmission varchar(16)` (`manual`, `automatic`, `dct`, `cvt`, `e-cvt`, `single`; null = unknown) and `drive varchar(4)` (`FWD`, `RWD`, `AWD`);
  - `manufacturer_facts.fact_type` gains `MARKET_SHARE`, `FINANCIAL`, `RELIABILITY_REPUTATION`, `NETWORK_ES`, plus `value_num` and `year`;
  - new table `value_retention` with id uuid PK, variant_id FK, evidence_id FK null, years smallint, share numeric(4,3) null, eur numeric(10,0) null, market varchar(4), quoted_on date null, basis varchar(12) `SOURCED`/`ASSUMPTION`, excerpt text;
  - new table `report_ratings` with message_id PK, chat_id, rating smallint 1–5, note, created_at; it is deleted with the chat;
  - new table `value_challenges` with id, chat_id, turn_id, variant_id, attribute or claim_id, user_text, outcome `CONFIRMED`/`CORRECTED`/`REMOVED`/`UNRESOLVED`, details jsonb, created_at;
  - the downgrade reverses all of it.
- [X] T008 Add the ORM models and columns for T007 in `backend/src/automind/infrastructure/db/` (models module), and add the new chat-scoped tables to chat deletion in `backend/src/automind/application/chats.py`
- [X] T009 [P] Extend `backend/tests/integration/test_migrations.py` to test 0007: upgrade, downgrade, upgrade again
- [ ] T010 [P] Add the new block types `verdict`, `comparison`, `data_panel`, `value_retention`, `suggestions` and `section` to `frontend/src/lib/protocol.ts` exactly as in contracts/report-blocks-and-protocol.md. Also add the client messages `find`, `challenge`, `rating` and `suggestion` and the server messages `progress` and `challenge_result`. Extend `criteria_scores` with `relative`. Unknown blocks stay ignored. Add tests in `frontend/src/lib/protocol.test.ts`
- [ ] T011 [P] Create the i18n skeleton: `frontend/src/i18n/en.ts`, `ru.ts`, `es.ts`, a typed key set (the `en` keys are the type) and `frontend/src/i18n/index.ts` with `useT()`. The language comes from the latest `assistant_message.language` unless the user switched it manually; a manual choice is stored in localStorage inside try/catch (research R12)

**Checkpoint**: config loads, migration 0007 is applied to the Docker DB, the protocol compiles.

---

## Phase 2: Foundational — value sense and variant identity (FR-027, FR-028)

**Purpose**: no report may be built on values that do not mean what their attribute means. Every story depends on this.

**⚠️ CRITICAL**: no user story work starts before this phase is done.

### Tests first

- [X] T012 [P] Write the 2026-11-02 defect regression set in `backend/tests/unit/domain/test_sense.py`: interval "16" → 16,000 km; "5" months next to "years" → 60 months; "1 speed" e-CVT → transmission e-CVT and no gear_count; TCO €513,672/year → flagged and not scored; seats 0 and boot 0 L → rejected. Each case asserts the rule id
- [X] T013 [P] Write identity tests in `backend/tests/unit/domain/test_identity_gearbox.py`:
  - a "manual" claim for an automatic CX-5 variant is rejected as `OTHER_VARIANT`;
  - a title or URL that says "manual" for an automatic target gives OTHER_VARIANT in `domain/relevance.py`;
  - unanimous accepted claims fill an empty variant transmission;
  - mixed claims flag the variant for re-identification.

### Implementation

- [X] T014 Implement `backend/src/automind/domain/sense.py`. It is pure. `check(attribute, value, unit, excerpt, car_context, rules) -> SenseResult {ok, value, flags, rule_id}` covers magnitude, meaning, cross-checks (power vs mass vs 0–100, boot vs body class, consumption vs powertrain) and result ranges. The rules load from `config/sense.yaml`. Move the interval and month normalisation from its current place (specs/tco normalisation added after 003) into these rules, keeping its behaviour. Makes T012 pass
- [X] T015 Call the sense layer after unit normalisation and plausibility in `backend/src/automind/application/extraction.py`. Rejections store `reject_rule = sense.<attribute>.<rule>` on the claim. Computed TCO results go through the result-range rules in `backend/src/automind/application/compose.py` (`tco_car`), so a flagged TCO is shown as an estimate and not scored
- [X] T016 Count sense rejections per rule in the metrics endpoint (`backend/src/automind/api/rest.py` metrics query) and in `backend/tests/integration/test_metrics.py`
- [X] T017 Add `transmission` and `drive` to the `Target` dataclass and a gearbox/drive signal (manual, automatic, DSG/DCT, CVT, 4x4/AWD/AWD-i in the title or URL) in `backend/src/automind/domain/relevance.py`
- [X] T018 Make the resolver return transmission and drive when `generations.yaml` lists several (`backend/src/automind/application/resolve.py`, `backend/src/automind/orchestration/prompts/resolver.md`). Store them on the variant. In `backend/src/automind/application/research.py` or extraction, reject `transmission`/`drivetrain` claims that contradict the variant as `OTHER_VARIANT`
- [X] T019 Re-identify mixed variants in `backend/src/automind/application/resolve.py` (`revalidate`). Fill transmission and drive from unanimous accepted claims. A variant with conflicting accepted claims gets a GEARBOX question: add the question kind to `backend/src/automind/domain/policy.py` and `backend/config/questions.yaml`. Its claims of the other gearbox are marked `OTHER_VARIANT`. Makes T013 pass
- [X] T020 Data repair: a one-off step in migration 0007 (or `scripts/`) that runs the T019 re-identification on existing variants and reports the CX-5 result. Run it on the Docker DB and check that the CX-5 no longer has manual and automatic accepted together

**Checkpoint**: `scripts/check.sh` is green and the regression set passes. The user stories can start.

---

### Done ahead of plan (user reports 2026-11-02)

- [X] T086 [P] Run each page of a job as a concurrent pipeline, with `concurrency.llm_per_job` and a gateway-wide `llm_total` limit (FR-032) in `backend/src/automind/application/research.py` and `backend/src/automind/infrastructure/llm_gateway.py`
- [X] T087 Keep consumption per cycle (WLTP / NEDC / real) and use WLTP upper bounds. The fuel bill uses real-world consumption or WLTP × the allowance in `rates.yaml` (FR-033) in `backend/src/automind/domain/sense.py`, `domain/tco.py` and `domain/specs.py`
- [X] T088 Make excerpt checks ignore markdown and accept an ellipsis; check the market of price and schedule sources; derive the service interval from the schedule (FR-034) in `domain/evidence.py`, `domain/sense.py` and `application/research.py`
- [X] T089 Repair stored data with the new rules (`scripts/repair-data.sh`, `backend/src/automind/application/repair.py`). It was run on the dev DB after a backup in `backups/`

## Phase 2b: User Story 8 — Exact cars settled before research; equal equipment level (Priority: P1) 🎯 MVP part 0

**Goal**: research never starts on an unsettled car. Each answer to a car question is checked and asked again when it does not settle the car. Cars without a named version are compared at the same level (base by default).

**Independent Test**:
- Nonsense, an unknown model, "choose for me" and a valid answer in a row: the first two are asked again, no research runs, and "choose for me" takes the base level.
- Comparisons without versions use the base version of each car, and one named version matches the others at its level.

### Tests first

- [X] T021 [P] [US8] Write `backend/tests/unit/domain/test_identification.py` for `settled(car, assessment)`:
  - make, model, unique generation and a confirmed or unique version → settled;
  - PROPOSED → not settled;
  - unknown model → not settled, reason UNKNOWN_MODEL.

  Also cover `answer_settles(pending_item, before, after, request)`: a field set, an option picked or a yes/no settles; a nonsense message with no delta does not. And cover `level_for(cars)`: no trim → BASE; "Homura" at the top of its price-ordered range → TOP for the others; a gearbox or drive wish narrows the range first.
- [X] T022 [P] [US8] Write graph tests in `backend/tests/graph/test_identification_loop.py`:
  - a nonsense answer to CAR_IDENTITY or TRIM re-asks the same question (pending kept, `asked` not consumed, a `not_understood` phrase);
  - a nonsense free-text answer to CONFIRM_VARIANTS re-proposes and never confirms;
  - no search, research or report node runs until every car is settled;
  - "choose for me" picks the BASE level;
  - "remove this car" drops it.
- [ ] T023 [P] [US8] Write golden `backend/tests/golden/g19_identification_loop.yaml` (nonsense → re-ask → unknown model → closest models → valid → research) and `g20_equal_level.yaml` (RAV4 / CX-5 / CR-V without trims → base versions with "compared at base level"; "CX-5 Homura" → the others at TOP)

### Implementation

- [X] T024 [US8] Add `trim varchar(64)`, `trim_level varchar(4)` (`BASE`, `MID`, `TOP`) and `price_eur numeric(10,0)` (official, null = unknown) to `vehicle_variants` in migration `backend/alembic/versions/0007_report_experience.py` and to the ORM model. Add `compare_level` BASE|MID|TOP and `compare_level_source` DEFAULT|USER_TRIM to the case in `backend/src/automind/domain/casefile.py`, and `attempts` and `not_understood` to `Pending.items`
- [X] T025 [US8] Implement `backend/src/automind/domain/identification.py`, pure: `settled`, `answer_settles`, `level_for`, `closest_models(name, known, scorer)` (the fuzzy scorer is passed in, so domain stays free of libraries). Makes T021 pass
- [X] T026 [US8] Policy: in `backend/src/automind/domain/policy.py`, while any car is not `settled`, return only ASK or CONFIRM_VARIANTS, never RESEARCH, REPORT or ANSWER (FR-030). `_questions` re-asks a car question whose pending answer did not settle it, even when it is in `asked`
- [X] T027 [US8] Answer check in `backend/src/automind/orchestration/nodes/understand.py` (`_pending_answered`):
  - compare the case before and after the delta with `answer_settles`;
  - when it does not settle, keep `pending`, increment `attempts`, do not consume `asked`, and route to `ask` with `not_understood`;
  - in `backend/src/automind/orchestration/nodes/confirm.py` (`apply_variants`), free text that is not an option, a yes/no or a car correction re-proposes the variants instead of continuing.
- [X] T028 [US8] Re-ask phrasing in `backend/src/automind/application/ask.py` and `backend/src/automind/orchestration/phrases.py`: "I did not understand <answer> for <car>", the same question, fewer options, and "choose for me" / "remove this car" buttons (`backend/config/questions.yaml`). Handle the buttons: "choose for me" → BASE level and the first proposal confirmed; "remove this car" → the car is dropped
- [X] T029 [US8] Unknown model: in `backend/src/automind/application/resolve.py`, when the make and model are not in the catalog or config and the resolver returns no generation, return UNKNOWN_MODEL with `closest_models` from `known_models`. The ask node offers them as options. The resolver never invents a variant (resolver prompt rule)
- [X] T030 [US8] Equal level. Extend `VariantIdentity` in `backend/src/automind/application/resolve.py` and `backend/src/automind/orchestration/prompts/resolver.md` with `trim`, `trim_level`, `price_eur` and `range` (versions on sale in Spain with official prices, price-ordered). The resolver returns the version at the requested level, taken from `case.compare_level`, which `level_for` sets in assess. Catalog reuse in `_fits` and `_rank` prefers variants at that level. Store the trim, level and price on the variant
- [X] T031 [US8] Show the level: "compared at base level" (or the user's level) in the verdict facts and the case summary in `backend/src/automind/application/compose.py`, and each version's trim in the car labels. In `frontend/src/components/CasePanel/CasePanel.tsx`, show the level and each car's settled state (settled / needs your answer). Add vitest cases

**Checkpoint**: no research on an unsettled car. Nonsense answers are asked again. Equal-level comparisons are the default.

---

## Phase 3: User Story 3 — Consistent, explainable report algorithms (Priority: P1) 🎯 MVP part 1

**Goal**: code decides what is meaningful before the AI writes, scores show their basis, and the text cannot contradict the blocks.

**Independent Test**: on known data, insights are deterministic. Text with a "no data" claim, a sub-threshold win, a winner in a tie or an unknown number is corrected or regenerated. Scores show their values, relative-to-best and the missing criteria.

### Tests first

- [X] T032 [P] [US3] Write `backend/tests/unit/domain/test_insights.py`:
  - 583 L vs 580 L boot is not meaningful (a tie group);
  - 0.8 l/100 km is meaningful, shown in money per year at the user's 15,000 km;
  - the relevance order follows the priorities;
  - trade-off detection: A cheaper by €10,400, B €190/year cheaper to run, so break-even 54.7 years;
  - the same input gives the same output (FR-013);
  - one car gives no comparative insights.
- [X] T033 [P] [US3] Write `backend/tests/unit/test_report_check.py` for the four rules: a number not in the facts; "no data" / "нет данных" / "sin datos" for an area that has a block with data; "better/лучше/más" attached to a sub-threshold attribute; a winner named in a tie. One regeneration at most, then the offending sentences are removed and a notice is logged

### Implementation

- [X] T034 [US3] Implement `backend/src/automind/domain/insights.py`. It is pure and holds `Insight`, `TradeOff`, `InsightSet {insights, ties}` and `build(cars_facts, profile, thresholds) -> InsightSet`. The fields follow data-model.md: id, attribute, label, cars [{car_id, value, unit, source_ids}], diff, rel_diff, unit, meaningful, better_car, relevance, confidence. Relevance is priority weight × magnitude. Money is converted at the user's km per year and over 5 years. Thresholds load from `config/insights.yaml`. Makes T032 pass
- [X] T035 [US3] Extend scoring with its basis in `backend/src/automind/domain/criteria.py` and `backend/src/automind/application/compose.py` (`criteria_block`): `relative {car_id: 0–100, best = 100}` next to the absolute parts, the underlying values per criterion, and `not_compared` (criteria missing for some car). A single car gives absolute scores with the scale explained and no ranking (FR-010, US3 scenario 4)
- [X] T036 [US3] Add an `insights_for_llm` to `backend/src/automind/application/compose.py`. It sends the meaningful, relevant insights first and the ties as "about the same", and replaces the flat facts dump in `summary_for_llm`. Keep the allowed-numbers set built from the same facts
- [X] T037 [US3] Extend `backend/src/automind/orchestration/guard.py` into `report_check(text, blocks, insights, verdict) -> CheckResult {text, violations}` with the four rules and the multilingual absence and comparison word lists. Makes T033 pass
- [X] T038 [US3] Rewire `backend/src/automind/orchestration/nodes/report.py`: facts → insights → (verdict, Phase 4) → reporter → `report_check` → one regeneration that lists the violations → otherwise remove the offending sentences. Persist the insights and violations in the turn's computations (`persist_computations`) for audit
- [X] T039 [US3] Rewrite `backend/src/automind/orchestration/prompts/reporter_{buyer,performance,expert,balanced}.md`: write only from the insights given, call sub-threshold differences "about the same", never claim "no data" for an area that is in the facts, no winner in a tie, follow the section depth
- [X] T040 [P] [US3] Show the score basis in `frontend/src/components/blocks/CriteriaScores.tsx`: relative bar, absolute value, "not compared: …" line. Add a vitest case

**Checkpoint**: report text comes from insights and passes `report_check`. Scores show their basis.

---

## Phase 4: User Story 1 — Verdict first, personal and concrete (Priority: P1) 🎯 MVP part 2

**Goal**: the first block is a verdict card with a pick or a tie, 2–3 reasons, a trade-off with numbers, confidence with its reason, and what would change it.

**Independent Test**: golden comparisons per profile. The first block is `verdict`. It names a pick or a tie, a trade-off with numbers and units, and a confidence with its reason, and `report_check` finds 0 violations.

### Tests first

- [X] T041 [P] [US1] Write `backend/tests/unit/domain/test_verdict.py`:
  - a pick with 2–3 reasons from top insights;
  - totals within 3 points → tie, no pick, and `would_change` filled;
  - confidence: HIGH when common criteria are ≥ 80% of weight and decisive insights come from ≥ 2 sources; MEDIUM at ≥ 60%; LOW otherwise or on a decisive conflict;
  - key data missing → confidence lowered and the gap named;
  - all key data missing → "not enough data to recommend";
  - very different cars → "serve different needs".
- [ ] T042 [P] [US1] Write golden dialogues `backend/tests/golden/g12_three_suvs_verdict.yaml` (RAV4 / CX-5 / CR-V, buyer: verdict first, a trade-off with numbers, no win below thresholds) and `g13_close_cars_tie.yaml` ("too close to call" and what would tip it). Extend `backend/tests/golden/schema.py` and `runner.py` with assertions: first block type, verdict fields, zero `report_check` violations

### Implementation

- [X] T043 [US1] Implement `backend/src/automind/domain/verdict.py`, pure: `build(ranking, insight_set, coverage, profile) -> Verdict {pick_car_id|None, tie, reasons [insight ids], trade_off, confidence, confidence_reason, would_change}`. "Would change" is the insight whose flip changes the pick, written as a condition (e.g. "if you drive more than 25,000 km a year"). Makes T041 pass
- [X] T044 [US1] Add a `verdict_block` to `backend/src/automind/application/compose.py`. It renders the Verdict with reason texts and trade-off numbers from the insights. The headline is the only model-written line: one line from the reporter, checked by `report_check`, with a code fallback headline. Put the verdict and its numbers into the reporter facts in `backend/src/automind/orchestration/nodes/report.py`
- [X] T045 [US1] Make the verdict block always first, ahead of every other block (including notices) in `backend/src/automind/domain/report_layout.py`
- [X] T046 [P] [US1] Create `frontend/src/components/blocks/Verdict.tsx`: headline, pick or "too close to call", reasons, trade-off numbers, confidence badge with its reason, "what would change this", and a "find it" button when the confidence is lowered by gaps. Register it in `BlockView.tsx`. Add vitest cases for pick, tie and low confidence
- [ ] T047 [US1] Record the golden G12/G13 cassettes in replay mode (no paid calls). A live run waits for the paid tier and is announced with a cost estimate first

**Checkpoint (MVP)**: a comparison opens with a deterministic, consistent verdict card.

---

## Phase 5: User Story 2 — Rich content: technology, depreciation, manufacturer (Priority: P1)

**Goal**: sourced engineering differences explained, value retention after 3 and 5 years, a manufacturer situation per make, model-year changes and cost over time.

**Independent Test**: for well-documented cars the report has ≥ 1 sourced engineering difference, value retention per car (sourced or labelled) and ≥ 2 manufacturer facts per make, or "insufficient data" with "find it".

### Tests first

- [ ] T048 [P] [US2] Write unit tests in `backend/tests/unit/domain/test_value_retention.py`: a sourced share at 3 and 5 years wins over the curve, the fallback is labelled ASSUMPTION from the `feasibility.yaml` depreciation curve, and the market is kept. Also add extraction-schema tests for the depreciation and manufacturer kinds in `backend/tests/unit/test_agents.py`

### Implementation

- [ ] T049 [US2] Add the `depreciation` area to `backend/src/automind/domain/research_plan.py` (minimum: one sourced point per car, otherwise unmet with a retry window). Add a `backend/src/automind/orchestration/prompts/extract_depreciation.md` prompt and schema (years, share or eur, market, quoted_on, excerpt). Write to `value_retention` in `backend/src/automind/application/research.py`
- [ ] T050 [US2] Add the kinds `MARKET_SHARE`, `FINANCIAL`, `RELIABILITY_REPUTATION` and `NETWORK_ES` with `value_num` and `year` to `backend/src/automind/orchestration/prompts/extract_manufacturer.md` and to the manufacturer extraction in `backend/src/automind/application/extraction.py`
- [ ] T051 [US2] Add `model_year_changes` (facelift, engine change, recall fixed, from year) to engineering extraction (`backend/src/automind/orchestration/prompts/extract_specs.md` or a new engineering prompt) and to `engineering_block` in `backend/src/automind/application/compose.py`
- [ ] T052 [US2] Add a `value_retention_block` to `backend/src/automind/application/compose.py`: per car, points at 3 and 5 years with basis, market and sources, and the curve fallback labelled. Rework `manufacturer_block` to group by kind with source and date, and to show "insufficient data" plus findable when it has fewer than 2 facts per make
- [ ] T053 [US2] Add the tech explainers to engineering. In `compose.engineering_block`, match the powertrain and gearbox of each car to entries in `config/tech_explainers.yaml` and attach them. Pass the meaningful engineering insights and the explainers to the reporter (EXPERT gets full depth, BUYER a summary)
- [ ] T054 [US2] Add cost over time to `tco_block` in `backend/src/automind/application/compose.py`: per year and over 5 years with its parts and assumptions, and depreciation from the value-retention points when they are sourced (FR-008)
- [ ] T055 [P] [US2] Create `frontend/src/components/blocks/ValueRetention.tsx` and rework `frontend/src/components/blocks/Manufacturer.tsx` (kinds, source and date, insufficient data plus find it). Show explainers and model-year changes in `frontend/src/components/blocks/Engineering.tsx`. Add vitest cases

**Checkpoint**: an RAV4 / CX-5 / CR-V report shows e-CVT power-split vs 6-speed automatic, value retention and the makers' situation.

---

## Phase 6: User Story 4 — Data gaps in the open, with "find it" (Priority: P2)

**Goal**: one data panel instead of a wall of warnings, a comparison table without empty rows, and "find it" that researches and shows what changed.

**Independent Test**: a comparison with gaps shows one panel and no per-section warnings. "Find it" researches only those areas, and the panel then shows "+N values".

### Tests first

- [ ] T056 [P] [US4] Write `backend/tests/unit/test_data_panel.py`: status per car × area COMPLETE/PARTIAL/MISSING/UNAVAILABLE from the area minimums and the unmet set. A hard reason (robots, not sold in Spain) within the retry window gives findable=false. The before/after diff text is tested too
- [ ] T057 [P] [US4] Write golden `backend/tests/golden/g14_missing_data_find_it.yaml`: one data panel; "find it" closes a gap; the panel shows the change

### Implementation

- [ ] T058 [US4] Add a `data_panel_block(cars, unmet, last_attempts, previous=None)` to `backend/src/automind/application/compose.py`. Replace `section_notices` warnings with it, so there is at most one data-quality element at the top level (SC-008). Keep the OLD_CAR/not-sold warnings as panel reasons
- [ ] T059 [US4] Add a `comparison_block` in `backend/src/automind/application/compose.py` that replaces the spec table in reports. It keeps only rows with data for at least one car, marks missing cells, sets `meaningful` and `better` from the insights, and puts "find it" on a car column (FR-016)
- [ ] T060 [US4] Handle the client `find {focus_cars, areas}` message in `backend/src/automind/api/ws.py` as a `research_more` turn with areas. Extend `research_more` with `areas` in `backend/src/automind/application/interpret.py`, `backend/src/automind/orchestration/nodes/understand.py` (`_plan` force only the given areas) and `backend/src/automind/domain/research_plan.py`. After the research, rebuild the report with `previous` counts so the panel shows "+N values"
- [ ] T061 [P] [US4] Create `frontend/src/components/blocks/DataPanel.tsx` (compact grid, reasons, find it buttons that send `find`) and `frontend/src/components/blocks/ComparisonTable.tsx` (missing cells, meaningful highlight, find it on column header). Replace `Notice` walls in `BlockView.tsx`. Add vitest cases

**Checkpoint**: gaps are in one place, and one click fixes them.

---

## Phase 7: User Story 5 — Profile and real dialogue (Priority: P2)

**Goal**: the profile is inferred with evidence, asks 1–3 questions only when they change the answer, offers suggestions, makes critique lead to action, makes "this is wrong" trigger a re-check, and lets the user rate reports.

**Independent Test**: a clear message gets no questions, a vague one gets 1–3. Critique changes the report fingerprint. A challenge on the gearbox is re-checked and corrected with sources. A rating is stored.

### Tests first

- [ ] T062 [P] [US5] Write `backend/tests/unit/domain/test_profile_gaps.py`:
  - km/year is asked only when a hybrid vs petrol yearly difference is > €150 between mileages;
  - family size is asked only when boots differ meaningfully;
  - budget is asked when prices differ > 15%;
  - at most 3 questions;
  - nothing is asked when the verdict would not change.
- [ ] T063 [P] [US5] Write `backend/tests/unit/domain/test_suggestions.py`: 3–4 suggestions from the verdict and gaps (why is X ahead, what if used, compare on reliability, cheaper alternative, find missing). They are deterministic and in the user's language
- [ ] T064 [P] [US5] Write graph tests in `backend/tests/graph/test_critique_and_challenge.py`:
  - critique with gaps in the target → research_more;
  - critique without gaps → rework with the target section opened, and the reply starts with what was done;
  - the report fingerprint changes;
  - a challenge triggers a re-check, and the outcome is stored in `value_challenges`.
- [ ] T065 [P] [US5] Write golden `g15_critique_fill_mazda.yaml`, `g16_challenge_gearbox.yaml` and `g17_questions_vague_vs_clear.yaml` in `backend/tests/golden/`

### Implementation

- [ ] T066 [US5] Extend the profile in `backend/src/automind/domain/casefile.py`: `family` SINGLE|COUPLE|FAMILY|null, `age_band`, `driving_style`, and `evidence {field: verbatim words}`. Add the `asked` kinds KM_PER_YEAR, FAMILY_SIZE, PRIORITY, GEARBOX and `last_report {fingerprint, blocks_hash, insights_hash}`. The interpreter fills the fields only from the user's words (`backend/src/automind/orchestration/prompts/interpreter.md`, `backend/src/automind/application/interpret.py`). Investigate and fix the G2 persona-not-inferred failure on Gemini here
- [ ] T067 [US5] Implement `backend/src/automind/domain/profile_gaps.py` (pure, makes T062 pass) and use it in `backend/src/automind/domain/policy.py` (`_questions`): one round, at most 3, with suggested answers as buttons (`backend/config/questions.yaml`), asked before research when cheap
- [ ] T068 [US5] Implement `backend/src/automind/domain/suggestions.py` (pure, makes T063 pass) and add the `suggestions` block to the report in `backend/src/automind/orchestration/nodes/report.py`. Handle the client `suggestion {id}` message in `backend/src/automind/api/ws.py` by sending its request
- [ ] T069 [US5] Add the critique request kind with an optional target car/area/section to `backend/src/automind/application/interpret.py` and the interpreter prompt. The policy in `backend/src/automind/domain/policy.py` routes gaps in the target to `research_more` and no gaps to `rework`. Rework rebuilds the report with the target section open and emphasised, and passes what the user disliked to the reporter. A vague critique asks one question while it researches the biggest gaps. The reply never only apologises (FR-021)
- [ ] T070 [US5] Implement `backend/src/automind/application/challenge.py`: re-validate the claims of the value (sense + validator with the case), run a fresh search for that attribute if needed, decide CONFIRMED/CORRECTED/REMOVED/UNRESOLVED, store it in `value_challenges` and send `challenge_result`. Wire the client `challenge` message in `backend/src/automind/api/ws.py`
- [ ] T071 [US5] Store ratings: the client `rating {message_id, rating 1–5, note}` message goes to `report_ratings` (`backend/src/automind/api/ws.py` plus a repository in `backend/src/automind/infrastructure/db/`). Add ratings to the metrics endpoint
- [ ] T072 [US5] Make the profile change the content. Section `depth` and `open_by_default` come from `config/report_layouts.yaml`. The reporter prompt gets the profile and the depth per section (`backend/src/automind/orchestration/nodes/report.py`). Replace the fixed `ORDER` in `backend/src/automind/domain/report_layout.py` with the declarative layout that produces `section` blocks (FR-002, FR-019)
- [ ] T073 [P] [US5] Frontend:
  - create `frontend/src/components/blocks/Suggestions.tsx` (chips), `frontend/src/components/ChallengeButton.tsx` ("this is wrong" on table values and verdict reasons, shows the challenge_result) and `frontend/src/components/RatingControl.tsx` (1–5 and a note under each report);
  - render `section` as collapsible in `BlockView.tsx`;
  - show the profile with its evidence and let the user edit it in `frontend/src/components/CasePanel/CasePanel.tsx`;
  - add vitest cases.

**Checkpoint**: the dialogue steers the report, and every critique leads to a visible change.

---

## Phase 8: User Story 6 — Live research progress grid (Priority: P3)

**Goal**: a car × area grid instead of a status feed; it survives a reload.

**Independent Test**: during a 3-car research, cells change within 5 s and end in a final state. After a reload the grid shows the current state.

- [ ] T074 [P] [US6] Write a graph test in `backend/tests/graph/test_progress_events.py`: research jobs emit `progress {car, area, state, accepted}` for queued→searching→reading→done|failed|paused, and `EventBus.current` returns the latest snapshot on a WebSocket hello
- [ ] T075 [US6] Emit `progress` events from the research jobs in `backend/src/automind/orchestration/nodes/research.py` and `backend/src/automind/application/research.py`. Keep the grid snapshot in `backend/src/automind/infrastructure/events.py` (`EventBus.current`) and resend it on reconnect in `backend/src/automind/api/ws.py`
- [ ] T076 [P] [US6] Create `frontend/src/components/ProgressGrid.tsx` (car × area cells with state icons and one line of current activity). Keep the grid in `frontend/src/store/chat.ts`. Use it in place of `StatusTimeline.tsx` during research and show partial results as they come. Add vitest cases

---

## Phase 9: User Story 7 — User's language, phone layout (Priority: P3)

**Goal**: all interface text in ru/es/en following the conversation, and readable at 375 px.

**Independent Test**: a Russian conversation shows no English labels (G18). At 375 px there is no page-level horizontal scroll.

- [ ] T077 [P] [US7] Write golden `backend/tests/golden/g18_russian_ui.yaml` (assistant_message.language = ru, block labels sent as i18n keys) and a vitest in `frontend/src/i18n/i18n.test.ts`: every key exists in en, ru and es; a Russian message switches the labels; the manual switch wins
- [ ] T078 [US7] Move every hard-coded interface string in `frontend/src/components/**` and `frontend/src/App.tsx` into `frontend/src/i18n/{en,ru,es}.ts` and use `useT()`. Add a language switch in `frontend/src/components/Header.tsx`. Backend-generated labels in blocks (section titles, data panel reasons, suggestion labels) are sent as i18n keys with arguments, or translated through `backend/src/automind/orchestration/phrases.py`
- [ ] T079 [US7] Phone layout:
  - make the verdict card and data panel full width;
  - turn the comparison table into per-row cards under 640 px;
  - make tap targets ≥ 44 px;
  - check that there is no page-level horizontal scroll at 375 px.

  The work is in Tailwind classes in the block components and `frontend/src/index.css`. Check it in a 375 px browser viewport.

---

## Phase 10: Polish & validation

- [ ] T080 [P] Write ADRs in `docs/adr/` for the deterministic insights and verdict (ADR-021), the sense layer and gearbox/drive identity (ADR-022), and the declarative layouts and data panel (ADR-023)
- [ ] T081 [P] Update `README.md` and `backend/tests/golden/README.md` for the new blocks, config files and goldens G12–G18
- [ ] T082 Run `scripts/check.sh` (ruff, format, mypy, import-linter, pytest, vitest). Fix it until green. Check that the new domain modules have no infrastructure imports
- [ ] T083 Check performance: insights and verdict take < 100 ms for 3 cars (a timing assertion in the unit tests), and the verdict card is ready from cached data in < 30 s (SC-007)
- [ ] T084 Run quickstart.md sections 1–3 in replay. The live goldens G12–G18 and the RAV4 / CX-5 / CR-V manual check wait for paid Gemini: announce them with a cost estimate first
- [ ] T085 Restart the dev server (`pkill -x automind-api`, `scripts/dev.sh`), redeploy with `scripts/deploy.sh restart`, and update the project memory

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → stories.** T007 comes before T008, then T020. T001–T006, T010 and T011 are parallel.
- **US8 (Phase 2b)** needs Phase 1 (migration) and comes before any live research. It gates research for every other story.
- **US3 (Phase 3) → US1 (Phase 4)**: the verdict needs insights and `report_check`.
- **US2 (Phase 5)** needs Phase 2 only and can run alongside US3/US1. Its blocks join the layout from T072 or the current order.
- **US4 (Phase 6)** needs Phase 2. T059 uses the insights from T034 for `meaningful`/`better`.
- **US5 (Phase 7)** needs US3/US1: suggestions and critique work from the verdict and the fingerprint. T072 (layouts) is used by US2 and US4 blocks once it is done.
- **US6, US7** are independent of the other stories after Phase 1. T078 is best done after the new components exist (US1–US5).
- **Polish** comes last.

## Parallel examples

- Phase 1: T001, T002, T003, T004, T005, T006, T010, T011 together.
- Phase 2 tests: T012 and T013 together.
- US3: T032 and T033 together, then T034 and T037 in parallel (different files), then T038.
- US1: T041, T042 and T046 together.
- US5 tests: T062, T063, T064 and T065 together.

## Implementation Strategy

1. **MVP**: Phases 1, 2, 2b, 3 and 4 (setup, sense and identity, insights and consistency, verdict card). This fixes the worst 2026-11-02 defects: wrong values, noise presented as wins, contradictions and the buried answer.
2. **Then US2** (rich content): this answers "boring".
3. **Then US4 + US5** (gaps panel, dialogue).
4. **Then US6 + US7** (progress grid, language and phone).
5. Commit after each phase. Run `scripts/check.sh` at every checkpoint. Paid live runs only after asking, with a cost estimate.
