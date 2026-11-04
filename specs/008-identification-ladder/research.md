# Research: spec 008

## R1. Where the list of versions comes from

- **Decision.** A sourced list per model generation and market (Spain), stored in a shared cache table `model_versions` (make, model, generation, market unique; versions JSON; sources; years; body; fetched_at).
  - On a miss: one Spanish search: "{make} {model} {year|generation|nuevo} versiones motores potencia CV ficha técnica".
  - At most 3 readable pages, through the page store (robots, deny-list).
  - The `versions` web reader extracts the versions, and code validates them.
- **Rationale.** Neither the catalog nor the resolver knows which versions exist. The catalog only holds versions researched before (the 115 CV row), and the resolver answers one guess. A sourced list is the only base for "offer what exists" and for "say what does not exist". One lookup per generation, shared by all chats, costs about one search and one flash call.
- **Alternatives considered:**
  - catalog rows only: incomplete, and the root of the incident;
  - resolver alternatives: unsourced, mixes generations;
  - per-chat lookup without a cache: repeated cost, inconsistent answers;
  - paid data providers: out of scope.

## R2. Validation of the extracted versions

- **Decision.** A version is kept only when all of these hold:
  - (a) its document is one of the pages read;
  - (b) its excerpt occurs in the document (`evidence.occurs`);
  - (c) its power in CV or kW is written in the excerpt;
  - (d) its years overlap the generation's years when both are known.

  Duplicates by (fuel, displacement/100, power/3 kW) are merged, keeping the first, which keeps the source's base-first order. A list with zero kept versions is not stored.
- **Rationale.** This is constitution I and FR-017. Source order gives the "base version first" rule for "choose for me".

## R3. The ladder levels and grouping

- **Decision.** Levels in this order:
  - GENERATION, from the year for a used car or "on sale" for a new one; not a question when known;
  - ENGINE: one question listing full engine labels ("2.0 TDI 150 CV") when ≤ 6 distinct engines remain. With more than 6, it is asked coarse-to-fine:
    - FUEL, when fuels differ;
    - then FAMILY ("2.0 TDI", displacement + family);
    - then POWER.
  - GEARBOX: asked only when the remaining engine has several gearbox kinds;
  - DRIVE: asked only when several drives remain.

  A level is skipped when every remaining version agrees on it. That level is settled from the list, which is not a guess: it is the only option that exists.
- **Rationale.** Fewest questions, with no level skipped by guessing (FR-002, FR-006, FR-007). A BEV has no displacement: the family is its range or battery label, and gearbox questions do not arise (the gearbox is single).

## R4. What the user said that does not exist

- **Decision.** `narrow()` filters by each stated level from the top down. A stated value that removes every version is recorded in `missing` and ignored for filtering. The next question is then asked at that level with what exists, and the text uses the `missing` template variant: "{car} {year} has no {missing}; there is: {options}". The FR-005 conflict between year and generation is handled by `reconcile()`: the newer statement wins, the other is dropped, and a note is shown.
- **Rationale.** This is SC-003 and US2.

## R5. The no-loop guarantee

- **Decision.**
  - Each ladder level has its own intake item (FUEL, ENGINE, POWER, GEARBOX, DRIVE) and attempt counter.
  - When the counter reaches the limit (2) and the level is still open, `decide()` settles it with the first option and records origin LIMIT, and the note is shown.
  - "Choose for me" sets `chosen_for_me`, so `decide()` descends to one version with origin CHOSEN.
  - Every ladder question offers its options + "choose for me" + "remove".
  - PROPOSE / REMOVE_OR_CHOOSE are never produced for a car on the ladder.
  - Property test: random version lists (1–30 versions, mixed fuels, gearboxes, drives, years) and random replies (option, choose, nonsense, remove), 1,000+ seeded scenarios.
    - Invariant 1: the number of candidate versions never grows on an option reply.
    - Invariant 2: every scenario ends DONE or REMOVED within Σ(levels × 2) asks.
    - Invariant 3: no question text repeats twice in a row for the same car and level.
- **Rationale.** This is FR-008…FR-012 and SC-004. The pure `decide()` makes the guarantee testable without the graph.

## R6. Corrections and the newer answer winning

- **Decision.**
  - `CaseCar.ladder` keeps a snapshot of the level values at the last identify, and the origin of the values the hub wrote (CHOSEN/LIMIT).
  - At the start of identify, `reconcile(snapshot, now)` finds the highest level whose value changed:
    - values the hub wrote at lower levels are cleared;
    - values the user stated are kept and re-validated by `narrow()`; if they no longer exist, they are reported as missing;
    - `chosen_for_me` is reset.
  - Year against generation: the newer one wins, and the older one is dropped with a note.
- **Rationale.** This is FR-005, FR-014 and US5, without a new store of history.

## R7. Fallback without a sourced list

- **Decision.**
  - When the lookup finds no supported version (or the store is absent), the existing path runs (catalog → resolver).
  - A catalog candidate taken without the user's words naming its power is PROPOSED (shown on the card), never AUTO_OK.
  - `ladder.certainty = "LESS_CERTAIN"` is set, and a notice says the identity is less certain.
  - The ENGINE question without a list asks in free form, with no invented options.
- **Rationale.** This is FR-020. The fallback keeps models with poor web coverage usable.

## R8. Used car age

- **Decision.**
  - A used car without a year is asked once (USED_AGE, together with the identity questions).
  - If no year comes after that ask (attempt ≥ 1 and the reply had none), `used.assumed_age(mileage, generation span, now)` gives the age: mileage/15,000 km, else the middle of the generation, else 5. The values come from config `intake.km_per_year_used` and `intake.default_used_age`.
  - It sets `year = now − age` and `year_assumed = True`, and the notice "assumed".
  - Compute keeps a safety net: a used car with no age gets the assumed age, never 0.
- **Rationale.** This is FR-021, FR-022 and SC-006.

## R9. Used purchase price, value now and warranty

- **Decision.**
  - `compose.load_car` loads the accepted `used_price_ranges` with their evidence.
  - `used.used_price_for(ranges, year)` returns the midpoint of the range whose model years cover the year (else the nearest range within 1 year, else None), with its URL.
  - Criteria `_price`: for a USED car it uses `used_price_eur` with the input "used price €X for YEAR (sourced)", else no data.
  - TCO depreciation for a used car: value now = used price when sourced, else new price × class share at its age (assumption); the value at the end = value now × share(age+years)/share(age).
  - Warranty: `used.warranty_status(first_year, years, now)` from the brand's sourced WARRANTY fact (`value_num` years) → "remaining until YEAR" or "expired in YEAR"; assumed when the year is assumed. It is shown as a notice and passed to the report facts.
- **Rationale.** This is FR-023…FR-027 and SC-006/007, reusing data the research areas already collect.

## R9b. Reliability for a used car

- **Decision.**
  - The age effect already exists and now always has an age.
  - A mileage effect is added: above `mileage_free_km` (60,000), `per_10k_over` (−1) points per 10,000 km, capped by `mileage_max` (−15). The values are in `config/criteria.yaml`, and the inputs list "mileage N km".
- **Rationale.** This is FR-025.

## R10. Architecture contract

- **Decision.**
  - `Version`, `Generation` and their JSON (de)serialisers live in `domain/ladder.py`.
  - `ModelVersionsRepo` imports only domain.
  - `application/versions.py` uses `ports.versions` (a `VersionsStore` Protocol).
  - No new `ignore_imports` lines: the WIP lines in `.importlinter` are dropped.
- **Rationale.** The architecture test limits the exceptions to 14.
