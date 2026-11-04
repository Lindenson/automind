# Implementation Plan: Reliable Car Identification Ladder and Used Cars Costed as Used

**Branch**: `008-identification-ladder` | **Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/008-identification-ladder/spec.md`

## Summary

Identification after make and model becomes one pure, deterministic **ladder** over a **sourced list of the versions** of the car's generation:
- the generation is taken from the year (used) or is the one on sale (new);
- then the engine (fuel → family/displacement → power, grouped only when there are more than 6 engines);
- then the gearbox;
- then the driven wheels.

Each step offers only versions that exist under the levels above. Something the user named that does not exist is reported, and the question moves one level up. "Choose for me" (and yes / go ahead / any) settles the current level and every level below by the base-version rule. After two asks, a level is settled by the same rule with a note, so no state can loop. The PROPOSE / REMOVE_OR_CHOOSE path stays only for make and model, and for the fallback when no source lists versions.

The version lists are a shared cache (`model_versions`, 60-day TTL) behind a new `VersionsStore` port:
- they are filled by one Spanish search and ≤ 3 pages read by the `versions` web reader (no tools);
- code keeps a version only when its power is written in its excerpt and the excerpt occurs in the document.

Used cars:
- a year that is never given is assumed (mileage → generation middle → 5 years) and labelled; age 0 is impossible;
- the purchase-price criterion uses the sourced used price for the car's year, or "no data";
- depreciation starts from the used price (value now);
- reliability adds age and mileage effects;
- the warranty is shown as remaining or expired from the brand's sourced terms;
- NCAP comparability is already per protocol period.

Reuses the draft from branch `008-wip-version-ladder` (`domain/ladder.py`, `application/versions.py`, `ModelVersions`, `assumed_age`), reworked to pass the architecture contract.

## Technical Context

**Language/Version**: Python 3.12 (backend); TypeScript/React (frontend, unchanged except chips text)

**Primary Dependencies**: FastAPI, LangGraph, SQLAlchemy/asyncpg, Alembic, Pydantic; LLM through the model gateway (`ports.llm.structured`)

**Storage**: PostgreSQL. A new table `model_versions` (migration 0013) and new CaseCar fields in the case JSON (backward compatible defaults).

**Testing**: pytest (unit, integration with `automind_test`, graph tests with fake LLM/search, golden dialogues), import-linter, `scripts/check.sh`. Hypothesis-style property tests are written with a seeded random generator (no new dependency).

**Target Platform**: Linux server (Docker Compose dev and deploy)

**Project Type**: web service + SPA (backend changes; frontend renders the existing question/chip contract)

**Performance Goals**:
- one version lookup per model generation and market, shared by all chats;
- ≤ 1 search, ≤ 3 pages and 1 LLM call per lookup;
- identification with a cached list is code only.

**Constraints**:
- the per-turn hard cap is unchanged; lookup calls are counted as identification (`identify_search_calls`), not research;
- robots and the deny-list are respected through the page store;
- no LLM produces numbers that code computes.

**Scale/Scope**: about 20 models in daily use; lists of ≤ 40 versions per generation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How the plan complies |
|---|---|
| I Evidence first | Every version keeps its source URL and excerpt. Its power must be written in the excerpt, and the excerpt must occur in the document. Without a sourced used price, the purchase-price criterion says "no data" and never uses the new price. |
| II Exact identity | Levels are settled from the user's words or asked. Options come only from the generation fixed by the year or by "on sale". A single catalog row never settles a level the user did not determine. The fallback marks the identity as less certain. |
| III Deterministic computation | The ladder, the assumed age, the used price choice, the warranty status and the reliability age/mileage effects are pure functions. The LLM only extracts the version list from documents. |
| IV Provenance classes | An assumed age, the class-curve value and the warranty under an assumed year are labelled "assumption". The used price is a "sourced fact". |
| V Layers | `domain/ladder.py` and `domain/used.py` are pure. `application/versions.py` goes through ports only. The repository depends on domain types only (no new import-linter exceptions; the architecture test stays ≤ 14). |
| VI Bounded orchestration | Asks are bounded per level (2). Lookups are bounded (pages, TTL cache-first, per-turn cap). The identity is confirmed on the card before paid research. |
| VII Provider independence | The new role `versions` is configured in `models.yaml` and called through the gateway. |
| VIII Untrusted content | `versions` is a web reader: no tools, untrusted documents wrapped, structured output only, deny-list honoured. |
| IX Test-first core | Unit tests cover the ladder, reconcile, assumed age, used price and warranty. Property tests cover the no-loop guarantee. Graph tests use a fake versions store. |
| X YAGNI | One table and one port. No queue, no new service. Trims are out of scope. |
| XI Quality gates | A lookup with no supported version stores nothing; it falls back and the identity is marked less certain. |

**Result**: PASS, no violations. The re-check after design is also PASS (see the end of the document).

## Project Structure

### Documentation (this feature)

```text
specs/008-identification-ladder/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/identification-protocol.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/0013_model_versions.py           # new table
├── config/
│   ├── models.yaml                                    # role versions
│   ├── questions.yaml                                 # ENGINE/FUEL/POWER/GEARBOX/DRIVE texts, "missing", status words
│   ├── search.yaml                                    # intake: versions_ttl_days, versions_max_pages, ask limit, km/year
│   └── criteria.yaml                                  # reliability mileage effect
├── src/automind/
│   ├── domain/
│   │   ├── ladder.py          # Version, Generation, Wanted, narrow, next_step, decide, apply_option, status, reconcile
│   │   ├── used.py            # assumed_year/age, used_price_for, warranty_status
│   │   ├── casefile.py        # Choice: level/fuel/power_kw/engine_cc/gearbox/drive; CaseCar: ladder memo, year_assumed
│   │   ├── intake.py          # pick: structured options; ladder items; no PROPOSE/REMOVE for ladder levels
│   │   ├── criteria.py        # used price criterion, reliability mileage
│   │   └── tco.py             # depreciation from the used price
│   ├── application/
│   │   ├── ports.py           # VersionsStore protocol, Ports.versions
│   │   ├── versions.py        # lookup (cache-first, search, read, extract, validate)
│   │   ├── identify.py        # ladder path; fallback; assumed year; reconcile
│   │   ├── ask.py             # status line, missing variant, choose chip on every ladder question
│   │   └── compose.py         # used prices loaded; used facts for criteria/TCO; warranty
│   ├── infrastructure/db/{models.py,repositories.py}  # ModelVersions, ModelVersionsRepo
│   ├── infrastructure/live_ports.py                   # versions=ModelVersionsRepo()
│   └── orchestration/
│       ├── nodes/compute.py   # age never 0 for used, used notices, warranty notice
│       ├── prompts/versions.md
│       └── phrases.py         # used_age_assumed, warranty_*, identity_less_certain, level replaced
└── tests/
    ├── unit/test_version_ladder.py, test_ladder_property.py, test_used_costs.py, test_incident_9b5c0b0c.py
    ├── integration/test_model_versions_repo.py
    └── golden/ (runner subtracts identify_search_calls)
```

**Structure Decision**: the existing layered modular monolith. The new pure logic goes in `domain/ladder.py` and `domain/used.py`, I/O in `application/versions.py`, and persistence behind a port.

## Complexity Tracking

No constitution violations. Two older paths are kept on purpose:
- PROPOSE / REMOVE_OR_CHOOSE stays for the make/model level and for the no-list fallback;
- the resolver stays as the fallback.

Removing them would leave models without any sourced list unidentifiable.

## Post-design Constitution re-check

PASS. The data model adds no unsourced fact: every version has a URL and an excerpt, and an assumed age is labelled. The contracts keep the question/chip protocol of spec 005 and add fields. The frontend does not change its logic.
