# Research: The User's Profile Drives the Assessment

All findings were checked against main at f29a286 (2026-11-03). File references are relative to `backend/src/automind/` unless marked otherwise.

## R1. Why the German cars were not found (chat 757cff3d)

- **Template.** `queries.yaml` favourites are `'{make} {model} {generation} {variant} … {sites}'`. `research.identity_of` (research.py:156) passes the full `variant_name`, which already contains the model ("Golf Variant R 2.0 TSI 333 CV DSG 4MOTION"), and a generation code that pages never write ("Mk8.5"). The query is long, repeats words and contains codes that pages never write. With `site:a OR site:b OR …`, Google needs every word, so it returns 0.
- **Language.** The language of the area words is fixed per template: `reliability problems` goes to Spanish sites. `favourite_by_market` exists only for DE.
- **Cache.** `infrastructure/search/cache.py:94–99` stores results without checking for empty, with `cache_ttl_days` 7 (price 3). So 118 of 439 cached searches were empty and blocked retries for a week.

**Decision**:
- `search_plan.short_identity(Identity) -> str`, pure: make + model + `variant_key`. `variant_key` is the first token matching an engine code (`\d{3}[a-z]{0,2}`: 320d, 330e), else a named performance trim (R, GTI, RS3, AMG 43, M340i, N…) plus power, else displacement + fuel word. Words already present in make or model are dropped. Generation codes (Mk\d, [A-Z]\d{2}, "8.5") and gearbox and drive tokens (DSG, CVT, AT, MT, 4MOTION, xDrive, quattro, AWD, 4x4) are dropped.
- Favourite templates use `{short}` instead of `{model} {generation} {variant}`. Open templates keep the full identity for later rounds.
- Area words per market language: `favourite_by_market` for ES, DE and EN. FR and IT are added when such sites are configured. The default is the market of the first favourite.
- Retry: a FAVOURITE query with 0 hits is rendered once more with `{make} {model}` plus area words. This is planned as a new query of kind FAVOURITE_RETRY and is counted in the limits.
- Empty results: cached with `empty_result_ttl_hours` (6). The `empty` flag on the row is for metrics.

**Alternatives**: drop `site:` grouping (one query per site): rejected, it multiplies search calls about 4×. Rely on the AI follow-up queries: rejected, they run after round 0 and cost model calls.

## R2. Learned sources

**Data already there**:
- evidence rows have `url` and `source_type`, and claims link evidence to attribute and variant;
- selected spec values identify the accepted claims;
- research runs have area and market per job.

**Decision**:
- Table `learned_sources`.
- At the end of each research run, `application/learned_sources.update(run_id)` aggregates domains whose claims were selected (accepted) in this run, per (area, market).
  - Hits: upsert with `accepted_runs += 1`, `misses = 0`, `last_seen = now`.
  - Domains that were searched (appeared in hits) for that area but gave nothing accepted: `misses += 1`.
- Pure rules (`domain/learned.py`):
  - active when `accepted_runs >= min_runs (3)` and `misses < max_misses (5)`;
  - never active when `is_denied(domain)` or the domain is already a configured favourite for that area;
  - `source_type` comes from `classify_source` (so a fan club can never be MANUFACTURER).
- Round 0 appends at most `per_area` (4) active learned domains after the configured favourites of the same market, as one extra `site:` group.
- The metrics page lists them.

**Alternatives**: write learned sources into sources.yaml: rejected, because config files are reviewed by people and the runtime must not edit them. Compute the list on the fly from evidence every time: rejected, because the query is heavy and misses would not be tracked.

## R3. Profile fields and their basis

**Today**:
- `Profile.evidence` holds the user's words for some fields.
- `persona_source` is INFERRED or USER_EDIT.
- `annual_km_stated` is a bool.
- There is no ownership period.
- New or used lives in `budget.intent` and per-car `condition`.
- The monthly limit exists as `running_cost_limit`.

**Decision**:
- `ProfileBasis = Literal["STATED","INFERRED","ASSUMED"]`. `CaseFile.basis: dict[str, ProfileBasis]` covers persona, ownership_years, condition, annual_km, budget, monthly_limit, family, driving_style, region and usage.
- New `CaseFile.ownership_years: int | None` (1–20).
- Defaults per persona come from `profile_defaults.yaml`. PERFORMANCE: 4 years, 12,000 km; BUYER: 7 years, 15,000 km; EXPERT: 5 years; UNKNOWN: 5 years, 15,000 km, new. Defaults are applied by code with basis ASSUMED.
- Upgrade: a pydantic `model_validator(mode="before")` fills `basis` from the old flags (`annual_km_stated`, `persona_source`, `evidence`). No migration.
- Rule: STATED > INFERRED > ASSUMED. A lower basis never overwrites a higher one. The only exception is a USER_EDIT in the panel, which is STATED.

