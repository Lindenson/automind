# Implementation Plan: Understanding the User — Intake and Identification

**Branch**: `005-user-intake-identification` | **Date**: 2026-11-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-user-intake-identification/spec.md`

## Summary

The intake becomes a bounded loop run by code. Every reply is turned into identity facts and profile facts. Each car is identified again from those facts in the same turn. The next step is either a concrete question (never the same one twice), a proposal, or one confirmation card. Research starts only after "yes" on the card.

Five changes carry it:
1. **Identify on every turn.** A new `identify` node runs the identification pipeline for every unsettled or changed car. `UNKNOWN_MODEL` is no longer sticky.
2. **Open world.** A make registry in config, plus brand line-ups looked up on the web with sources and cached. "Unknown" is said only after that lookup. Transliteration and fuzzy matching are deterministic.
3. **Engine identity and corrections.** `engine_hint` is added and variants store cc, kW and fuel. Any identity change clears the resolved variant and is shown as "before → after".
4. **Intake state.** Attempts are counted per item. A repeated item gets a rephrased question with options, and after two attempts the assistant proposes the most likely car. Generic chat is unreachable while an intake step is pending. Question templates are localized.
5. **Confirmation card.** One card with cars, profile and cost. Each item is marked stated, inferred, looked up or assumed, and can be edited with chips. One "yes" confirms the variants and approves the cost.

Details: [research.md](./research.md) R0–R14.

## Technical Context

**Language/Version**: Python 3.13 (backend), TypeScript 5.6 (frontend). Unchanged.

**Primary Dependencies**: unchanged (FastAPI, LangGraph, LangChain gateway with Gemini/OpenAI, SQLAlchemy, Alembic, rapidfuzz, React, Zustand, Zod). No new libraries.

**Storage**: Docker Postgres 16. Migration `0008_intake`:
- new table `brand_lineups` (make, market, models JSON with excerpts, sources, fetched_at);
- new table `intake_events` (chat-scoped, ON DELETE CASCADE);
- `vehicle_variants` gains `engine_cc`, `power_kw` and `fuel` (back-filled from `variant_name`);
- the case file JSON gains `intake`, `engine_hint`, `previous_label`, and profile `region`, `climate`, `annual_km_min` and `annual_km_max`. JSON only, no migration needed.

**Testing**:
- Unit tests (pure): `domain/intake` (next step, attempts, identity key, progress, rank_lineup, parse_distance), `identity.parse_engine`, `identity.transliterate_ru`, the make registry, localized templates and the language guard.
- Graph tests with fake model and search:
  - the incident replay;
  - a correction clears the variant;
  - general chat is not reachable while a question is pending;
  - card edit then confirm leads to research.
- Golden replay G21–G30.
- vitest: IntakeCard (chips, highlighting, confirm).

**Target Platform**: unchanged (Linux, Docker, desktop and phone browsers).

**Project Type**: web application (backend + SPA), one repository.

**Performance Goals**:
- Confirmation card within 60 s of the first message when no question is needed (SC-008).
- A line-up lookup costs at most 1 search plus 2 page reads plus 1 model call. Cached line-ups cost 0 calls.
- Every intake reply within 15 s.

**Constraints**:
- At most 3 questions per message.
- Attempts are bounded: 2 per item, then a proposal; 4 per car, then remove or choose.
- Classifieds are never read, also from user links.
- robots.txt is respected.
- Limits ask "continue?" instead of cancelling.
- No English text in a ru/es conversation.

**Scale/Scope**:
- About 60 makes in the registry.
- Line-ups of up to about 30 models per make.
- 1–3 cars per chat.
- Single-user LAN deployment (accounts are roadmap step 5).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | How 005 complies | Status |
|---|---|---|
| I. Evidence first | Brand line-ups and prices are stored with URL, excerpt and date. A model must occur in its document. No model memory is used as a fact. Suggestions are labelled as suggestions. | PASS |
| II. Exact identity | The engine (cc, kW, fuel) becomes part of the identity. Corrections invalidate the old variant. Ambiguity leads to options or a proposal, never a silent choice. | PASS |
| III. Deterministic | Next step, attempts, progress, engine and distance parsing, transliteration and line-up ranking are pure code. The model only parses free text and phrases the acknowledgement. | PASS |
| IV. Provenance | Card items carry a basis: STATED, INFERRED (evidence), LOOKED_UP (source) or ASSUMED. | PASS |
| V. Layering | `domain/intake.py` and the `identity.py` additions are pure. `application/lineup.py` and `application/identify.py` hold the I/O. The new node only delegates. import-linter contracts are unchanged. | PASS |
| VI. Bounded, human-steered | Attempts are bounded in config. Research starts only after the card's "yes". One "yes" covers the variants and the cost below the hard cap, which is still never exceeded. | PASS |
| VII. Provider independence | The new `lineup` role goes through the gateway and is configured in `models.yaml`. | PASS |
| VIII. Untrusted content | User URLs go through the same page store (robots, deny-list, size and time limits) inside `<untrusted_document>`. The `lineup` role has no tools. | PASS |
| IX. Test-first | Pure modules are tested first. The graph is tested with fakes. Goldens are replayed. | PASS |
| X. Simplicity | No new infrastructure. The line-up is a table plus one role. The registry is a YAML file. | PASS |
| XI. Quality gates | The line-up minimum is 1 official or price-list source per make. "Unknown" is said only after the lookup ran. | PASS |

Post-design re-check: PASS (no violations, so Complexity Tracking is empty).

## Turn graph (changes)

```text
START → load_case → interpret → apply_delta ──► identify (NEW) ──► assess → policy
                                    │              per unsettled / changed car:
                                    │              registry → line-up → catalog → resolver → engine match
                                    │              → IDENTIFIED | CHOICES | NEED | NOT_FOUND
