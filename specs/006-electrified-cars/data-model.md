# Data Model: Electrified Cars

## 1. New attributes (`domain/specs.py` ATTRS; stored as claims / spec values, no migration)

| Key | Unit | Category | Plausible | Notes / sense rule (rule id) |
|-----|------|----------|-----------|------------------------------|
| `battery_kwh` | kWh | specs | 5–150 | Renamed in the label to "Battery (usable)". Usable only when the words say usable or net (`útil`, `neta`, `usable`, `net`, `нетто`); else the value goes to `battery_gross_kwh` (`sense.ev.gross_not_usable`). |
| `battery_gross_kwh` | kWh | specs | 5–160 | ≥ usable; usable ≥ 0.80 × gross, else both are kept and the pair is flagged (`sense.ev.gross_usable_ratio`). |
| `battery_chemistry` | text | specs | LFP, NMC, NCA, LMFP, Na-ion | Normalised from the words; an unknown string is rejected. |
| `range_wltp` | km | specs | BEV 100–900, PHEV 20–200 | ≤ usable_kwh × 10 (minimum 10 kWh/100 km) (`sense.ev.range_above_battery`). |
| `range_real` | km | measured | as above | Conditions recorded in `conditions`: summer / winter / motorway / mixed, plus the temperature when stated. |
| `consumption_ev` | kWh/100 km | specs | 10–35 | WLTP electric; basis plug. kW unit → rejected (`sense.ev.power_for_energy`). |
| `consumption_ev_real` | kWh/100 km | measured | 10–45 | basis `plug` or `battery` from words (`en el enchufe`, `at the wall`, `ab Steckdose`, `según ordenador`, `display`). |
| `consumption_cs` | l/100 km | specs | 3–12 | PHEV charge-sustaining (research R4). |
| `consumption_weighted` | l/100 km | specs | 0.2–3 | PHEV weighted WLTP; displayed only, never priced. |
| `charge_ac_kw` | kW | specs | 2.3–22 | kWh unit → rejected (`sense.ev.energy_for_power`). |
| `charge_dc_peak_kw` | kW | specs | 20–400 | ≤ 5 × usable_kwh (C-rate) (`sense.ev.c_rate`); a PHEV without DC → none. |
| `charge_dc_10_80_min` | min | specs | 10–90 | Must be a 10–80 % or 20–80 % window from the words; other windows are rejected (`sense.ev.dc_window`). |
| `battery_warranty_years` | years | manufacturer | 3–12 | Split from one warranty string. |
| `battery_warranty_km` | km | manufacturer | 50,000–1,000,000 | |
| `battery_warranty_soh_pct` | % | manufacturer | 60–80 | |
| `warranty_years` / `warranty_km` | years / km | manufacturer | 2–10 / 50,000–1,000,000 | Car warranty. |
| `dealer_count_es` / `service_points_es` | count | manufacturer | 1–2000 | Only next to a network word, and only for the ES market (`sense.brand.count_context`). |
| `heat_pump` | bool | specs | — | yes / no / optional. |
| `v2l_kw` | kW | specs | 1–11 | |
| `towing_kg` | kg | specs | 0–2500 | Existing attribute if present; reused. |
| `euro_standard` | text | specs | Euro 3–7 | For the environmental label. |

Every value keeps the existing claim fields (evidence_id, source_type, provenance class).

## 2. EnergyCar (input, `domain/energy.py`)

`car_id`, `powertrain` (ICE | MHEV | HEV | PHEV | EREV | BEV), `fuel` (petrol | diesel | None).

The consumption fields of today: `consumption`, `consumption_real`, `consumption_nedc`.

The EV fields from §1, each carried as `Num(value, basis)`:
- `basis ∈ {SOURCED, MEASURED, DERIVED}`;
- `meter ∈ {plug, battery, None}` for kWh figures;
- `conditions` for real ranges.

## 3. EnergyPrices / ChargingSituation / UsageContext

- **Price**: `kind`, `value`, `unit` (€/kWh | €/l), `as_of`, `source`, `basis` (ASSUMPTION | SOURCED | USER), `stale: bool`.
- **EnergyPrices**:
  - `home: Price`;
  - `public_ac: Price`;
  - `public_dc: Price`;
  - `petrol: Price`;
  - `diesel: Price`.
