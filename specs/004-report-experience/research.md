# Research: Report Experience

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Date**: 2026-11-02

Starting point (002/003 code): `orchestration/nodes/report.py` → `compute()` (scores, race, TCO, blocks in a
fixed per-persona order, `domain/report_layout.py`) → one reporter call (`prompts/reporter_<persona>.md`,
optionally with scoped MCP tools) on `compose.summary_for_llm` facts → `guard.check_numbers` drops numbers not
in the facts. Defects found live on 2026-11-02 are the regression set for this feature (see spec Context).

## R1. Deterministic insights before writing

- **Decision**: new pure module `domain/insights.py`. Input: per-car facts (specs, metrics, TCO, depreciation,
  reliability, manufacturer facts), the profile (priorities, usage, budget) and thresholds
  (`config/insights.yaml`). Output: a ranked list of `Insight {attribute, cars, values, diff, unit,
  meaningful, direction(better/worse), relevance (priority weight × magnitude), confidence, sources}` plus
  `ties` (differences under the threshold, grouped as "about the same").
  - Thresholds per attribute, absolute or relative: boot 30 L, consumption 0.5 l/100 km (or 5%), 0–100 km/h
    0.5 s, power 10%, price 5%, yearly cost €150, value retention 5 points, reliability score 10 points.
  - Relevance: attributes linked to the user's top priorities first; money expressed in the user's terms
    (per year at their km, over 5 years).
  - Trade-off detection: pairs of meaningful insights with opposite winners (A cheaper, B more economical)
    → `TradeOff {gain, cost, break_even}` (e.g. extra price ÷ yearly saving = years to break even).
- **Rationale**: the writer currently picks "interesting" facts itself and presents noise as wins; code can
  decide what is meaningful and decisive (constitution III).
- **Alternatives**: prompt-only instructions (tried in 003 follow-ups; not enforceable).

## R2. Verdict built by code, phrased by the model

- **Decision**: `domain/verdict.py` builds `Verdict {pick | tie, reasons (insight ids), trade_off, confidence,
  confidence_reason, would_change}` from the criteria ranking (common criteria, tie margin), the top insights
  and data coverage. Confidence: high = common criteria ≥ 80% of weight and the decisive insights from ≥ 2
  sources; medium = ≥ 60%; low otherwise (or a decisive conflict). "Would change": the insight whose flip
  would change the pick (e.g. "if you drive more than 25,000 km a year, the RAV4 wins"). The verdict card is a
  block rendered from this structure; the model writes only the one-line headline and the reasons' wording
  within the given facts.
- **Rationale**: the verdict must not depend on the model's mood; it is the first screen.

## R3. Consistency check: text vs blocks

- **Decision**: extend `orchestration/guard.py` into `report_check`:
  1. numbers not in the facts (existing);
  2. claims of absence ("no data", "insufficient", "нет данных", "sin datos") for an attribute/area that has
     data in the blocks;
  3. comparative words ("better", "more", "wins", "лучше", "больше") attached to an attribute whose insight
     is below the threshold;
  4. a winner named when the verdict is a tie.
  On violations: one regeneration with the violations listed; if it fails again, the offending sentences are
  removed and a notice is logged. Golden dialogues assert zero violations.
- **Rationale**: SC-003; the live report said "no ownership cost data" next to a TCO block.

## R4. Sense validation of values (FR-027)

- **Decision**: a `domain/sense.py` layer run after unit normalisation and plausibility (003), with rules per
  attribute in `config/sense.yaml`:
  - magnitude by context: service intervals in km must be 1,000–300,000 (3–300 read as thousands); months
    1–240 with "years" in the excerpt → ×12 (already in code after 2026-11-02, moved here as rules);
  - meaning: gearbox "1 speed" + CVT/hybrid → CVT/e-CVT, gear count not set; "0" seats, "0 l" boot → reject;
  - cross-checks: power vs mass vs claimed 0–100 (003), boot vs body class, consumption vs powertrain;
  - computed results: TCO maintenance above the class cap → estimate (done), total TCO per year outside
    [€800, €15,000] for a car under 15 years → flagged and not scored;
  - every rejection carries the rule id; metrics count them per rule.
  The 2026-11-02 defects become unit tests (regression set).
- **Rationale**: excerpt checks prove the text exists, not that the value means what the attribute means.

## R5. Variant identity with gearbox and drive (FR-028)

