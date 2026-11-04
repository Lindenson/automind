# Data model: spec 008

## ModelVersions (table `model_versions`, new: migration 0013)

| field | type | rule |
|---|---|---|
| id | uuid str(36) | pk |
| make, model | str(80) | canonical make and model (registry spelling) |
| generation | str(40) | generation code as sourced ("Mk4", "B9", "NX") |
| market | str(4) | "ES" |
| years_from, years_to | int? | the generation's years; `years_to` null = on sale |
| body_class | str(16)? | HATCHBACK…PICKUP |
| versions | jsonb list | each: `{engine, fuel, engine_cc, power_kw, gearboxes[], drives[], years_from, years_to, source_url, excerpt}` |
| sources | jsonb list | `{url, name}` of the documents that supplied kept versions |
| fetched_at | timestamptz | freshness: reused while `now − fetched_at < intake.versions_ttl_days` (60) |

Unique: (make, model, generation, market).

Lookup:
- by generation code;
- by year (the span covers the year ± 1);
- for a new car: `years_to` null.

## Version (domain value, `domain/ladder.py`)

| field | type | rule |
|---|---|---|
| engine | str ≤ 80 | as the source writes it, with power ("2.0 TDI 150 CV") |
| fuel | petrol, diesel, hybrid, mhev, phev, bev, lpg, or none | |
| engine_cc | int? | from the displacement or parsed from the engine label |
| power_kw | int? | required in practice (validation needs the power written) |
| gearboxes | tuple of manual, automatic, dct, cvt, e-cvt, single | source order |
| drives | tuple of FWD, RWD, AWD | source order |
| years_from / years_to | int? | the years this version was sold |
| source_url, excerpt | str | evidence (constitution I) |

The derived properties are `cv`, `family` and `engine_key`.

## Generation (domain value)

The make, model, generation, years, body_class, versions[] and sources[] of one row.

## Choice (CaseFile, extended)

New optional fields:
- `level` (FUEL, ENGINE, POWER, GEARBOX, DRIVE, or none);
- `fuel`;
- `engine_cc`;
- `power_kw`;
- `gearbox`;
- `drive`.

A tapped ladder option sets exactly these as the user's stated facts; its label is not parsed.

## CaseCar (extended)

- `year_assumed: bool = False`: the year was assumed (FR-022). It is shown wherever the age is used.
- `ladder: LadderMemo | None`:
  - `levels: dict[str, str]`: a snapshot of the level values at the last identify (GENERATION, YEAR, FUEL, ENGINE, POWER, GEARBOX, DRIVE);
  - `origin: dict[str, "STATED" | "CHOSEN" | "LIMIT"]`: who settled each level (the hub-written ones are cleared on a higher correction);
  - `certainty: "SOURCED" | "LESS_CERTAIN" | None`;
  - `generation: str | None`: the generation the list belongs to.

`IntakeItem` gains FUEL, POWER and DRIVE. Attempts per car and item are kept as before.

## Identification state transitions (per car)

```
NO_MAKE ─make─▶ NO_MODEL ─model─▶ (USED ∧ no year) ─year | 1 ask→assume─▶ GENERATION
GENERATION ─list found─▶ LADDER(level) ─option / stated─▶ LADDER(lower level) … ─▶ SETTLED(variant)
LADDER(level) ─choose for me─▶ SETTLED (descends with the first options; origin CHOSEN)
LADDER(level) ─2 asks unanswered─▶ next level (first option; origin LIMIT, note)
LADDER(level) ─nothing fits─▶ LADDER(same level) with "missing" text
any ─remove─▶ REMOVED
GENERATION ─no list─▶ FALLBACK (catalog/resolver; PROPOSED; LESS_CERTAIN)
SETTLED ─correction at level L─▶ LADDER(L) with hub-written levels below L cleared
```

## Used-car facts (computed, not stored)

- `age_years`: stated, or `used.assumed_age(...)` → (years, how).
- `used_price_eur`, `used_price_src`: from `used.used_price_for(ranges, year)`.
- `warranty`: `used.warranty_status(first_year, brand_years, now)` → `{state: REMAINING|EXPIRED|UNKNOWN, until: year, assumed: bool}`.

## CarFacts / TcoCar (extended)

- `metrics.CarFacts`: `used_price_eur: float | None`, `mileage_km: int | None`.
- `tco.TcoCar`: `used_price_eur: float | None`.
