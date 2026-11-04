# Research: Electrified Cars — Decisions

Each item: **Decision**, **Rationale**, **Alternatives considered**.

## R1. One energy module, one function per powertrain

**Decision**: `domain/energy.py` exposes `estimate(car: EnergyCar, prices: EnergyPrices, situation: ChargingSituation, use: UsageContext, cfg: EnergyConfig) -> EnergyEstimate`, dispatching on powertrain:

- `ICE` / `MHEV` / `HEV`: today's `tco.energy_consumption`, moved here unchanged (FR-005).
- `PHEV` / `EREV`: R2.
- `BEV`: R3.

`tco._energy` turns the estimate into one ENERGY item, with sub-lines for electricity and fuel and the full input list. When `estimate.missing` is non-empty, the item says "cannot be computed — missing: …" (FR-001).

**Rationale**: the TCO module already has 440 lines and C901 pressure. A pure module is testable with the incident numbers. MHEV never gets an electric share (edge case).

**Alternatives**: extending `_energy` in place (complexity limit, mixed concerns); an LLM estimate (violates III).

## R2. Plug-in hybrid: the electric share

**Decision**:

- Daily distance `d`:
  - `needs.daily_km` when known;
  - else `annual_km / driving_days` (`driving_days: 300`, assumption, labelled "daily distance unknown").
- Real electric range `R`: sourced real-world range when similar conditions exist (R6), else `range_wltp × ev_range_factor` (assumption), with climate factors (R6).
- Charging probability `h` per driving day (`energy.yaml habits`, labelled, overridable):

  | Charging situation | h |
  |--------------------|------|
  | home or work YES | 0.9 |
  | NO (public only) | 0.25 |
  | UNKNOWN | the scenario the question would choose (R5); before the answer, YES with the label "assumed" |

- Electric share `s = h × min(d, R) / d`, clamped to [0, 0.95]. Long trips are covered: `d` is an average, and `min(d, R)` caps a day.
- Electric km `= s × km`; fuel km `= (1 − s) × km`.
- Electricity per 100 km: charge-depleting `consumption_ev` (kWh/100 km).
  - When it is missing but `battery_usable_kwh` and `range_wltp` are sourced, it is derived as `usable ÷ range × 100` and labelled DERIVED.
  - Basis "plug" or "battery" is recorded; losses per R3.
- Fuel per 100 km: `consumption_cs` × the ICE real-use allowance.
- Missing CS consumption: the research plan marks the `specs` area unmet for this car (R10). After the deeper round, the estimate returns `missing=["fuel consumption with an empty battery"]`.

The weighted WLTP figure (`consumption_weighted`) is shown as a homologation figure only and never enters `estimate` (FR-002, SC-002).

**Rationale**: the share follows the user's life, not the homologation cycle. All inputs are visible.

**Alternatives**:
- the weighted figure × 1.8, today's rule: the incident;
- the EU "utility factor" curve: it describes fleet averages, not this user's charging; it could be offered as a later refinement.

## R3. BEV consumption and charging losses

**Decision**: consumption priority:

1. `consumption_ev_real`, a sourced test with its basis;
2. WLTP `consumption_ev` × `real_world_factor.BEV`, assumption.

