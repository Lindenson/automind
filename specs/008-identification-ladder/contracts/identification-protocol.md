# Contract: identification questions (extends spec 005 `intake-protocol.md`)

## Question items (`pending.items[]`, `questions` block)

```json
{
  "kind": "ENGINE | FUEL | POWER | GEARBOX | DRIVE | USED_AGE | MAKE_LINEUP | UNKNOWN_MODEL | CAR_IDENTITY | PROPOSE | REMOVE_OR_CHOOSE",
  "car": "car#2",
  "item": "ENGINE | FUEL | POWER | GEARBOX | DRIVE | YEAR | MODEL | MAKE | CHOICE",
  "text": "Skoda Octavia · nuevo (2024–) · diésel 2.0 TDI · potencia: ?\n¿Qué potencia: 116 CV o 150 CV?",
  "choices": [
    {"label": "2.0 TDI 116 CV", "level": "POWER", "fuel": "diesel", "engine_cc": 1968, "power_kw": 85,
     "engine": "2.0 TDI 116 CV", "make": "Skoda", "model": "Octavia"}
  ]
}
```

Rules:
- One item concerns one level of one car. Choices are options of that level only (FR-007).
- `text` starts with the car's status line while the car is not settled (FR-013):
  - each settled level is shown;
  - the asked level is shown as "?".
- When something the user said does not exist, `text` names it first: "El Audi A4 de 2023 no tiene 2.5; hay: …" (FR-004).
- A rephrased ask (2nd) never repeats the first text (FR-012).

## Quick replies (chips)

For a ladder question (FUEL/ENGINE/POWER/GEARBOX/DRIVE): each option, then "choose for me", then "remove {car}". These are always present (FR-008).

## Replies understood by code (before the interpreter)

| reply | effect |
|---|---|
| an option label (tapped or typed) | its structured fields are set as stated facts of that level |
| "choose for me" / yes / go ahead / any / "вперёд" / "adelante" / "к сравнению" | `chosen_for_me`: this level and the levels below are settled by the base-version rule |
| "remove …" | the car is removed (existing) |
| free text | interpreter → facts (engine, gearbox, year …) → identify again |

## Notices (turn `notices[]`)

- `level_replaced`: "año 2023 → B5 es de 1994–2001: ¿qué año?" (FR-005).
- `settled_by_rule`: "No respondido dos veces: tomé 2.0 TDI 116 CV (versión base)" (FR-010).
- `identity_less_certain`: no sourced list of versions (FR-020).
- `used_age_assumed`: "Audi A4: año no indicado — supongo ~3 años (50.000 km a ~15.000 km/año)" (FR-022).
- `warranty_status`: "Audi A4 (2023): garantía de fábrica hasta 2026" / "caducada en 2021" (FR-026).

## Report facts (to the report writer, `case_facts`)

Per used car:
- `used: year Y (stated|assumed: how), mileage M km`;
- `price used €X (source)` or `price used: no data`;
- `value now ≈ €V`;
- `warranty: remaining until Y | expired in Y (assumed?)`.

The writer must label these as figures for a used car (FR-027).
