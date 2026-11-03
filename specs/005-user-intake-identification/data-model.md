# Data Model: Understanding the User — Intake and Identification

**Feature**: 005-user-intake-identification | **Date**: 2026-11-03

Changes against spec 004. Case-file fields live in the case JSON (`case_files.data`). Tables are created by migration `0008_intake`.

## Case file (JSON)

### EngineHint (new, inside `Constraints.engine_hint`)

| Field | Type | Rule |
|---|---|---|
| displacement_l | float \| null | 0.6–8.0. "1.5", "1,5", "1500" → 1.5 |
| power_hp | int \| null | 40–1000 (CV/PS/л.с./hp, all treated as metric hp) |
| power_kw | int \| null | 30–750; if only hp is given, kw = round(hp × 0.7355) by code |
| fuel | `petrol` \| `diesel` \| `hybrid` \| `mhev` \| `phev` \| `bev` \| `lpg` \| null | from words or the family |
| family | str \| null | ≤ 16 chars, as written: TSI, TDI, DM-i, e:HEV, EcoBoost |
| evidence | str | ≤ 120 chars: the user's words |

The deterministic `identity.parse_engine(text)` and the interpreter both fill it. A field the parser found wins over an empty interpreter field. A conflict keeps the parser's value and is logged.

### CaseCar (changed)

| Field | Change |
|---|---|
| request_text | kept as the user's first words; **display_name** (new, computed) = make + model + engine/trim facts, used in every question |
| previous_label | new, str \| null: the label before the last correction (for "before → after") |
| resolution | `UNKNOWN_MODEL` is still allowed for old cases but is recomputed each turn by `identify` |
| identify | new: `{outcome: IDENTIFIED\|CHOICES\|NEED\|NOT_FOUND, need: item\|null, choices: [Choice], checked: [source urls], at: datetime}` |

`Choice` = `{label, make, model, variant_id?, engine?, body?, powertrain?, price_from_eur?, source_url?, suggested: bool, reason?: str}`.

### Intake (new, `CaseFile.intake`)

| Field | Type | Rule |
|---|---|---|
| attempts | {car_key: {item: int}} | item ∈ MAKE, MODEL, ENGINE, GEARBOX, YEAR, CONDITION, MILEAGE, TRIM, CHOICE |
| last_questions | list[str] (≤ 6) | sha1(car_key, item, text)[:12]; the newest last |
| proposed | {car_key: Choice} | the car the assistant proposed after 2 attempts |
| card | IntakeCard \| null | the card last shown (for highlighting edits) |
| card_confirmed | bool | true after "yes"; reset by any identity or profile change |

Limits (config `search.yaml: intake`): `max_attempts_per_item: 2` (then PROPOSE) and `max_attempts_per_car: 4` (then "remove or choose for me").

### Profile (changed)

| Field | Type | Rule |
|---|---|---|
| region | str \| null | as the user wrote it, ≤ 60 chars, with evidence |
| region_code | str \| null | normalized community/province from `regions.yaml` |
| climate | `HOT` \| `MILD` \| `COLD` \| `MOUNTAIN` \| null | derived from region_code by config (basis INFERRED) |
| annual_km_min / annual_km_max | int \| null | 1,000–200,000; min ≤ max; `annual_km` = the rounded middle |
| evidence | dict | gains keys region, annual_km |

### IntakeCard (pending kind `CONFIRM_INTAKE`)

```text
IntakeCard
  cars: [CardCar]
  profile: [CardItem]          # usage, annual_km, region, climate, budget, priorities, family, experience
  cost: {eur, over_cap, areas[], depth}
CardCar
  key, display_name
  items: [CardItem]            # make, model, generation, engine, power, fuel, gearbox, drive, year, condition,
                               # mileage (used), trim, trim_level, price_eur (new)
CardItem
  field, value (display text), basis: STATED|INFERRED|LOOKED_UP|ASSUMED,
  evidence?: str (user words), source?: {name, url, retrieved_at}, changed: bool,
  options?: [str]              # chips: alternatives the user can pick (other engines, gearboxes, years)
```

State transitions of the pending intake:

```text
QUESTIONS ──reply──► (identify) ──► QUESTIONS (next item) | PROPOSE (after 2 attempts) | CONFIRM_INTAKE
PROPOSE ──yes──► CONFIRM_INTAKE        PROPOSE ──no / other text──► QUESTIONS (attempt +1)
CONFIRM_INTAKE ──edit chip / text──► CONFIRM_INTAKE (changed items highlighted)
CONFIRM_INTAKE ──yes──► research (variants CONFIRMED, cost approved below the hard cap)
any state ──identity change──► card_confirmed = false, affected car UNRESOLVED
```

## Tables

### vehicle_variants (changed)

| Column | Type | Note |
|---|---|---|
| engine_cc | int \| null | 600–8000 |
| power_kw | int \| null | 30–750 |
| fuel | varchar(8) \| null | petrol\|diesel\|hybrid\|mhev\|phev\|bev\|lpg |

Back-fill: parse `variant_name` ("1.5 TSI 150 CV", "2.0 TDI 110 kW") by `identity.parse_engine`. Unparsed rows stay null.

### brand_lineups (new)

| Column | Type | Note |
|---|---|---|
| id | varchar(36) PK | |
| make | varchar(80) | canonical make; unique with market |
| market | varchar(2) | `ES` |
| models | JSONB | `[{model, body, powertrains[], price_from_eur?, excerpt, source_url}]` |
| sources | JSONB | `[{url, name, type, retrieved_at}]` |
| fetched_at | timestamptz | refreshed after `lineup_ttl_days` (default 30) |

Validation: every `model` occurs in the text of its source document (`evidence.occurs`), and a price must occur in its excerpt. At least 1 official or price-list source per make (otherwise not stored; the lookup result is NOT_FOUND).

### intake_events (new, chat-scoped)

| Column | Type | Note |
|---|---|---|
| id | varchar(36) PK | |
| chat_id | varchar(36) FK chats ON DELETE CASCADE | |
| turn_id | varchar(36) | |
| car_key | varchar(16) \| null | |
| kind | varchar(20) | ASKED, ANSWERED, CORRECTED, PROPOSED, CARD_SHOWN, CARD_EDITED, CONFIRMED, RESEARCH_STARTED |
| item | varchar(16) \| null | as in Intake.attempts |
| details | JSONB | text_hash, progress, before/after, all_confirmed |
| created_at | timestamptz | |

Metrics derived (domain/metrics): replies to confirmed identity per chat, repeated questions, corrections changing identity, research on unconfirmed cars.

## Config

- `makes.yaml`: `{canonical: {aliases: [..], translit: [..], es_site: "byd.com/es", group: "Chery"?}}`, about 60 makes.
- `regions.yaml`: `{code: {names: [..ru/es/en..], climate: HOT|MILD|COLD|MOUNTAIN}}` for the 17 communities and 50 provinces.
- `questions.yaml` v2: `{KIND: {en, ru, es, rephrase: {en, ru, es}}}`. New kinds: CONDITION, ENGINE, MAKE_LINEUP, PROPOSE.
