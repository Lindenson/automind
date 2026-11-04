# Tasks: Electrified Cars and Chinese Brands

**Input**: design documents in `/specs/006-electrified-cars/`, namely plan.md, research.md (R1–R13), data-model.md, contracts/ and quickstart.md.

**Tests**: these are required. The spec asks for a sense-rule regression set (SC-003) and golden dialogues (SC-004). The constitution (IX) requires the pure core to be built test-first.

**Increments**: one PR per increment, A–G as in plan.md. Each phase below is one increment.

- Paths are relative to the repository root. The backend lives in `backend/` and the frontend in `frontend/`.
- `[P]` marks a task that can run in parallel: it touches a different file and depends on nothing unfinished.

## Phase 1: Setup

- [X] T001 Create `backend/config/energy.yaml` with these sections, each with comments:
  - `prices` (keys home_pvpc, home_fixed, home_night, public_ac, public_dc, petrol, diesel; fields value, unit, as_of, source, freshness_days; placeholder values copied from today's rates.yaml, labelled "assumption");
  - `habits` (driving_days 300, charge_probability YES 0.9 / NO 0.25);
  - `mix` (YES/WORK home 0.85, public_ac 0.05, public_dc 0.10; NO 0 / 0.4 / 0.6);
  - `losses` (home_ac 0.10, dc 0.05);
  - `ev_range_factor` (0.85);
  - `climate` (HOT 1.08, MILD 1.0, COLD 1.15, MOUNTAIN 1.20);
  - `motorway` (share MOTORWAY 0.6 / CITY 0.1 / default 0.3; extra 0.25).
- [ ] T002 [P] Add a config loader for energy.yaml next to the existing rates loader (`backend/src/automind/application/` config module that loads rates.yaml), and add a test that the file parses in `backend/tests/unit/test_config_files.py`.

## Phase 2: Foundational (blocks all stories)

- [X] T003 Add the new attributes from data-model §1 to `ATTRS` in `backend/src/automind/domain/specs.py`:
  - battery_gross_kwh, battery_chemistry, range_wltp, range_real, consumption_ev, consumption_ev_real, consumption_cs, consumption_weighted;
  - charge_ac_kw, charge_dc_peak_kw, charge_dc_10_80_min;
  - battery_warranty_years/km/soh_pct, warranty_years/km, dealer_count_es, service_points_es;
  - heat_pump, v2l_kw, euro_standard.

  Give each its plausible range and converter: kWh, kW, min, km and count converters reject the wrong unit. Also relabel battery_kwh to "Battery (usable)".
- [X] T004 [P] Unit tests for the new converters and plausible ranges (kW given for kWh fails; kWh given for kW fails) in `backend/tests/unit/domain/test_specs_ev.py`.
- [X] T005 Carry the EV attributes in `application/compose.py`: extend the facts/attribute lists so they reach the report and the data panel, and hide EV rows for ICE/MHEV/HEV as is done today for battery_kwh (`backend/src/automind/application/compose.py`).

**Checkpoint**: the attributes exist and are stored, but nothing uses them yet.

## Phase 3: US1 + US2 — honest energy cost and electric facts (increment A, MVP) 🎯

**Goal**: every car has an energy line or a named "cannot be computed". The PHEV cost comes from its charge-depleting (CD) and charge-sustaining (CS) consumption; a BEV's from kWh with losses added once. EV values are checked for meaning.

**Independent test**: quickstart A1–A3. The BYD fixture has two energy parts. The weighted 0.9 figure is never priced. Without CS consumption the car gets "cannot be computed".

### Tests first

- [X] T006 [P] [US1] Write `backend/tests/unit/domain/test_energy.py` covering:
  - ICE regression, identical to today's `tco.energy_consumption`;
  - HEV and MHEV with no electric share;
  - PHEV share with daily km known and unknown, home YES and NO, range above and below the daily distance;
  - PHEV CD figure derived from usable kWh ÷ WLTP range (labelled DERIVED);
  - PHEV without CS → `missing`;
  - BEV on WLTP (no losses added);
  - BEV with a display-based test (losses once);
  - the invariant that `consumption_weighted` never appears in `parts`.

  Use the incident numbers for BYD Seal U DM-i and Ateca.
- [X] T007 [P] [US2] Write `backend/tests/unit/domain/test_sense_ev.py`: a regression table of about 40 cases from quickstart A2. It covers:
  - unit confusions;
  - gross vs usable, and the usable/gross ratio;
  - range above what the battery allows;
  - DC time and power bounds, and the C-rate;
  - weighted / CS / CD classification;
  - an unmarked PHEV figure;
  - the meter (plug or battery) of a kWh figure;
  - real-range conditions;
  - a warranty string split into three claims.

### Implementation

- [X] T008 [US1] Create `backend/src/automind/domain/energy.py` with the data model §2–4 types:
  - EnergyCar, Num, Price, EnergyPrices, ChargingSituation, UsageContext, EnergyPart, EnergyEstimate;
  - `estimate()` dispatching per powertrain (R1);
  - `_fuel()` (moved from `tco.energy_consumption`), `_phev()` (R2), `_bev()` (R3).

  Keep every function at C901 ≤ 10.
- [X] T009 [US1] Rewrite `_energy` in `backend/src/automind/domain/tco.py` to build the ENERGY item from an EnergyEstimate:
  - the label lists the energies ("Energy (electricity + petrol)");
  - `parts` and `missing` are added to TcoItem;
  - "cannot be computed — missing: …" when inputs are missing.

  Keep `energy_consumption` as a thin wrapper for its existing callers. Remove `real_world_factor.PHEV` from `backend/config/rates.yaml`.
- [X] T010 [US1] Assemble the EnergyCar and context in `backend/src/automind/application/compose.py` `tco_car()`:
  - the EV values with basis and meter;
  - prices built from rates.yaml for now (one home price, until increment B);
  - the situation is UNKNOWN, assumed YES;
  - the usage comes from the case (annual_km, needs.daily_km, climate).
- [X] T011 [US2] Create `backend/src/automind/domain/sense_ev.py` with:
  - `classify_consumption_phev(raw, excerpt)` (R4);
  - `battery_kind(excerpt)` (usable / gross);
  - `meter(excerpt)` (plug / battery);
  - `range_conditions(excerpt)`;
  - `split_warranty(raw, excerpt)`;
  - the pair checks (usable vs gross, range vs battery, DC power vs battery C-rate).
- [X] T012 [US2] (done as module constants in `domain/sense_ev.py`, like `sense.py`) Add the EV markers to `backend/config/sense.yaml` in es/en/de/ru: weighted, CS, electric, usable/net, gross, plug/display, summer/winter/motorway, DC window.
- [X] T013 [US2] Hook `sense_ev` into `_sense_before` and attribute routing in `backend/src/automind/application/research.py`:
  - PHEV/EREV consumption claims are rerouted to consumption_weighted, consumption_cs or consumption_ev;
  - an unclear figure is rejected (`sense.phev.unclear_consumption`);
  - battery_kwh without a usable marker goes to battery_gross_kwh;
  - after the claims are accepted, the pair checks run per variant.
- [X] T014 [US1] Add EV query templates `specs_ev` and `measured_ev` to `backend/config/queries.yaml`, and the PHEV CS query (R10). Use them in `backend/src/automind/domain/search_plan.py` for PHEV/EREV/BEV variants.
- [X] T015 [US1] Add the EV minimums to `minimum_met("specs")` in `backend/src/automind/domain/research_plan.py`:
  - BEV: range_wltp plus (consumption_ev or battery_kwh);
  - PHEV: consumption_cs plus (consumption_ev or battery_kwh + range_wltp).

  An unmet minimum plans a deeper round (FR-009). Extend `backend/tests/unit/domain/test_research_plan.py`.
- [X] T016 [US1] Add the fallback for FR-001 to `backend/src/automind/orchestration/nodes/compute.py`: when a car's energy item has `missing`, a notice names it, using the new phrase `energy_missing` in en/ru/es in `backend/src/automind/orchestration/phrases.py`.
- [ ] T017 [P] [US1] Write `backend/tests/graph/test_ev_research.py`: a PHEV with only a weighted figure in the cassette gets a deeper specs job with the CS query, then a TCO "cannot be computed" and a notice.
- [ ] T018 [US2] Add metrics to `backend/src/automind/orchestration/nodes/common.py`: a helper that records `ev_rejected` and `weighted_blocked` in intake_events from the sense hook, and `energy_missing` from compute.

**Checkpoint**: increment A is done. Run `scripts/check.sh`, restart dev, deploy, and open the PR.

## Phase 4: US3 — Spanish prices and the charging situation (increment B)

**Goal**: the costs use dated Spanish prices and the user's home/public mix. The user can override prices. The home-charging question is asked at most once, and only when it matters.

**Independent test**: quickstart B. The same BEV costs clearly more with NO than with YES at the night tariff. A price the user types is used and marked USER.

- [X] T019 [P] [US3] Write the tests:
  - prices and mix: `backend/tests/unit/domain/test_energy_prices.py`;
  - stale price label;
  - user override and zero;
  - interpreter parsing of "12 центов ночью" and "plaza de garaje": `backend/tests/unit/application/test_interpret_charging.py`;
  - ask_value for home_charging: `backend/tests/unit/domain/test_ask_value.py`.
- [X] T020 [US3] Fill the `backend/config/energy.yaml` prices with cited values and dates (R7):
  - PVPC average and a typical fixed tariff;
  - the night price;
  - public AC and DC ranges per network;
  - petrol and diesel from the EU Weekly Oil Bulletin.

  Use web search with standard mode (free pages only). Put the source URL and as_of date in each entry.
- [X] T021 [US3] Update `backend/src/automind/domain/casefile.py`:
  - Profile `home_charging`, with basis and evidence, and `night_tariff`;
  - Rates gets home_electricity, public_ac and public_dc (ge=0);
  - a validator migrates legacy `electricity_eur_per_kwh` to home;
  - CaseDelta gets `set_home_charging` and `set_night_tariff`.
- [X] T022 [US3] Update `backend/src/automind/application/interpret.py` and its prompt:
  - extract the charging words with evidence;
  - convert electricity prices (céntimos/центы → €);
  - reject values above 1.5 €/kWh.
- [X] T023 [US3] Build EnergyPrices and ChargingSituation from config, profile and rates in `backend/src/automind/application/compose.py`, with the mix and the stale flag. The TCO inputs show each price with its as_of date and basis.
- [X] T024 [US3] Add the `home_charging` field to `backend/src/automind/domain/ask_value.py`:
  - candidates YES and NO;
  - only when a PHEV/BEV/EREV is in the case;
  - the existing one-question budget;
  - the chips follow `contracts/case-profile-and-rates.md`, in `backend/config/questions.yaml` en/ru/es.
- [X] T025 [US3] Make a PATCH of home_charging, night_tariff or the electricity rates a parameter change (RESCORE) in the 007 fingerprint split, in `backend/src/automind/domain/policy.py`. Extend its test.
- [X] T026 [US3] Add the "assumed home charging" notice and the alternative scenario (`alt_scenario`) in `backend/src/automind/orchestration/nodes/compute.py`.

## Phase 5: US4 — climate and motorway (increment C)

**Goal**: estimated EV range and consumption follow the region's climate and the motorway share, and the report names the factors.

**Independent test**: quickstart C. Sevilla + motorway and Asturias + city give different real ranges, with the factors listed.

- [X] T027 [P] [US4] Write the tests for the factors, the bypass by a sourced real value for similar conditions, and the motorway share from usage, in `backend/tests/unit/domain/test_energy_climate.py`.
- [X] T028 [US4] Implement `_factors(use, cfg, sourced_conditions)` in `backend/src/automind/domain/energy.py`. It is applied to BEV consumption and range and to the PHEV CD part only, and it is listed in `EnergyEstimate.factors`.
- [X] T029 [US4] Derive the motorway share from `case.usage` and pass the climate from the profile, in `backend/src/automind/application/compose.py`.

## Phase 6: US5 — fair verdict, break-even, label, incentives (increment D)

**Goal**: cars are compared on one €/100 km scale. Running cost never decides when an energy line is missing. The break-even, the environmental label and dated incentives are shown.

**Independent test**: quickstart D.

- [X] T030 [P] [US5] Write the tests in `backend/tests/unit/domain/test_incentives.py`:
  - env_label for BYD PHEV, Ateca, RAV4 HEV, a 2005 diesel and an EREV;
  - break-even YEARS, NEVER and ALREADY_CHEAPER;
  - incentive status from dates.
- [X] T031 [P] [US5] Write the tests for efficiency in €/100 km and its unknowable-for-all rule, in `backend/tests/unit/domain/test_criteria.py`.
- [ ] T032 [US5] Create `backend/src/automind/domain/incentives.py` with `env_label`, `status` and `break_even`. Create `backend/config/incentives.yaml` with the DGT label rules (with source URL) and the incentive keys to research.
- [X] T033 [US5] Switch `efficiency` in `backend/src/automind/domain/criteria.py` and `backend/config/criteria.yaml` to `eur_per_100km` (scale [14, 2]). Pass the estimates through `facts()` in `backend/src/automind/application/compose.py`.
- [X] T034 [US5] Add verdict fairness in `backend/src/automind/orchestration/nodes/compute.py`:
  - when any car lacks an energy line, add `ownership_cost` and `efficiency` to `not_compared` with a reason;
  - add the `break_even` and `labels` verdict fields from `contracts/blocks-electric-and-tco.md`.
- [ ] T035 [US5] Add migration `backend/alembic/versions/0011_market_facts.py` and the `MarketFact` model in `backend/src/automind/infrastructure/db/models.py`. Add a repository with get/upsert in `backend/src/automind/infrastructure/db/repositories.py`, and a port in `backend/src/automind/application/ports.py`.
- [ ] T036 [US5] Add the market-level area `incentives` (freshness 30 days) in `backend/src/automind/domain/research_plan.py`, with its queries in `backend/config/queries.yaml`. Extraction stores only facts with evidence, in `backend/src/automind/application/research.py`. The area is planned once per market when an electrified car is compared.
- [ ] T037 [US5] Build the incentives view in compose: only ACTIVE facts with an amount reduce the break-even price difference, and EXPIRED facts are shown as expired.
- [ ] T038 [P] [US5] Write the graph test `backend/tests/graph/test_incentives_area.py`: one incentives job per market, reused by a second chat within 30 days.

## Phase 7: US6 — brands: warranty, network, resale (increment E)

**Goal**: for every make the report shows the warranty, the Spanish network size with sources and dates, and resale value or "insufficient data".

**Independent test**: quickstart E.

- [ ] T039 [P] [US6] Write the tests for the count context rule, the warranty split, and DEPRECIATION "insufficient data" for new_in_market makes, in `backend/tests/unit/domain/test_brand_presence.py`.
- [ ] T040 [US6] Add the brand count context rule (`sense.brand.count_context`) in `backend/src/automind/domain/sense_ev.py`, and hook it in `backend/src/automind/application/research.py`.
- [ ] T041 [US6] Add manufacturer queries for warranty and battery warranty, and for dealers and service points in Spain, in `backend/config/queries.yaml`.
- [ ] T042 [US6] Add `new_in_market: true` for BYD, MG, Omoda, Jaecoo, Leapmotor, Xpeng, Zeekr, Lynk & Co, Ebro and DFSK in `backend/config/makes.yaml`. When set, the DEPRECIATION item reads "insufficient data" instead of the class curve (`backend/src/automind/domain/tco.py`, `backend/src/automind/application/compose.py`).
- [ ] T043 [US6] Show the warranty and network rows with dates in the data panel and the report, in `backend/src/automind/orchestration/report_text.py`.

## Phase 8: US7 — electric section and explainers (increment F)

**Goal**: a compact electric section with the same rows for each car, the energy split in the ownership cost, and explainers, all in ru/es/en.

**Independent test**: quickstart F, plus the MG4 vs ID.3 golden.

- [ ] T044 [P] [US7] Write the vitest tests for the `electric` block and the TCO `parts`, including an old payload without parts, in `frontend/src/lib/protocol.test.ts`.
- [ ] T045 [US7] Build the `electric` block in `backend/src/automind/application/compose.py`, following `contracts/blocks-electric-and-tco.md`. Add it to the layouts in `backend/config/report_layouts.yaml`.
- [ ] T046 [US7] Add `ElectricBlockSchema` and the TCO `parts`/`missing` to `frontend/src/lib/protocol.ts`.
- [ ] T047 [US7] Create `frontend/src/components/blocks/Electric.tsx`, register it in `BlockView.tsx`, and show the split in the TCO component.
- [ ] T048 [P] [US7] Add the i18n keys in `frontend/src/i18n/ru.ts`, `es.ts` and `en.ts`.
- [ ] T049 [P] [US7] Add 5 explainers in ru/es/en to `backend/config/tech_explainers.yaml`: weighted WLTP, charge-sustaining, usable vs gross, DC peak vs average, charging losses.
- [ ] T050 [US7] Extend the report text in `backend/src/automind/orchestration/report_text.py`:
  - the electric share sentence;
  - the cost per 100 km at home and in public;
  - the break-even sentence;
  - all in en/ru/es.

## Phase 9: Polish and goldens (increment G)

- [ ] T051 [P] Record the goldens g8–g12 with their cassettes in `backend/tests/golden/` (quickstart G1).
- [ ] T052 Check the FR-022 metrics after the goldens, with an assertion in `backend/tests/golden/test_golden.py`.
- [ ] T053 Update `docs/next-session.md` and the ADR for the energy model (`docs/adr/ADR-028-energy-model.md`).
- [ ] T054 Run the live check of the BYD/Ateca incident pair (paid; announce about €0.15–0.30 first, then fix what it shows).

## Dependencies

- Setup → Foundational → US1/US2 (A).
- A → B → C.
- D needs A; it uses the estimates, and the break-even uses B's prices.
- E is independent after Foundational.
- F needs A, B and D.
- G needs all of the above.

## Parallel opportunities

- A: T006 and T007 (tests). T011 and T012 (sense) can run alongside T008 and T009 (energy).
- D: T030 and T031. T035 (migration) alongside T032.
- E can run alongside B and C.
- F: T048 and T049 alongside T046 and T047.

## Implementation strategy

The MVP is increment A: it fixes the incident on its own. Ship it, then B (personal prices), then C and D, then E, F and G. Run `scripts/check.sh` after each increment, restart dev, deploy, and open the PR. PRs are merged without review, at the owner's request.