## R4. Inferring the profile from the dialogue

**Today**: interpreter.md:52–54 sets family, age_band and driving_style ONLY from the latest message. The history window is `history[-12:]` × 500 characters (interpret.py:79).

**Decision**:
- The interpreter may emit `set_profile` and `set_persona` with `basis: INFERRED` from any turn, with `evidence` = the user's words (must occur in the dialogue, checked by code like excerpts).
- Persona cues are listed in the prompt: trims (M Sport, GTI, R, AMG, RS, track), family words, economy words.
- The window becomes `interpret.history_turns` (16) × `history_chars` (800) in search.yaml. The case file (already in the prompt) is the summary of older turns.
- Code check: the evidence must be a substring of a user message of this chat, otherwise the field is dropped.

**Alternatives**: a separate `profile_infer` LLM node: rejected for now, because it adds one call per turn and the interpreter already sees the dialogue.

## R5. Questions by value

**Decision**: `domain/ask_value.questions(case, cars_facts, model, rules, candidates) -> list[QuestionKind]`, pure.
- For each field with basis ASSUMED or missing, among persona, ownership_years, annual_km, condition and family, take 2–3 plausible values from `profile_defaults.yaml` (for example km 8,000/15,000/30,000; years 3/6/10).
- Recompute the score winner and tie for each value with the facts available.
- Ask only if the outcome differs. Return at most 1 field, the one with the most outcome changes; ties are broken by config order.
- Before research there are no facts yet. Then a prior is used: the persona-only check "weights differ by ≥ 15 points" decides whether persona matters.
- Today's `profile_gaps.questions` remains for non-profile questions (FAMILY_SIZE for 7 seats) and is capped by the same 1-question rule.
- `intake.full_intake` becomes false in search.yaml (FR-007).

## R6. Weight breakdown

**Decision**: `domain/weights.breakdown(case, model, rules) -> WeightBreakdown`, pure.

Steps:
1. Base = persona weights (criteria.yaml).
2. For each rule in `profile_rules.yaml` whose field matches the case (family, driving_style, usage[], climate, annual_km bands, ownership_years bands, condition, region class), add points per criterion with `reason` = rule id.
3. Priorities (`strength_points`), reason `priority:<criterion>`.
4. Clip negatives to 0. Cap one criterion at `cap` (50).
5. Normalise the automatic weights to 100.
6. Apply the manual adjustments (`weight_adjustments: dict[criterion, float]` in points, may be negative; 0 weight = "excluded by you"). Clip and renormalise.

Output per criterion: base, contributions list[(reason, points)], manual, final. `weights_for` returns `.final`, so the scorer is unchanged.

Migration of `weights_overridden`: on read, `weight_adjustments = old_weights − automatic weights` (so the user sees the same numbers), and the flag is dropped.

## R7. RESCORE and the split fingerprint

**Today**: `policy.fingerprint` hashes everything into one value. "Nothing new" compares it with the previous one. PATCH saves and publishes but runs nothing. The preset path exists (runner.run_turn(preset), understand skips the LLM).

