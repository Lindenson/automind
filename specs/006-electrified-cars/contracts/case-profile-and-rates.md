# Contract: profile.home_charging and energy price overrides

## Case file (REST `GET/PATCH /chats/{id}/case`, and the confirmation card)

```jsonc
"profile": {
  "home_charging": "UNKNOWN",          // YES | WORK | NO | UNKNOWN
  "night_tariff": null,                // true | false | null
  "basis": {"home_charging": "STATED"},
  "evidence": {"home_charging": "у меня гараж с розеткой"}
},
"rates": {
  "home_electricity_eur_per_kwh": 0.12,   // ge 0 (0 = free charging at work, marked USER)
  "public_ac_eur_per_kwh": null,
  "public_dc_eur_per_kwh": null,
  "fuel_eur_per_l": null,
  "diesel_eur_per_l": null,
  "labour_eur_per_h": null
}
```

- **Legacy field**: `rates.electricity_eur_per_kwh` is accepted on PATCH and read. It maps to `home_electricity_eur_per_kwh`.
- **PATCH of `home_charging`, `night_tariff` or any rate**: a parameters-only change. It starts a RESCORE turn (007): no search, new energy lines and verdict.

## Interpreter delta (LLM structured output, `CaseDelta`)

- `set_home_charging: "YES"|"WORK"|"NO"|null` with `evidence: str` (the user's words).
- `set_night_tariff: bool|null`.
- `set_rates` gains the three electricity keys.
- **Unit check**: a value given in "€/kWh" or "céntimos/kWh" is converted (12 c → 0.12). A value above 1.5 €/kWh is rejected as a unit error.

## Question (ask_value)

- `field: "home_charging"`, chips:
  - "Yes, at home" → YES;
  - "At work" → WORK;
  - "No, street parking" → NO.
- Only when a PHEV/BEV/EREV is compared and the cheaper car or the tie changes between YES and NO.
- At most once per chat: a recorded `asked` event blocks repeats (SC-006).