- **Decision**: `Variant` gains `transmission` (manual/automatic/dct/cvt/e-cvt/single) and `drive`
  (FWD/RWD/AWD) columns; the resolver returns them when the model is sold with several (config
  `generations.yaml` may list `transmissions` per generation); the relevance gate (003) adds a gearbox/drive
  signal (title/URL/table says "manual" for an automatic target → other variant); claims of `transmission`
  and `drivetrain` that contradict the variant are rejected as `OTHER_VARIANT`. Existing variants without them
  get them from accepted claims when unanimous; mixed ones are flagged for re-identification ("which
  gearbox?" question).
- **Rationale**: the CX-5 had "manual" and "automatic 6-speed" accepted together.

## R6. Rich content areas

- **Decision**: three research areas, using the favourites added after 003:
  - `depreciation`: residual value after 3/5 years (analysts: Autovista24, cap hpi, iSeeCars; editorial
    buying guides). Stored as `ValueRetention {years, share or eur, market, source, date}`; fallback is the
    labelled depreciation curve from `feasibility.yaml`.
  - `manufacturer` (exists, extended): market share trend, financial results, reliability reputation, dealer
    and parts network in Spain → `ManufacturerFact {kind, text, value?, year, source}` with new kinds
    `MARKET_SHARE`, `FINANCIAL`, `RELIABILITY_REPUTATION`, `NETWORK_ES`.
  - `engineering` (exists): adds `model_year_changes` (facelift, engine changes, recalls fixed).
  The engineering explainer uses a small catalogue `config/tech_explainers.yaml` (power-split hybrid, series
  hybrid, e-CVT, DCT, torque converter, MHEV, PHEV …) with short sourced or editorial descriptions, so the text
  explains what a difference means.
- **Rationale**: the user found the report boring: no technology, depreciation or manufacturer content.

## R7. Block structure and profile-driven content

- **Decision**: `report_layout` becomes a declarative layout per profile (`config/report_layouts.yaml`):
  sections (verdict, comparison, engineering, cost over time, value retention, reliability, reviews,
  manufacturer, data panel, sources) with `open_by_default`, `depth` (summary/full) and order per profile;
  the reporter prompt receives the profile and the section depth. The comparison table hides rows without
  data for any car and marks missing cells; the scores block shows values, relative-to-best and absolute.
- **Rationale**: the persona only reordered blocks; FR-019 needs content to change.

## R8. Data panel and "find it"

- **Decision**: notices about gaps are collected into one `data_panel` block: per car × area status
  (complete / partial / missing / unavailable-with-reason, last attempt). "Find it" sends a
  `research_more` with `focus_cars` and `areas` (003 request kind, extended with areas). After the research,
  the report is rebuilt and the panel shows a diff ("+12 values"). Gaps that failed recently with a hard reason
  (robots, not sold in Spain) show the reason and no button until the retry window.
- **Rationale**: one place for gaps (SC-008), one action to fix them.

## R9. Profile inference and questions

- **Decision**: extend the case profile (002) with `experience`, `family`, `age_band`, each with evidence
  (verbatim words, as `persona_evidence`). A deterministic `domain/profile_gaps.py` decides which unknowns
  change the answer for the current comparison (e.g. km per year when a hybrid and a petrol differ by > €150 a
  year at different mileages; family size when boots differ meaningfully; budget when prices differ > 15%)
  and the policy asks at most 3 (one round, with suggested answers as buttons). Asked before research when
  cheap to answer; never when the answer would not change the verdict.
- **Rationale**: FR-017/018; the live chat never asked anything and kept a default persona.

## R10. Dialogue actions: suggestions, critique, "this is wrong"

- **Decision**:
  - suggestions: code builds 3–4 from the verdict and gaps (why is X ahead?, what if used?, compare on
    reliability, cheaper alternative, find missing data) → a `suggestions` block; a click sends the request.
  - critique: interpreter kind `critique` (with optional target: car/area/section) → policy: gaps in target →
    `research_more`; no gaps → `rework` (report rebuilt with the target section opened and emphasised, and the
    reporter told what the user disliked). The reply starts with what was done. Golden dialogues assert the
    report changed (fingerprint of blocks/text).
  - "this is wrong": a `challenge {car, attribute | claim id}` message → re-check: re-validate the claims of that
    value (sense + validator with the case), fresh search for that attribute if needed, then show
    confirmed/corrected/removed.
- **Rationale**: FR-020–FR-022, SC-005.

## R11. Progress grid

- **Decision**: research jobs already emit `status` with `car` and `area`; add a `progress` event
  `{car, area, state: queued|searching|reading|done|failed|paused, accepted}`; the UI keeps a car × area grid;
  the WebSocket resend-on-reconnect (003 fix) sends the latest progress snapshot.
- **Rationale**: FR-023.

## R12. Interface language and layout

- **Decision**: a tiny i18n layer in the frontend (`src/i18n/{en,ru,es}.ts`, `t(key)`), the language from the
  latest `assistant_message.language` (backend already detects it) with a manual switch stored per browser;
  backend fixed phrases already exist in `phrases.py`. Layout: verdict card and data panel full-width on
  phones; the comparison table becomes per-row cards under 640 px.
- **Rationale**: FR-024/025; no i18n library needed for three languages (constitution X).

## R13. Ratings and evaluation

- **Decision**: `report_ratings` table (message id, 1–5, note, created); a small rating control under each
  report; golden dialogues 004 (G12–G18) cover verdict, tie, trade-off, critique, challenge, questions,
  Russian UI; the defect regression set as unit tests.
