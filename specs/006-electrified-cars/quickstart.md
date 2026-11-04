# Quickstart: validating spec 006

## Prerequisites

- Docker Postgres up, migrations applied (`0011_market_facts`).
- `scripts/check.sh` green.
- Everything below runs on fakes and recorded search, except step G3, which is a live paid run. For G3, give an estimate and ask the owner first.

## A. Energy model and EV data

1. Unit `test_energy.py`, with the incident numbers:
   - **BYD Seal U DM-i**, PHEV, 18,000 km, HOT, home YES, daily unknown:
     - the share comes from 60 km/day and the real range;
     - the cost has two parts, electricity and petrol;
     - `consumption_weighted = 0.9` is never in `parts`.
   - **The same car without `consumption_cs`**: `missing == ["fuel consumption with an empty battery"]` and `annual_eur is None`.
   - **BEV with WLTP kWh**: no losses added. A display-based real test gets losses once.
   - **Ateca 1.5 TSI (ICE)**: identical to today's output (regression).
2. Unit `test_sense_ev.py`: the regression table (SC-003) of about 40 cases:
   - "60 kWh" as charging power → rejected;
   - "11 kW" as battery → rejected;
   - gross vs usable;
   - range 900 km on 40 kWh → rejected;
   - DC 10–80 in 3 min → rejected;
   - "0,9 l/100 km ponderado" → `consumption_weighted`;
   - "6,1 l/100 km con batería descargada" → `consumption_cs`;
   - an unmarked "5,8 l/100 km" on a PHEV → unclear, rejected;
   - the warranty "8 años o 160.000 km, 70 %" → three claims.
3. Graph `test_ev_research.py`: a PHEV with only a weighted figure gives a deeper specs job with the CS query, then "cannot be computed" in the TCO and `ownership_cost` in `not_compared`.

## B. Prices and charging situation

- Unit: the same BEV costs more per 100 km at mix NO than at YES with a night tariff. Both show `as_of` and basis.
- Unit: "плачу 12 центов за кВт·ч ночью" gives `home_electricity_eur_per_kwh = 0.12` (USER) and `night_tariff = true`.
- Unit (ask_value): the home-charging question is asked only in a fixture where YES vs NO flips the cheaper car, and never twice.

## C. Climate

- Unit: the same BEV in Sevilla + motorway vs Asturias + city gives different `real_km` and a different `factors` list.
- A sourced `range_real_summer` bypasses the HOT factor.

## D. Verdict, break-even, label, incentives

- Unit `test_incentives.py`:
  - the environmental label for BYD PHEV (≥ 40 km) is ZERO, Ateca petrol 2024 is C, RAV4 HEV is ECO;
  - break-even gives YEARS / NEVER / ALREADY_CHEAPER;
  - a subsidy with `valid_to` in the past is EXPIRED and not subtracted.
- Unit (criteria): efficiency on €/100 km ranks a PHEV, a BEV and an ICE on one scale. If one car has no estimate, efficiency is unknowable for all.

## E. Brands

- Unit: "BYD cuenta con 120 concesionarios en España" gives `dealer_count_es = 120`. "120 km de autonomía" is never taken as a count.
- Unit: an MG with no retention value has DEPRECIATION "insufficient data for this brand", without a class curve.

## F. Report

- vitest: the `electric` block renders the same rows for two cars, `null` renders as "not found", and the ru/es/en keys exist.
- vitest: a TCO ENERGY item with `parts` shows the split. An old payload without `parts` still renders.

## G. Goldens and live check

1. Golden dialogues (fake model + cassettes in `backend/tests/golden/`):

   | File | Dialogue | What it checks |
   |------|----------|----------------|
   | `g8_byd_vs_ateca.yaml` | BYD Seal U DM-i vs SEAT Ateca | SC-001: energy line for both cars, break-even, ZERO vs C |
   | `g9_model3_vs_320d.yaml` | Tesla Model 3 vs BMW 320d | BEV vs diesel on €/100 km |
   | `g10_mg4_vs_id3.yaml` | MG4 vs VW ID.3 | electric block with the same rows; MG residual "insufficient data" |
   | `g11_rav4_vs_sportage_phev.yaml` | Toyota RAV4 HEV vs Kia Sportage PHEV | the HEV has no electric share |
   | `g12_used_leaf.yaml` | used Nissan Leaf | battery health only when sourced |
2. Metrics: after the goldens, `intake_events` has `energy_missing`, `ev_rejected` and `weighted_blocked` rows where expected (FR-022).
3. **Live (paid)**: re-run the incident pair in a fresh chat. Expected:
   - SC-001: energy lines with inputs for both cars;
   - SC-002: no weighted figure priced;
   - at most 1 home-charging question.

   Estimate before running: about €0.15–0.30 of model and search calls.
