# Tasks: The User's Profile Drives the Assessment

**Input**: Design documents from `/specs/007-profile-assessment/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: required. Constitution IX requires the deterministic core to be test-first, and the success criteria are verified by tests. Within each story, test tasks come before implementation.

**Organization**: phases follow the plan's increments. Each phase is one PR merged to main:
- US5 (search recall) ships first and is independent;
- then US1 → US2 → US3 → US4 → US6;
- then the validation gaps and graph robustness;
- US7 is last.

Paths are relative to the repo root: `B/` = `backend/src/automind/`, `T/` = `backend/tests/`, `C/` = `backend/config/`, `F/` = `frontend/src/`.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [X] T001 (US5 keys done in increment A; intake, interpret and graph keys come with B and H) Add config keys to `C/search.yaml`:
  - `empty_result_ttl_hours: 6`
  - `favourite_retry: true`
  - `learned: {min_runs: 3, max_misses: 5, per_area: 4}`
  - `interpret: {history_turns: 16, history_chars: 800}`
  - `graph: {max_hops: 12}`
  - set `intake.full_intake: false`

  Load them in `B/config.py` / `B/infrastructure/config.py` with the defaults above.
- [X] T002 [P] (profile_defaults.yaml done in B; profile_rules.yaml comes with C) Create `C/profile_rules.yaml` and `C/profile_defaults.yaml` exactly as in data-model.md (real criteria only; `cap: 50`; probe values).

---

## Phase 2: Foundational (blocks US1–US4)

- [X] T003 Write tests in `T/unit/domain/test_casefile.py` for:
  - the `basis` upgrade of old rows (USER_EDIT → STATED; `annual_km_stated` → STATED; a field with evidence → INFERRED; else ASSUMED);
  - the precedence rule STATED > INFERRED > ASSUMED;
  - `ownership_years` bounds 1–20;
  - the conversion of `weights_overridden` + `weights` into `weight_adjustments`.
- [X] T004 Implement in `B/domain/casefile.py`:
  - `ProfileBasis` and `CaseFile.basis: dict[str, ProfileBasis]`;
  - `ownership_years: int | None` (ge=1, le=20);
  - `weight_adjustments: dict[CriterionKey, float]`;
  - a `model_validator(mode="before")` upgrade of old rows (the conversion to adjustments needs the automatic weights: do it lazily via `weights.upgrade_adjustments()` in T020; keep `weights` and `weights_overridden` read-only until then);
  - `apply()` respecting basis precedence.
- [X] T005 [P] (done as `weights.ProfileRules.from_config`, tested in test_weights.py) Write a loader for `profile_rules.yaml` / `profile_defaults.yaml` in `B/infrastructure/config.py`. It rejects unknown criteria, unknown fields and malformed bands (`<N`, `<=N`, `>N`, `>=N`). Test it in `T/unit/test_domain.py::test_profile_rules_loader`.

**Checkpoint**: case files load and save with the new fields; all existing tests stay green.

---

## Phase 3: User Story 5 — Searches find what exists, good sources remembered (P1) 🎯 Increment A, own PR

**Goal**: round-0 queries are short, use the market's language, retry once on zero hits, cache empty results only briefly, and use learned sources.

**Independent Test**: replaying chat 757cff3d with recorded search finds round-0 pages for specs, measured and reliability for both cars (SC-006).

### Tests

- [X] T006 [P] [US5] Tests in `T/unit/domain/test_search_plan.py` for `short_identity()` / `variant_key()`:
  - "Volkswagen Golf Mk8.5 Golf Variant R 2.0 TSI 333 CV DSG 4MOTION" → "Volkswagen Golf Variant R 333";
  - "BMW 3 Series G21 320d Touring M Sport Steptronic" → "BMW 320d Touring" (the engine code names the model);
  - "Toyota C-HR 2.0 hybrid 197 CV" keeps "2.0 hybrid";
  - no Mk\d, chassis codes, DSG/xDrive/4MOTION or repeated words.
- [X] T007 [P] [US5] Tests in `T/unit/domain/test_search_plan.py` for templates and retry:
  - a DE reliability favourite contains "Pannenstatistik";
  - an ES one contains "fiabilidad";
  - an EN one contains "reliability";
  - `shorter(query)` gives `{make} {model}` + the area words;
  - learned domains are appended after the configured ones, at most `per_area`, never denied.
- [X] T008 [P] [US5] Tests in `T/unit/domain/test_learned.py` for the rules in `B/domain/learned.py`:
  - a domain is promoted at `min_runs`;
  - it expires at `max_misses`;
  - a denied domain is never active;
  - a configured favourite is not duplicated;
  - `source_type` comes from `classify_source` (a look-alike such as "bmw-club.es" is never MANUFACTURER).
- [X] T009 [P] [US5] Tests in `T/unit/infrastructure/test_search_cache.py`: an empty result is stored with `empty=True` and expires after `empty_result_ttl_hours`; a non-empty result keeps the area TTL.

### Implementation

- [X] T010 [US5] Implement `short_identity`, `variant_key`, `shorter` and a `{short}` placeholder in `_render` in `B/domain/search_plan.py`. Add a `learned` parameter to `queries()` and the planned-query kind `FAVOURITE_RETRY`.
- [X] T011 [US5] Rewrite the favourite templates in `C/queries.yaml` to `'{short} <area words> {sites}'`, with `favourite_by_market` for ES, DE and EN in every area. Open templates are unchanged.
- [X] T012 [P] [US5] Implement `B/domain/learned.py`, with pure `update_row(row, accepted: bool) -> row` and `is_active(row, cfg, denied, favourites) -> bool`.
- [X] T013 [US5] Write migration `backend/alembic/versions/0010_learned_sources.py`:
  - table `learned_sources` (id uuid pk, domain, area, market, source_type, accepted_runs int default 0, misses int default 0, first_seen, last_seen; unique (domain, area, market));
  - `search_cache.empty boolean not null default false`.

  Mirror it in `B/infrastructure/db/models.py` (`LearnedSource`, `SearchCache.empty`) so `alembic check` passes.
- [X] T014 [US5] Change `B/infrastructure/search/cache.py`: store `empty`, and use `empty_result_ttl_hours` for empty rows in `_ttl` / the lookup.
- [X] T015 [US5] Create `B/application/learned_sources.py`:
  - `load_active(session, area, market)`;
  - `update(session, run_id)`, which aggregates accepted claim domains per job's (area, market) and searched-but-not-accepted domains, as in contracts/learned-sources.md.

  Add a repository in `B/infrastructure/db/repositories.py`.
- [X] T016 [US5] Wire it into `B/application/research.py`:
  - `identity_of` keeps the full identity for open queries;
  - round 0 passes the learned domains;
  - one `FAVOURITE_RETRY` is issued when a favourite query returns 0 hits (counted in the limits);
  - `learned_sources.update` is called at the end of the run.
- [X] T017 [US5] Metrics (done in the API; empty share is computed from `research_jobs.queries[].empty`; the frontend page shows it only when a metrics page exists): add `learned_sources` and `empty_search_share` to `GET /api/v1/research/metrics` (`B/api/rest.py` + the existing metrics query). Show both on the frontend metrics page if one exists, else skip the UI.
- [X] T018 [US5] Write the recorded replay (done as `T/unit/test_recall_757cff3d.py`, offline, real config), with fixture search results keyed by the new short queries for BMW 320d Touring G21 and Golf Variant R. Assert round-0 pages > 0 for specs, measured and reliability, and that no query contains "Mk8.5" or a repeated model.
- [X] T019 [US5] Run `scripts/check.sh`, restart dev, run `scripts/deploy.sh up`, then commit, push, open a PR and merge to main ("007-A search recall").

**Checkpoint**: increment A is shippable alone.

---

## Phase 4: User Story 1 — Profile understood, asked when it matters (P1) Increment B

**Goal**: profile fields are inferred from the dialogue with evidence, defaults are marked ASSUMED, and at most one question is asked, only when it changes the outcome.

**Independent Test**: G31 and G32 (quickstart B).

### Tests

- [X] T020 [P] [US1] Tests in `T/unit/test_interpret.py` for `numbers_in`:
  - "до 20 тыщ" → {20000};
  - "1,5 млн" → {1500000};
  - "20к" → {20000};
  - "Golf 7 2015" → {7, 2015};
  - "25.000 €" → {25000};
  - "20 км" is not money.
- [X] T021 [P] [US1] Tests in `T/unit/domain/test_ask_value.py` for `B/domain/ask_value.questions()`:
  - no question when every probe value gives the same winner and tie;
  - asks `annual_km` when 8,000 vs 30,000 flips the winner;
  - at most 1 field;
  - before research, asks persona only when the persona weight vectors differ by ≥ 15 points;
  - never asks a STATED field.
- [X] T022 [P] [US1] Tests in `T/unit/domain/test_casefile.py`:
  - interpreter evidence that is not in any user message drops the field;
  - INFERRED never overwrites STATED;
  - defaults from `profile_defaults.yaml` are applied with ASSUMED per persona.
- [X] T023 [P] [US1] (done as graph tests `T/graph/test_profile_inferred.py`) Goldens `T/golden/G31_persona_from_trims.yaml` ("BMW 320d M Sport или Golf R?" → PERFORMANCE INFERRED with evidence "M Sport"; ≤1 question) and `T/golden/G32_family_mountains.yaml` (family FAMILY INFERRED, usage MOUNTAINS, budget 30000), with fake-model cassettes.

### Implementation

- [X] T024 [US1] `B/application/interpret.py`:
  - fix `numbers_in` / `_NUM_RE` for "тыс", "тыщ", "млн", "mil", "k", "к" and the rule that space-separated numbers are not glued (FR-004);
  - the history window comes from config (`history_turns` × `history_chars`, FR-005);
  - add an evidence check: every `set_profile` / `set_persona` evidence must be a substring (normalised) of a user message in this chat.
- [X] T025 [US1] Update `B/orchestration/prompts/interpreter.md`. Replace "ONLY when the latest message says it" with inference from the whole dialogue, `basis: INFERRED` and the evidence words. Add the persona cues: M Sport, GTI, R, RS, AMG, track → PERFORMANCE; children or school → family; economy words → BUYER. Bump the prompt version.
- [X] T026 [US1] `B/domain/casefile.py` CaseDelta:
  - `set_profile` / `set_persona` carry a basis;
  - add `set_ownership_years`;
  - map the monthly limit onto `running_cost_limit` with basis `monthly_limit`;
  - add `apply_defaults(case, defaults)` (pure).
- [X] T027 [US1] Implement `B/domain/ask_value.py` (R5). Use it in the intake step of `B/domain/policy.py` / `B/orchestration/nodes/understand.py`, capping profile questions at 1 per turn together with `profile_gaps.questions`. Add the question kinds OWNERSHIP_YEARS, ANNUAL_KM, CONDITION and PERSONA, localized en/ru/es in `C/questions.yaml` with chip answers.
- [X] T028 [US1] (vitest for the card: still to add) Intake card (`B/orchestration/nodes/confirm.py` + `F/components/IntakeCard.tsx`): show persona, ownership years, new/used, km and budget, each with a basis badge (stated / inferred «…» / assumed) and a "correct?" chip for inferred fields. Add a vitest test in `frontend/src/components/IntakeCard.test.tsx`.
- [X] T029 [US1] Run check, restart dev, deploy, then commit, push and merge ("007-B profile understood").

---

## Phase 5: User Story 2 — Profile changes the weights, visibly (P1) Increment C

**Goal**: the weights are persona base + profile rules + priorities + manual adjustments, each with a reason.

**Independent Test**: quickstart C.

### Tests

- [X] T030 [P] [US2] Tests in `T/unit/domain/test_weights.py`:
  - one test per rule in `C/profile_rules.yaml` (the field value adds those points with that reason);
  - the cap of 50 and normalisation to 100;
  - negatives are clipped;
  - a manual +10 survives a persona change;
  - reset clears the adjustments;
  - a manual 0 gives final 0, "excluded by you";
  - an old case with `weights_overridden` gives the same final numbers after `upgrade_adjustments`;
  - "family+mountains+calm" ≠ "single+city+sporty" with the same persona (SC-003).

### Implementation

- [X] T031 [US2] Implement `B/domain/weights.py`: `WeightLine`, `WeightBreakdown`, `breakdown(case, model, rules)` and `upgrade_adjustments(case, model, rules)`. Make `B/domain/criteria.py::weights_for` return `breakdown(...).final`. Change `set_weights` in casefile.py to store `weight_adjustments` (absolute weights minus automatic) instead of setting `weights_overridden`.
- [X] T032 [US2] Make `B/orchestration/nodes/compute.py` and `B/application/compose.py` put the breakdown into the `criteria_scores` block (contracts/case-patch-and-rescore.md "Weight breakdown in blocks"). Add the reason-code labels en/ru/es to `B/orchestration/report_text.py` and the frontend i18n.
- [X] T033 [US2] (the panel reads `GET /api/v1/chats/{id}/weights` after every case change; no component-test setup exists, so a backend test checks that every reason code has a label) In `F/components/CasePanel/Weights.tsx`, show the reasons per weight, a "set manually" badge and a "back to automatic" button (sends `reset_weights: true`). Update the types in `F/lib/protocol.ts`. Add a vitest test in `frontend/src/components/CasePanel/Weights.test.tsx`.
- [X] T034 [US2] Run check, restart dev, deploy, then commit, push and merge ("007-C weights from profile").

---

## Phase 6: User Story 3 — A change in the panel recalculates at once (P1) Increment D

**Goal**: a panel PATCH triggers a RESCORE turn with no research and no interpreter. Card edits shape the research.

**Independent Test**: quickstart D (under 2 s; 0 searches; 0 interpreter calls).

### Tests

- [ ] T035 [P] [US3] Tests in `T/unit/domain/test_policy.py`:
  - `fingerprint_data` / `fingerprint_params` split;
  - only params changed + fresh data → RESCORE;
  - data changed or stale → research;
  - neither → nothing new;
  - an old single fingerprint → treated as both changed;
  - a family or region change is now detected (it was missing from the old fingerprint).
- [ ] T036 [P] [US3] Graph test `T/graph/test_rescore.py`:
  - a finished fixture report, then `PATCH {persona: PERFORMANCE}` gives one turn of kind rescore, 0 search calls, 0 interpreter calls, at most 1 reporter call, and changed weights and scores;
  - PATCH during RUNNING gives 409;
  - `PATCH {condition: USED}` gives `rescore: research_needed` with `missing`.
- [ ] T037 [P] [US3] Graph test `T/graph/test_card_edits_before_research.py`: changing the persona on the intake card makes the research plan areas equal `research_plan.areas_for(new persona, …)`.

### Implementation

- [ ] T038 [US3] `B/domain/policy.py`:
  - the actions RESCORE and the reason codes `params_changed`, `data_stale`, `nothing_new`;
  - `fingerprint_data(case, data_version)` and `fingerprint_params(case, language)`;
  - the decision rules from plan.md "Turn graph".

  Store both fingerprints on the turn (`"<data>:<params>"`) in `B/orchestration/runner.py` / repositories.
- [ ] T039 [US3] `B/api/rest.py`:
  - CasePatch v2 (`profile`, `ownership_years`, `condition`, `weight_adjustments`, `reset_weights`; every patched field gets basis STATED);
  - after `save_version`, call `B/application/rescore.py::plan(case_before, case_after)` → started / not_needed / research_needed + missing;
  - when started, call `runner.run_turn(chat_id, None, None, preset={"kind": "rescore", "changes": [...]})`.

  Response as in contracts/case-patch-and-rescore.md.
- [ ] T040 [US3] Graph:
  - `B/orchestration/nodes/understand.py` handles the preset kind `rescore` (skips interpret and identify);
  - policy routes to compute → a new `report_rescore` in `B/orchestration/nodes/report.py`: one LLM call over facts + changes, with the guard, giving a short "what changed" text;
  - the edge is added in `B/orchestration/graph.py`;
  - the criteria rows carry a `delta` against the previous report's scores.
- [ ] T041 [US3] Frontend:
  - `F/components/CasePanel/CasePanel.tsx`: replace the read-only `AboutYou` with a `ProfileEditor`. It has chips or inputs for persona, ownership years, new/used, km, budget, monthly limit, family, style, region and usage, each with a basis badge;
  - `F/store/case.ts` queues a patch while a turn runs and sends it after `turn_done`;
  - `F/components/blocks/CriteriaScores.tsx` highlights rows whose `delta` ≠ 0.

  Add vitest tests for the editor and the queue.
- [ ] T042 [US3] Run check, restart dev, deploy, then commit, push and merge ("007-D rescore").

---

## Phase 7: User Story 4 — The verdict and text speak to this user (P1) Increment E

**Goal**: the TCO covers the user's period and km; budget findings; a persona counterfactual; the text leads with the persona's criteria.

**Independent Test**: the three-profile test (SC-005).

### Tests

- [ ] T043 [P] [US4] Tests in `T/unit/domain/test_tco.py`:
  - the horizon comes from `ownership_years`, falling back to `rates.horizon_years`;
  - depreciation is interpolated between the 3- and 5-year points;
  - beyond 5 years it uses the assumption rate, labelled ASSUMPTION;
  - the period is shown in the block payload.
- [ ] T044 [P] [US4] Tests in `T/unit/domain/test_insights.py`:
  - `OVER_BUDGET`, `OVER_MONTHLY`;
  - the verdict rule (an over-budget car is "best if the budget allows"; the in-budget runner-up becomes the pick when within 2 × TIE_MARGIN);
  - `OTHER_PROFILE_WINS` appears only when another persona's winner differs;
  - the years and km counterfactuals use the user's numbers.
- [ ] T045 [P] [US4] Write `T/graph/test_three_profiles.py`: the same fixture pair with racer/3 y, family/8 y/20,000 km, and used buyer/400 €/month. At least 2 verdicts differ, and each verdict text names the profile reason.

### Implementation

- [ ] T046 [US4] `B/domain/tco.py`: a `years` parameter and the depreciation-to-year logic. In `B/orchestration/nodes/compute.py`, pass `case.ownership_years`. In `B/application/compose.py:~772`, replace the hard-coded "over 5 years" title with a localized period.
- [ ] T047 [US4] `B/domain/insights.py` (or the module where insights and the verdict live):
  - budget findings;
  - the verdict rule documented in a docstring;
  - `persona_counterfactual` using `weights.breakdown` per persona;
  - `USED_DATA_MISSING` for USED cars without used prices (FR-019).

  Add the localized texts to `B/orchestration/report_text.py`.
- [ ] T048 [US4] Reporter prompts (`B/orchestration/prompts/reporter_*.md`): pass the top 3 criteria by final weight and the profile summary. Lead with them, and say when another profile would choose differently, using only the counterfactual fact.
- [ ] T049 [US4] Run check, restart dev, deploy, then commit, push and merge ("007-E verdict per profile").

---

## Phase 8: User Story 6 — Intake does not contradict itself (P2) Increment F

**Independent Test**: the chat 757cff3d intake replay.

- [ ] T050 [P] [US6] Write `T/graph/test_offered_option_text.py`. An offered label sent back as text ("BMW 3 Series BMW 320d Touring M Sport") resolves to that option's variant id, and the reply has no "no such engine". Option labels never repeat the make or model.
- [ ] T051 [P] [US6] Tests in `T/unit/test_resolve_years.py`: with intent NEW/UNKNOWN and no year or code, the options and catalog reuse keep only current-generation rows (no F30/F31 for the 3 Series). With "used" or a year, older rows are allowed.
- [ ] T052 [US6] `B/orchestration/nodes/confirm.py` (`apply_variants`, `ask_node`): match text against the pending offered labels (normalised, rapidfuzz ≥ 90) before interpret. Fix the label builder (`B/application/identify.py::_choices_from_lineup` / the label helper) to drop a repeated make or model.
- [ ] T053 [US6] `B/application/resolve.py` (around :135 and the option lists): apply the current-generation filter. Add G20/G21 (3 Series, 2019–) to `C/generations.yaml` if it is missing.
- [ ] T054 [US6] Run check, restart dev, deploy, then commit, push and merge ("007-F intake fixes").

---

## Phase 9: Validation gaps (FR-030 to FR-034) Increment G

- [ ] T055 [P] Write the parametrised regression set `T/unit/test_review_regressions.py`, using the review's examples:
  - "Golf 1.0 TSI ... 1.500 kg" with parts 6,000 characters apart is rejected;
  - "150" inside "1500 rpm" is rejected;
  - gearbox "DSG" vs "manual" conflicts;
  - guard: "Расход 10 л/100 км, гарантия 7 лет" and "2019 год, 5 звёзд NCAP" are removed when they are not in the facts;
  - "Además, el precio del Golf es razonable." is not `sub_threshold`;
  - "moreover" is not a comparative.
- [ ] T056 Make the following changes in `B/domain/evidence.py`:
  - `occurs` takes `max_gap_chars` (200);
  - `validate_excerpt` matches digits at number boundaries;
  - `_agree` compares gearbox, body and fuel normalised.
- [ ] T057 Make the following changes in `B/orchestration/guard.py`:
  - remove the blanket `x <= 12 or 1950 <= x <= 2035` (line ~57) and allow small ints and years only from the facts (plus the car count);
  - compile `_ABSENCE`, `_COMPARATIVE`, `_WINNER` and `TOPIC_WORDS` into word-boundary regexes (stems keep `\w*`).
- [ ] T058 Run `scripts/repair-data.sh` in dry-run mode to see how many stored claims the stricter excerpt rules would reject. Report the count to the owner before applying (backup first in `backups/`). Then run check, deploy, commit, push and merge ("007-G validation gaps").

---

## Phase 10: Graph robustness (FR-027 to FR-029) Increment H

- [ ] T059 [P] Write graph tests in `T/graph/test_robustness.py`:
  - hops ≥ `max_hops` gives a partial localized answer, not FAILED;
  - a transient provider error in interpret is retried and then gives a localized "provider unavailable, data kept";
  - a timeout with saved research data gives a report from the saved data (rescore path).
- [ ] T060 Add a `hops` counter to the graph state, incremented in the policy node; `B/domain/policy.py` applies rule 0.
- [ ] T061 In `B/orchestration/graph.py`, add `RetryPolicy(max_attempts=2, retry_on=<transient provider errors>)` to the interpret, report and answer nodes. In `B/orchestration/runner.py`, the final failure gives a localized message (`B/orchestration/phrases.py`).
- [ ] T062 In `B/orchestration/runner.py`, on timeout with research results saved, start a `rescore` preset turn instead of the bare `run_timeout` text. Keep the existing message when nothing was saved.
- [ ] T063 Run check, restart dev, deploy, then commit, push and merge ("007-H graph robustness").

---

## Phase 11: User Story 7 — Advice without named cars (P3) Increment I

**Independent Test**: G36.

- [ ] T064 [P] [US7] Write tests in `T/unit/domain/test_policy.py`:
  - no cars + class or need + budget → SELECT_CANDIDATES;
  - no cars and nothing else → general.
- [ ] T065 [P] [US7] Write golden `T/golden/G36_advice_no_cars.yaml`. "посоветуй семейный кроссовер до 25к" gives a card with 2–3 candidates, each with a reason; a candidate without a sourced price shows "price to check".
- [ ] T066 [US7] Implement `B/application/candidates.py`: rank models of the class sold in ES within the budget from `C/makes.yaml`, `brand_lineups` and the catalog, with a code-computed one-line reason from the persona weights.
- [ ] T067 [US7] Wire SELECT_CANDIDATES into `B/orchestration/graph.py` and `B/orchestration/nodes/confirm.py`, reusing the intake card: remove or add a candidate, then confirm, then research.
- [ ] T068 [US7] Run check, restart dev, deploy, then commit, push and merge ("007-I candidates").

---

## Phase 12: Polish

- [ ] T069 [P] Write ADR-027 in `docs/adr/`: profile basis, weight breakdown, RESCORE and learned sources. Index it in `docs/adr/README.md`.
- [ ] T070 [P] Update `docs/review-2026-11-03.md`: mark the 007 items done with their PR numbers.
- [ ] T071 [P] Update `docs/next-session.md` for the step after 007 (spec 006 plan).
- [ ] T072 Run the quickstart.md sections A–I end to end on fakes. The live re-run of chat 757cff3d needs a cost estimate and the owner's approval first.

---

## Dependencies & Execution Order

The order is:

1. Phase 1 → Phase 2 (foundational).
2. Phase 3 (US5) needs only Phase 1 (T001) and can start right after it, in parallel with Phase 2.
3. Then US1 (Phase 4) → US2 (Phase 5) → US3 (Phase 6) → US4 (Phase 7):
   - US2 uses the basis from US1;
   - US3 needs the breakdown from US2;
   - US4 needs the rescore path from US3 to show changes, but its domain tests can start after US2.
4. US6 (Phase 8), G (Phase 9) and H (Phase 10) are independent of US1–US4 and can run in any order after Phase 2. H's timeout path (T062) needs US3's rescore.
5. US7 (Phase 11) comes after US1 and US2.
6. Polish comes last.

### Parallel opportunities

- T006 to T009 (US5 tests) run together. T012 runs in parallel with T010/T011.
- T020 to T023 run together. T030 is independent of the US1 implementation.
- T035 to T037 run together. T043 to T045 run together. T050/T051, T055 and T059 run in parallel.

## Implementation Strategy

- **MVP**: Phase 1 + Phase 3 (US5) as PR "007-A". It fixes the German-car search with no profile changes.
- **Then**: one PR per phase, each merged to main after `scripts/check.sh`, a dev restart and `scripts/deploy.sh up`.
- **Paid runs**: none are needed for any phase. A live check of chat 757cff3d or the goldens on the real stack needs a cost estimate and the owner's yes first.