- **ChargingSituation**:
  - `home_charging` (YES | WORK | NO | UNKNOWN);
  - `basis` (STATED | INFERRED | ASSUMED);
  - `mix: {home, public_ac, public_dc}`, shares summing to 1;
  - `night_tariff: bool`.
- **UsageContext**:
  - `annual_km`;
  - `daily_km | None`;
  - `climate` (HOT | MILD | COLD | MOUNTAIN | None);
  - `motorway_share` (0–1, with basis).

## 4. EnergyEstimate (output)

| Field | Meaning |
|-------|---------|
| `car_id` | |
| `parts` | list of `EnergyPart(energy, km, per_100km, unit, price, annual_eur, how: str)` |
| `electric_share` | 0–1 or None, with `share_inputs: list[str]` |
| `factors` | list of `(name, value, reason)`: climate, motorway, losses, real-use allowance |
| `annual_eur` | sum of the parts, or None |
| `eur_per_100km` | annual ÷ km × 100, or None |
| `missing` | the named inputs when it cannot be computed; then `annual_eur = None` |
| `alt_scenario` | €/100 km in the other charging scenario (home ↔ public), for BEV/PHEV |
| `inputs` | the human-readable lines for the TCO item (every price with as_of and basis) |

Invariant: if `missing` is non-empty, `parts` is empty, `annual_eur` is None and `eur_per_100km` is None. `consumption_weighted` never appears in `parts`.

## 5. Profile and rates (CaseFile JSON, validators upgrade old rows)

- `Profile.home_charging: Literal["YES","WORK","NO","UNKNOWN"] = "UNKNOWN"`, plus `basis["home_charging"]` and `evidence["home_charging"]` (007 mechanism).
- `Profile.night_tariff: bool | None`.
- `Rates`:
  - `home_electricity_eur_per_kwh`, `public_ac_eur_per_kwh`, `public_dc_eur_per_kwh`: `ge=0`, because zero is allowed for free work charging;
  - the legacy `electricity_eur_per_kwh` is migrated into `home_electricity_eur_per_kwh` on read.

## 6. MarketFact (table `market_facts`, migration 0011)

| Column | Type | Notes |
|--------|------|-------|
| id | uuid pk | |
| market | varchar(4) | "ES" |
| key | varchar(60) | e.g. `subsidy.moves`, `irpf.ev_deduction`, `label.zero.benefits`, `subsidy.region.AN` |
| value | jsonb | `{amount_eur?, percent?, text, scope: national|regional|municipal, region_code?}` |
| valid_from / valid_to | date null | |
| status | varchar(10) | ACTIVE / EXPIRED / UNKNOWN, recomputed on read from the dates (`incentives.status`) |
| evidence_ids | jsonb | must be non-empty: unsourced facts are not stored |
| fetched_at | timestamptz | freshness 30 days |

Unique (market, key). Read through a `MarketFacts` port in `application/ports.py`.

## 7. Incentive view and break-even

- **IncentiveView**: `key`, `label`, `status`, `amount_eur`, `valid_to`, `source_url`, `as_of`. Only ACTIVE with an amount is subtractable.
- **BreakEven**:
  - `years: float | None`;
  - `verdict` (YEARS | NEVER | ALREADY_CHEAPER | UNKNOWN);
  - `inputs`;
  - `beyond_ownership: bool`.
- **EnvLabel**: `label` (ZERO | ECO | C | B | NONE | UNKNOWN), `rule`, `source_url`, `basis=DERIVED`.

## 8. Brand presence

Read from the `manufacturer` attributes of §1. A make with `new_in_market` and no retention value sets the DEPRECIATION item to `annual_eur=None`, label "insufficient data for this brand".

## 9. Metrics (FR-022)

Rows in `intake_events`:
- `kind="energy_missing"`, details `{missing: [...]}`;
- `kind="ev_rejected"`, details `{rule}`;
- `kind="weighted_blocked"`.

They are written best-effort and never fail the turn.