Basis rules:
- EU WLTP figures are measured at the plug (homologation includes losses), so no losses are added.
- Real-world tests carry basis `plug` (e.g. ADAC Ecotest) or `battery` (the car's display). Display figures get `losses.home_ac: 0.10` or `losses.dc: 0.05`, weighted by the charging mix.
- An unknown basis on a test is treated as `battery`; this is the honest upper cost, and it is labelled.

Losses are added at most once (edge case).

**Rationale**: the double counting of losses is the most common error in EV cost tools. The meaning is a recorded basis, not a guess from the number.

**Alternatives**: always adding 10 % (double counts WLTP); never adding (under-costs display-based tests).

## R4. Meaning of consumption values for plug-in hybrids

**Decision**: `sense_ev.classify_consumption_phev(raw, excerpt)` decides from the words around the value (FR-008):

| Markers (es / en / de / ru) | Attribute |
|-----------------------------|-----------|
| `ponderad`, `weighted`, `gewichtet`, `взвешен`, `combinado` next to a value < 3 l/100 km | `consumption_weighted` (stored, not priced) |
| `batería descargada`, `sin batería`, `modo híbrido`, `charge sustaining`, `empty battery`, `depleted`, `leerer Akku`, `разряжен` | `consumption_cs` |
| `kWh/100`, `eléctric`, `electric`, `elektrisch` with a kWh unit | `consumption_ev` |
| none, value < 3 l/100 km, PHEV variant | `consumption_weighted` (a PHEV's headline WLTP figure is the weighted one) |
| none, value ≥ 3 l/100 km, PHEV variant | rejected as unclear (`sense.phev.unclear_consumption`); the research asks again with a CS query |

The rule runs before the existing `classify_consumption` for variants whose powertrain is PHEV or EREV. For other powertrains nothing changes.

**Rationale**: the incident value 0.9 was rejected as a unit error; it is really the weighted figure. Size alone never decides (edge case).

## R5. Charging situation and the question

**Decision**:
- `Profile.home_charging: Literal["YES", "WORK", "NO", "UNKNOWN"] = "UNKNOWN"`, with basis and evidence as in 007.
- The interpreter extracts it from words:
  - "garage", "plaza de garaje", "гараж", "charger at home", "wallbox" → YES;
  - "street parking", "no garage", "на улице" → NO;
  - "charge at work" → WORK.
- `ask_value` gets a field `home_charging` with candidates YES / NO. It asks only when the case has a PHEV/BEV and the winner or the tie changes between the two (SC-006); the existing one-question budget applies.
- When it is not asked, YES is assumed, labelled "assumed: you can charge at home — tell me if not". The report shows the other scenario's €/100 km in the electric block, so the impact is visible.

**Rationale**: it reuses 007's value-of-information machinery; there is no new question flow.

## R6. Climate and motorway factors

**Decision**: `energy.yaml factors`, applied only to estimated (not sourced-for-conditions) EV consumption and range (FR-013):

| Climate | Factor | Reason |
|---------|--------|--------|
| HOT | × 1.08 | air conditioning load, battery cooling |
| MILD | × 1.00 | |
| COLD | × 1.15 | heating, winter losses (one third of the year) |
| MOUNTAIN | × 1.20 | heating, climbs |

Motorway share:
- `usage` contains MOTORWAY → 0.6; CITY only → 0.1; else 0.3 (assumption);
- motorway extra for EVs: + 0.25 × the share.

Combined consumption = `base × climate × (1 + 0.25 × motorway_share)`. Range = usable kWh ÷ consumption.

A sourced real-world value for similar conditions (`range_real_summer` for HOT, `range_real_winter` for COLD/MOUNTAIN, `range_real_motorway` for motorway ≥ 0.5) bypasses the factors.

Combustion cars keep today's model: their climate effect is small, and FR-005 requires no change. Every factor applied is listed in the estimate's `factors`.

**Rationale**: documented, visible, overridable defaults (Assumptions). The numbers are typical published effects (ADAC, Recurrent and Geotab temperature studies). They are reviewed when sourced data exists.

## R7. Spanish energy prices

**Decision**: `config/energy.yaml prices`. Each entry has `value`, `unit`, `as_of`, `source` (URL or "assumption") and `freshness_days`. Kinds:

- `home_pvpc`, `home_fixed`, `home_night`;
- `public_ac`;
- `public_dc` (with a low–high range per network: Iberdrola, Endesa X, Tesla, Zunder, Ionity);
- `petrol`, `diesel`.

The values are filled in increment B from cited public pages (CNMC/OMIE PVPC averages, the operators' tariff pages, the EU Weekly Oil Bulletin for fuel), with their date.

User overrides:
- `Rates.home_electricity_eur_per_kwh`, `public_ac_eur_per_kwh`, `public_dc_eur_per_kwh`;
- a stated zero is accepted (free work charging), marked USER.

Home price used:
- `home_night` when the user mentions a night tariff;
- else `home_fixed` (labelled "typical fixed tariff").

The mix (FR-012):

| Charging situation | Home | Public AC | Public DC |
|--------------------|------|-----------|-----------|
| YES / WORK | 85 % | 5 % | 10 % |
| NO | 0 % | 40 % | 60 % |

The mix is labelled. Long-trip DC share rises with motorway share.

A price older than `freshness_days` is shown with its date and the "outdated" label. Refreshing it from search is out of scope for 006, because no new providers are added (Assumptions); the config date is the source of truth.

**Rationale**: one €0.25 price makes every comparison wrong (US3). Home vs motorway DC differs by four or more times.

## R8. Efficiency on one scale

**Decision**: the `efficiency` criterion uses `EnergyEstimate.eur_per_100km`, computed at the user's prices and mix. The scale in `criteria.yaml`: `eur_per_100km: [14, 2]` (worst → 0, best → 100, linear, clamped).

If any car has no estimate, efficiency is `unknowable` for all cars (the 007 mechanism), and the report says why (FR-023).

## R9. Break-even and verdict fairness

**Decision**: `incentives.break_even(price_a, price_b, running_a, running_b, active_incentives_a)`.

- Running cost = ENERGY + MAINTENANCE + ROAD_TAX per year from the TCO.
- The result is:
  - `years` rounded to 0.5;
  - "never" when the electrified car is not cheaper to run;
  - "already cheaper" when it is also cheaper to buy.
- Shown with inputs; it is flagged when it exceeds the ownership period.

`compute` drops `ownership_cost` (and efficiency, R8) from the ranking when one car's energy line is missing, with the notice "running cost not compared: … missing for …" (FR-014).

## R10. Research for EV attributes

**Decision**:

- `queries.yaml` gets `specs_ev` and `measured_ev` templates, used for PHEV/BEV/EREV variants in addition to the normal ones:
  - ES: `'{short} autonomía consumo kWh batería carga ficha {sites}'`, `'{short} autonomía real prueba {sites}'`;
  - EN: `'{short} range kWh/100km charging specs {sites}'`.
- PHEV only: `'{short} consumo batería descargada {sites}'`.
- `research_plan.minimum_met("specs")` for:
  - BEV: also `range_wltp` and (`consumption_ev` or `battery_usable_kwh`);
  - PHEV: also `consumption_cs` and (`consumption_ev` or (`battery_usable_kwh` and `range_wltp`)).

An unmet minimum plans a deeper round (FR-009), already supported via `RETRY_UNMET_HOURS` and DEEP rounds. Favourite sources get EV-capable sites (km77, motor.es, ev-database.org after a robots.txt check, ADAC for tests), configured in `sources.yaml`.

## R11. Environmental label and incentives

**Decision**: the label is derived deterministically, in `incentives.env_label(powertrain, range_ev_km, fuel, euro_std, year)`. The DGT rules sit in `config/incentives.yaml` with the source URL:

| Label | Rule |
|-------|------|
| ZERO | BEV, EREV, or PHEV with ≥ 40 km electric range |
| ECO | PHEV < 40 km, HEV, MHEV, gas |
| C | petrol Euro 4+ (2006+), diesel Euro 6 (2015+) |
| B | older petrol or diesel by year |

The label is shown with the rule and the source, labelled DERIVED.

Programmes:
- the purchase subsidy (MOVES or successor);
- the IRPF deduction;
- the regional plans.

They are market-level facts, researched in the new area `incentives`: once per market, freshness 30 days, stored in `market_facts`. Each has an amount, `valid_from`, `valid_to`, scope and evidence. `incentives.status(fact, today)` returns ACTIVE / EXPIRED / UNKNOWN. Only ACTIVE facts with an amount reduce the break-even price difference, labelled. EXPIRED is shown as expired (FR-016, SC-007).

Municipal road tax: the existing "not found" path. A sourced reduction is shown as a fact, never assumed.

## R12. Brand warranty, network and residual value

**Decision**:

- New attributes in the `manufacturer` area (per variant, make-level values repeated):
  - `warranty_years`, `warranty_km`;
  - `battery_warranty_years`, `battery_warranty_km`, `battery_warranty_soh_pct`;
  - `dealer_count_es`, `service_points_es`.
- A sense rule accepts a count only when it is within 40 characters of a network word (concesionarios, puntos de venta, talleres, dealers, service points, дилер) and the market is Spain (FR-017).
- A warranty string such as "8 años o 160.000 km, 70 %" is split into three claims (US6 AS2).
- `makes.yaml` gets `new_in_market: true` for the recent brands.
- For those makes, and for BEV/PHEV without a sourced retention value, the DEPRECIATION item uses no class curve. It says "insufficient data for this brand/powertrain" (FR-018).

The nearest-dealer lookup per region is shown only when a sourced page lists it; no map or provider is added.

## R13. Report and metrics

**Decision**:

- New block `electric` (contract in `contracts/blocks-electric-and-tco.md`): the same rows per car, `null` marks a gap.
- The `tco` block's ENERGY item gets `parts: [{energy: "electricity"|"petrol"|"diesel", km, per_100km, unit, price, annual_eur}]`.
- Explainers added to `tech_explainers.yaml`: weighted WLTP, charge-sustaining, usable vs gross, DC peak vs average, charging losses.
- FR-022 metrics use the existing `intake_events` style table with kinds:
  - `energy_missing` (car_key, missing inputs);
  - `ev_rejected` (rule);
  - `weighted_blocked`.

  These are written by `compute` and the sense hook; they never fail the turn.
