# Implementation Plan: Electrified Cars and Chinese Brands — Correct Data, Honest Running Costs

**Branch**: `006-energy-model` (the old `006-electrified-cars` branch held the spec only and is merged) | **Date**: 2026-11-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-electrified-cars/spec.md`

## Summary

Every car gets an honest energy cost, whatever its powertrain. The fuel bill in `domain/tco.py` becomes a pure **energy model** (`domain/energy.py`) with one function per powertrain:

- **ICE / MHEV / HEV**: unchanged (real-world figure, else WLTP × allowance, else NEDC × allowance).
- **PHEV / EREV**: electric km and fuel km from an **electric share**. The share comes from:
  - the daily distance, or km per year spread over driving days;
  - the real electric range;
  - home or work charging;
  - a documented charging-habit assumption.

  The electric km are priced from the charge-depleting kWh/100 km. The fuel km are priced from the charge-sustaining (empty-battery) l/100 km. The weighted WLTP figure is stored as its own attribute and never priced.
- **BEV**: kWh/100 km. A sourced real-world figure is used where one exists; otherwise WLTP × allowance. Charging losses are added once, and only to figures measured at the battery. EU WLTP figures are measured at the plug, so they already include them. The kWh are priced at the user's home/public mix.

Everything the model uses is a sourced attribute or a labelled, dated assumption from config:

- **New EV attributes** (generic claim/spec storage, no migration). Sense rules cover:
  - kWh vs kW;
  - gross vs usable;
  - weighted vs charge-sustaining;
  - impossible range;
  - charging power and time bounds.
- **Spanish energy prices**: `config/energy.yaml`, with `as_of` dates and source URLs. User overrides in the chat.
- **Charging situation**: a profile field with basis and evidence. The value-of-information asker from 007 asks it at most once, only when it flips the result.
- **Climate and motorway factors**: from the region's climate zone (005) and usage.

On top of the numbers:

- **Fairness**:
  - efficiency is scored on one scale, € per 100 km;
  - running cost never decides a verdict when one car lacks an energy line;
  - the break-even is computed by code.
- **Facts with dates**:
  - the environmental label (DGT rule, derived from the powertrain, electric range and Euro standard);
  - incentives as market-level facts (new table `market_facts`, area `incentives`, once per market per 30 days);
  - brand warranty and the Spanish dealer network (area `manufacturer`, new attributes; counts never estimated);
  - residual value marked "insufficient data" for new brands and electrified cars without a sourced figure.
- **Report**: a new `electric` block, the energy split in the `tco` block, and explainers, in ru/es/en.

Increments, one PR each:

| Inc. | Content | Stories / FR |
|------|---------|--------------|
| **A** | `domain/energy.py` per powertrain; EV attributes; PHEV consumption meaning (weighted / CS / CD); EV sense rules; regression set; TCO uses the energy model; "cannot be computed" with named inputs | US1, US2 · FR-001–009, FR-022 (rejections) |
| **B** | `config/energy.yaml` Spanish prices with dates and sources; overrides (`set_rates` extended); `home_charging` profile field; value-of-information question; home/public mix | US3 · FR-010–012 |
| **C** | climate and motorway factors with a sourced-real-world bypass | US4 · FR-013 |
| **D** | efficiency on €/100 km; verdict fairness; break-even; environmental label; `market_facts` + area `incentives` | US5 · FR-014–016, FR-023 |
| **E** | brand warranty and network attributes and queries; residual "insufficient data" | US6 · FR-017–018 |
| **F** | `electric` block, TCO energy split, explainers, ru/es/en, frontend | US7 · FR-019–021 |
| **G** | goldens g8–g12, metrics FR-022, live check of the incident pair (paid; estimate first) | SC-001–007 |

A is the MVP: it alone fixes the incident (the BYD gets an energy line or an honest "cannot be computed"). B makes it Spanish and personal. Details: [research.md](./research.md) R1–R13.

## Technical Context

**Language/Version**: Python 3.13 (backend), TypeScript 5.6 (frontend). Unchanged.

**Primary Dependencies**: unchanged. No new libraries.

**Storage**: Docker Postgres 16.
- New EV attributes live in the existing generic `claims` / `spec_values` rows (attribute String(40)); no migration.
- Migration `0011_market_facts` adds table `market_facts`: id, market, key, value JSON, valid_from, valid_to, status, evidence_ids, fetched_at; unique (market, key).
- Case file JSON (validators upgrade old rows on read):
  - `profile.home_charging` and its basis/evidence;
  - `rates` gains `home_electricity_eur_per_kwh`, `public_ac_eur_per_kwh` and `public_dc_eur_per_kwh`. The old `electricity_eur_per_kwh` override maps to home.

**Testing**:
- Unit tests, written first:
  - `energy.estimate` per powertrain, with the incident BYD/Ateca numbers;
  - the electric share (daily km known/unknown, home yes/no, range above/below daily);
  - losses added once;
  - climate and motorway factors and the bypass;
  - break-even, including "never";
  - the environmental label;
  - EV sense rules: a regression table of about 40 cases (SC-003);
  - PHEV consumption classification;
  - incentive status from dates;
  - efficiency €/100 km scoring;
  - `ask_value` for home_charging (asks only when the winner flips).
- Graph tests with fakes:
  - a PHEV with only a weighted figure: deeper research job → "cannot be computed";
  - home-charging question asked once.
- Goldens g8–g12 (fake model + recorded search), see quickstart.md.
- vitest: the `electric` block and the TCO energy split render; Zod schemas.

**Target Platform / Project Type**: unchanged (web application, backend + SPA).

**Performance Goals**: no extra LLM calls for the energy model (pure code).
- The EV attributes come from the same `specs` / `measured` jobs with EV query templates. That adds at most one extra search per EV car per area.
- Incentives are researched once per market per 30 days, shared across chats.

**Constraints**:
- Never scrape classifieds; respect robots.txt.
- Every price and factor is a dated, labelled assumption or a sourced fact.
- Ruff C901 ≤ 10.
- The import-linter keeps the domain pure.

**Scale/Scope**:
- about 16 new attributes and about 25 sense rules;
- 2 config files;
- 1 table, 1 research area;
- 1 new block type;
- 5 goldens.

## Constitution Check

*GATE: checked before Phase 0 and again after Phase 1.*

| Principle | How the plan complies |
|-----------|-----------------------|
| I. Evidence first | Every EV value comes from a claim with evidence. Prices and factors are configured assumptions with `as_of` and source URLs, labelled ASSUMPTION in every input line. Dealer counts and incentives are only shown when sourced; otherwise "not found". The weighted WLTP figure is never priced. |
| II. Exact identity | Attributes attach to the variant; a PHEV and an HEV of one model are different variants (005 identity already carries the powertrain). |
| III. Deterministic computation | Energy, share, factors, break-even, label and efficiency are pure functions in `domain/`, with tests. The LLM only extracts claims. |
| IV. Provenance classes | Each energy input carries SOURCED / MEASURED / DERIVED / ASSUMPTION / USER. A CD kWh figure derived from usable kWh ÷ WLTP range is labelled DERIVED. |
| V. Layered monolith | `domain/energy.py`, `domain/incentives.py` and `domain/sense_ev.py` stay pure. `application/compose.py` assembles the inputs. The infrastructure adds the table. Contracts stay checked by the import-linter. |
| VI. Bounded orchestration | The home-charging question goes through the existing ask_value budget (1 question). Deeper research for missing EV inputs uses the existing round limits and the "continue?" pause. |
| VII. Provider independence | No provider-specific code. |
| VIII. Untrusted content | New queries go through the existing fetcher (robots.txt, deny-list, SSRF guard). No new hosts are hard-coded beyond favourites in `sources.yaml`. |
| IX. Test-first | Regression tables are written before the rules. The goldens are recorded. |
| X. Simplicity | No new providers. Generic attribute storage is reused. One table, only because incentives are market-level, not per variant. |
| XI. Research depth | Minimum per EV area: range + consumption (+ CS for PHEV). An unmet minimum triggers a deeper round before "cannot be computed". |

**Result**: PASS. No violations to justify. Post-design re-check: PASS. The data model adds no per-chat state beyond the profile field and the rate overrides.

## Project Structure

### Documentation (this feature)

```text
specs/006-electrified-cars/
├── plan.md              # this file
├── research.md          # R1–R13 decisions
├── data-model.md        # attributes, energy estimate, prices, market facts
├── quickstart.md        # validation scenarios and goldens
├── contracts/
│   ├── blocks-electric-and-tco.md   # report blocks (WS assistant_message)
│   └── case-profile-and-rates.md    # profile.home_charging, rates overrides
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── config/
│   ├── energy.yaml            # NEW: Spanish prices (dated, sourced), habits, losses, climate/motorway factors
│   ├── incentives.yaml        # NEW: DGT label rules (source URL) + incentive keys to research
│   ├── rates.yaml             # real_world_factor.PHEV removed; electricity moves to energy.yaml
│   ├── sense.yaml             # EV markers (weighted / CS / gross / usable / kW / kWh)
│   ├── queries.yaml           # EV templates for specs/measured; manufacturer warranty/network; incentives
│   ├── criteria.yaml          # efficiency scale in €/100 km
│   ├── makes.yaml             # new_in_market flag (BYD, MG, Omoda, Jaecoo, Leapmotor, Xpeng, Zeekr…)
│   └── tech_explainers.yaml   # 5 new explainers (ru/es/en)
├── alembic/versions/0011_market_facts.py
└── src/automind/
    ├── domain/
    │   ├── energy.py          # NEW: estimate(car, prices, situation, usage) → EnergyEstimate
    │   ├── sense_ev.py        # NEW: EV meaning rules (kept out of sense.py for C901/size)
    │   ├── incentives.py      # NEW: env label, incentive status, break-even
    │   ├── specs.py           # new Attr entries
    │   ├── tco.py             # ENERGY item from EnergyEstimate; depreciation "insufficient data"
    │   ├── criteria.py        # efficiency on €/100 km
    │   ├── research_plan.py   # area "incentives" (market level); EV minimums
    │   ├── ask_value.py       # home_charging candidates
    │   └── casefile.py        # profile.home_charging, Rates fields
    ├── application/
    │   ├── compose.py         # assemble EV inputs, electric block, market facts
    │   ├── research.py        # route PHEV consumption by meaning; EV sense hook
    │   └── interpret.py       # extract home charging words and user prices
    ├── orchestration/nodes/compute.py, report_text.py, phrases.py
    └── infrastructure/db/models.py, repositories.py   # MarketFact
frontend/src/
├── lib/protocol.ts            # electric block schema; tco energy split
├── components/blocks/Electric.tsx (NEW), Tco.tsx
└── i18n/{ru,es,en}.ts
```

**Structure Decision**: the existing layered monolith. The new pure modules sit next to `tco.py` and `sense.py` so the functions stay below the complexity limit.

## Complexity Tracking

No constitution violations. One deliberate addition: the `market_facts` table. Incentives and the DGT programme status belong to the market, not to a variant. Storing them per variant would repeat them for every car and let copies disagree.