**Decision**:
- `fingerprint_data(case)`: cars (variant ids, condition, year, mileage), `data_version` (max `updated_at` of the variants' selected values), race, prediction.
- `fingerprint_params(case)`: persona, basis, profile (all fields), ownership_years, priorities, weight_adjustments, usage, budget, monthly limit, needs, annual_km, rates_override, language, compare_level.
- Policy:
  - data changed or stale → research;
  - only params changed → `RESCORE`;
  - neither → nothing new.
- PATCH: after `save_version`, `runner.start_preset(chat_id, {"kind":"rescore","changes":[…]})`. While a turn is RUNNING it still returns 409; the UI queues the patch.
- RESCORE runs compute (pure) and then `report_rescore`. That is one LLM call over facts plus the list of changes, with the guard. Its output is a short text and the updated blocks.
- A change in `condition` to USED is a data change: research is offered, not started. FR-019 says what is missing.
- Card edits before research: `apply_intake` writes the profile with basis STATED before research is planned. Research then takes its areas from that persona through `research_plan.areas_for(persona, criteria, condition)` (research_plan.py:111). The card edit therefore changes the plan with no new code there.

## R8. Assessment by profile

- **TCO horizon.** `tco.compute` takes `years = case.ownership_years or rates.horizon_years`. Depreciation uses `value_retention` at that year: the existing 3- and 5-year points are interpolated; beyond 5 years the 5-year point is extrapolated with the documented assumption rate, labelled ASSUMPTION. The block title is no longer the hard-coded "over 5 years" (compose.py:772).
- **Budget findings.**
  - `insights.budget(case, facts)`: price > budget.max → finding `OVER_BUDGET(car, amount)`;
  - monthly cost > limit → `OVER_MONTHLY(car, amount)`.
  - Verdict rule (documented in the verdict code): a car over budget cannot be the "best pick". It can be "best if the budget allows", and the in-budget runner-up becomes the pick when its score ≥ winner − 2 × TIE_MARGIN.
- **Counterfactual.** `insights.persona_counterfactual`: rerun `score` with each other persona's breakdown. If the winner differs, it emits `OTHER_PROFILE_WINS(persona, car)`. Existing counterfactuals (years, km) now use the user's numbers.
- **Persona-led text.** The reporter prompt gets the top 3 criteria by final weight, and the guard keeps it on facts.

## R9. Intake fixes (FR-024, FR-025)

- **What happened in chat 757cff3d.**
  1. The user wrote "Compare bmw 320d m line and vw golf variant 8.5 r".
  2. The bot offered "BMW 3 Series BMW 320d Touring M Sport". The duplicated "BMW" in the label comes from the label builder.
  3. The user sent that label back as a message. It went through interpret and the engine match again, and was rejected as "There is no such engine".
  4. The next options included an **F30** (old generation, sold until 2019), and the user picked it.

  So there are two defects: an offered label is re-validated instead of resolved, and old-generation rows are offered for a car with no year and no "used".
- **Offered option.** `confirm.apply_variants` and `ask_node` match a text reply against the labels offered in the pending step before interpret. Matching is normalised, with fuzzy ≥ 90 (rapidfuzz). A match resolves to that option's variant id, with no re-validation. The label builder drops a make or model repeated inside `variant_name`.
- **Generation.** `resolve.current_generation` exists (resolve.py:369), but option lists come from catalog and line-up rows of any generation. When intent is NEW or UNKNOWN and no year or code was given:
  - the options and the catalog reuse filter (resolve.py:135) keep only rows of the current generation;
  - older rows are offered only after "used" or a year.

  G20/G21 (3 Series, 2019–) is added to generations.yaml if it is missing.

## R10. Validation gaps (FR-030 to FR-034)

- `evidence.occurs`: the gap between parts must be ≤ `max_gap_chars` (200).
- `validate_excerpt`: digits matched with `(?<![\d.,])d(?![\d.,]*\d)`, so "150" does not match in "1500".
- `_agree` for text: compare normalised values for gearbox, body and fuel, the same way as drivetrain. Other free texts stay "agree".
- Guard: remove the blanket `x <= 12 or 1950 <= x <= 2035`. Allow small ints and years only when present in the facts numbers, plus ordinal words in sentences ("3 cars" when `len(cars) == 3`).
- Report check: compile each word list into `\b(?:…)\b` (Unicode word boundaries). Stems keep a trailing `\w*`.

## R11. Graph robustness (FR-027 to FR-029)

- `hops` in graph state is incremented by `policy`. At `graph.max_hops` (12), policy returns ANSWER_FROM_CONTEXT with `partial=True` and a localized notice. `recursion_limit` stays as the backstop.
- LangGraph `RetryPolicy(max_attempts=2, retry_on=transient)` on interpret, report and answer nodes. A final failure gives a localized "provider unavailable, data kept" message instead of FAILED.
- Timeout: runner, on `asyncio.TimeoutError`, checks whether the case has research results. If so, it runs a RESCORE preset turn (pure compute + facts-only text), so the user gets the report from the data already saved.

## R12. Candidate selection without named cars (US7)

**Decision**:
- Policy action SELECT_CANDIDATES when there are no cars, a vehicle class or need, and a budget or persona.
- `application/candidates.py` uses `makes.yaml` + `brand_lineups` (005) + the catalog to rank models of that class sold in ES within the budget (official price where known).
- It proposes 2–3 with a one-line reason computed by code from persona weights, for example "most practical in budget".
- The proposal goes on the confirmation card, then research.
- No guessing of prices: a model without a sourced price is shown as "price to check".

**Alternatives**: let the model suggest cars: rejected for the list itself (Principle III), but the model may phrase the reasons.