policy (rules, in order):
  0  pending intake + general/chitchat → treated as an intake answer (never `general`)      (NEW)
  1  general question, no pending intake → general
  2  intake step (domain/intake.next_step): ASK (≤3, localized, never repeated) | PROPOSE   (CHANGED)
  3  all cars IDENTIFIED, card not confirmed → CONFIRM_INTAKE (cars + profile + cost)        (NEW)
  4  research (no separate cost dialog after the card's "yes", hard cap kept)
  5/6 answer / report (unchanged)
CONFIRM_INTAKE → wait (interrupt) → apply_intake: yes → assess → RESEARCH | edit → card again | text → interpret
```

## Project Structure

### Documentation (this feature)

```text
specs/005-user-intake-identification/
├── spec.md
├── plan.md              # this file
├── research.md          # R0–R14
├── data-model.md
├── quickstart.md
├── contracts/
│   └── intake-protocol.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks (not yet)
```

### Source Code (repository root)

```text
backend/
├── config/
│   ├── makes.yaml               # NEW: makes sold in Spain, aliases, transliterations, official ES domains
│   ├── regions.yaml             # NEW: provinces / communities → climate zone
│   ├── questions.yaml           # v2: en/ru/es + rephrase variants, CONDITION, ENGINE, MAKE_LINEUP
│   ├── models.yaml              # + lineup role
│   └── search.yaml              # + intake limits (attempts, lineup TTL)
├── alembic/versions/0008_intake.py
├── src/automind/
│   ├── domain/
│   │   ├── intake.py            # NEW: identity_key, progress, next_step, attempts, rank_lineup, parse_distance
│   │   ├── identity.py          # + parse_engine, transliterate_ru, engine_fits
│   │   ├── casefile.py          # + Intake, EngineHint, previous_label, Profile.region/climate/km range
│   │   ├── policy.py            # rule 0, intake step, CONFIRM_INTAKE
│   │   ├── identification.py    # settled() uses the identify outcome; REASK replaced by attempts
│   │   └── metrics.py           # + intake metrics
│   ├── application/
│   │   ├── identify.py          # NEW: per-car pipeline → outcome
│   │   ├── lineup.py            # NEW: brand line-up lookup and cache
│   │   ├── makes.py             # NEW: registry load, match (aliases, transliteration, fuzzy)
│   │   ├── resolve.py           # _check_known uses the line-up; engine in _fits/_rank/upsert; display_name
│   │   ├── intake_card.py       # NEW: card build (basis per item), edit apply
│   │   ├── ask.py               # localized templates, concrete options, no fallbacks
│   │   └── interpret.py         # engine_hint + deterministic parse merge
│   ├── orchestration/
│   │   ├── nodes/identify.py    # NEW node (delegates to application/identify)
│   │   ├── nodes/confirm.py     # prepare/apply_intake; variants kept for old chats
│   │   ├── nodes/understand.py  # corrections clear variants; _not_understood → progress-based
│   │   ├── nodes/report.py      # general prompt: no greeting, no unnamed models
│   │   ├── graph.py             # identify node, CONFIRM_INTAKE edges
│   │   ├── phrases.py           # before → after, page-taken, proposal texts (en/ru/es)
│   │   └── prompts/             # interpreter v2 (engine_hint, region, km range, brand explanation),
│   │                            # lineup v1 (new), asker v2 (acknowledgement only), general v2
│   ├── api/ws.py                # intake_edit message
│   └── infrastructure/db/models.py, repositories.py   # BrandLineup, IntakeEvent
└── tests/
    ├── unit/test_intake.py, test_engine_parse.py, test_transliteration.py, test_makes.py, test_rank_lineup.py,
    │        test_questions_i18n.py
    ├── graph/test_identify_loop.py, test_corrections.py, test_intake_card.py, test_no_general_in_intake.py
    └── golden/g21_byd_seal_u_vs_ateca.yaml … g30_brand_explanation.yaml (+ cassettes)

frontend/src/
├── lib/protocol.ts              # IntakeCard confirm kind, intake_edit client message
├── components/IntakeCard.tsx    # NEW: cars + profile, basis badges, chips, highlight, confirm
├── components/ConfirmDialog.tsx # routes kind "intake" to IntakeCard
├── store/chat.ts                # editIntake()
└── i18n/{en,ru,es}.ts           # card labels
```

**Structure Decision**: the existing web application layout (`backend/` + `frontend/`). New pure logic goes in `domain/intake.py`. I/O pipelines go in `application/identify.py` and `application/lineup.py`. One new graph node delegates to them.

## Phases (for /speckit-tasks)

1. **Foundation**:
   - migration 0008;
   - `makes.yaml` and `regions.yaml`;
   - `EngineHint`, `Intake` and profile fields;
   - `parse_engine`, `transliterate_ru` and `parse_distance` with tests;
   - questions.yaml v2 with the i18n test.
2. **US1 + US3 (P1)**:
   - identify node and outcomes;
   - corrections clear variants, with "before → after";
   - progress-based answers and attempts;
   - propose after 2 attempts;
   - incident replay G21 and G23.
3. **US2 (P1)**:
   - registry match;
   - line-up lookup, cache and role;
   - `_check_known` on line-ups;
   - "find a model" with rank_lineup;
   - URL classification;
   - G22, G24, G25, G26 and G30.
4. **US4 (P2)**: region and climate, km range, CONDITION question for all cars, ≤3 grouped questions; G27 and G29.
5. **US5 (P2)**: CONFIRM_INTAKE card (backend build/edit/apply, protocol, IntakeCard UI); one "yes" covers variants and cost; G28.
6. **US6 (P2)**:
   - policy rule 0;
   - general prompt v2;
   - language guard;
   - suggestions labelled;
   - G30 assertions across all goldens.
7. **Polish**:
   - intake metrics;
   - ADR-024 (open-world identity) and ADR-025 (one confirmation card);
   - README;
   - deploy;
   - live run of G21–G30 on paid Gemini, announced with a cost estimate.

## Complexity Tracking

No constitution violations.
