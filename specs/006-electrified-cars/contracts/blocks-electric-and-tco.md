# Contract: `electric` block and TCO energy split (WS `assistant_message.blocks`)

Backend: Pydantic in `application/compose.py` (block builders). Frontend: Zod in `frontend/src/lib/protocol.ts`. Unknown fields are ignored by the client. An invalid block is dropped with a console warning, and the others are kept (existing behaviour).

## 1. New block `electric`

Present only when at least one compared car is a BEV, PHEV or EREV (FR-019).

```jsonc
{
  "type": "electric",
  "title": "Electric",                 // in the chat language
  "rows": ["battery", "range", "consumption", "charging_home", "charging_dc", "battery_warranty",
           "heat_pump", "electric_share", "cost_per_100km"],   // same row set for every car
  "cars": [
    {
      "car_id": "uuid",
      "label": "BYD Seal U DM-i 1.5 Boost",
      "powertrain": "PHEV",
      "values": {
        "battery":        {"usable_kwh": 18.3, "gross_kwh": null, "chemistry": "LFP", "sources": [SourceRef]},
        "range":          {"wltp_km": 80, "real_km": 62, "real_basis": "ASSUMPTION",
                           "factors": ["hot climate ×1.08", "motorway 30 % ×1.075"], "sources": [...]},
        "consumption":    {"kwh_per_100km": 19.8, "basis": "DERIVED", "meter": "plug", "sources": [...]},
        "charging_home":  {"ac_kw": 6.6, "full_h": 3.0, "sources": [...]},          // full_h computed
        "charging_dc":    {"peak_kw": 18, "min_10_80": null, "sources": [...]},     // null = not found
        "battery_warranty": {"years": 8, "km": 250000, "soh_pct": 70, "sources": [...]},
        "heat_pump":      {"value": "yes", "sources": [...]},
        "electric_share": {"share": 0.62, "inputs": ["≈60 km a day (18,000 km ÷ 300 days, assumption)",
                           "real electric range 62 km", "home charging: assumed yes"]},   // PHEV/EREV only
        "cost_per_100km": {"home_eur": 3.1, "public_eur": 9.4, "used_eur": 4.6, "mix": {"home": 0.85,
                           "public_ac": 0.05, "public_dc": 0.10}, "basis": "ASSUMPTION"}
      }
    }
  ],
  "not_electric": [{"car_id": "uuid", "label": "SEAT Ateca 1.5 TSI DSG", "cost_per_100km_eur": 11.4}],
  "notes": ["Prices as of 2026-11: home fixed €0.14/kWh (assumption) …"]
}
```

Rules:
- A missing value is `null`, and the UI shows "not found" (the i18n key `electric.not_found`).
- Every number that comes from a claim carries `sources`. Computed values (`full_h`, `real_km` from factors, `share`) carry `basis` and `inputs` instead.
- `not_electric` lets a mixed comparison show both cars on cost per 100 km (US7 AS2).

## 2. TCO item `ENERGY`: added fields

```jsonc
{
  "kind": "ENERGY",
  "label": "Energy (electricity + petrol)",
  "annual_eur": 1214.0,                      // null when it cannot be computed
  "five_year_eur": 6070.0,
  "basis": "ASSUMPTION",
  "inputs": ["electric share 62 % (…)", "electricity 19.8 kWh/100 km (derived: 18.3 kWh ÷ 80 km WLTP) × 1.08 hot",
             "home €0.14/kWh fixed tariff (assumption, 2026-11)", "petrol 6.1 l/100 km charge-sustaining × 1.15",
             "petrol €1.55/l (EU Weekly Oil Bulletin 2026-10-27)", "18,000 km/year"],
  "sources": [SourceRef],
  "parts": [                                  // NEW, optional (absent for old cached reports)
    {"energy": "electricity", "km": 11160, "per_100km": 21.4, "unit": "kWh", "price": 0.14, "annual_eur": 334.0},
    {"energy": "petrol", "km": 6840, "per_100km": 7.0, "unit": "l", "price": 1.55, "annual_eur": 742.0}
  ],
  "missing": []                               // NEW: non-empty ⇒ annual_eur null, label "cannot be computed — missing: …"
}
```

Zod: `parts: z.array(EnergyPartSchema).nullish()` and `missing: z.array(z.string()).nullish()`. Old payloads stay valid.

## 3. Verdict additions

- `verdict.not_compared` gets `"ownership_cost"` and/or `"efficiency"` when an energy line is missing, with `verdict.reasons[criterion]` as a string in the chat language (FR-014).
- A new optional `break_even` object:

  ```jsonc
  {"break_even": {"electrified_car_id": "uuid", "against_car_id": "uuid", "verdict": "YEARS",
                  "years": 4.5, "beyond_ownership": false,
                  "inputs": ["price difference €4,300 (no active subsidy)", "running cost €1,940 vs €2,900 a year"]}}
  ```

- A new optional `labels` object: `{"<car_id>": {"label": "ZERO", "rule": "PHEV ≥ 40 km electric range", "source_url": "https://www.dgt.es/…"}}`.
- A new optional `incentives` list of IncentiveView (data-model §7). The UI shows EXPIRED items struck through, with "expired on <date>".
