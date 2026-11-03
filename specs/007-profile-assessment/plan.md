# Implementation Plan: The User's Profile Drives the Assessment

**Branch**: `007-profile-assessment` | **Date**: 2026-11-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-profile-assessment/spec.md`

## Summary

The profile stops being decoration. Four mechanisms carry it, in the order they ship.

1. **Search recall (US5): first increment, its own PR.** It changes no profile code.
   - Favourite queries use a short identity: make, model, and a variant key such as "320d" or "R 333", with no generation code and no repeated words.
   - Area words follow the market's language, from per-market templates for ES, DE and EN.
   - A zero-hit favourite query is retried once in a shorter form.
   - Empty search results are cached for 6 hours.
   - Domains with accepted values are remembered in a new `learned_sources` table and join round 0 after the configured favourites.
2. **Profile model (US1).**
   - Every profile field carries a basis: STATED, INFERRED or ASSUMED, with the user's words where they exist.
   - New fields: ownership years, new or used (from `budget.intent` plus car condition), and a monthly limit (the existing running-cost limit).
   - The interpreter may infer from the whole dialogue, with evidence.
   - Questions are asked by value: a pure function scores the case with 2–3 plausible values of a field and asks only when the winner or the tie changes.
3. **Weights (US2).** `weights_for` becomes `weight_breakdown()`. It is a pure function: persona base + `profile_rules.yaml` + priorities + manual adjustments, then a cap and normalisation to 100. Every contribution carries a reason code. `weights_overridden` is replaced by `weight_adjustments`; old cases migrate in JSON on read.
4. **RESCORE and per-profile verdict (US3, US4).**
   - The fingerprint splits into a data part and a parameters part. Policy gets a new action, RESCORE.
   - A panel PATCH immediately starts a preset turn `{kind: "rescore"}`. It skips interpret and research and runs compute → report_rescore, which writes a short "what changed" text over the facts.
   - The TCO horizon comes from `ownership_years`.
   - Over budget and over the monthly limit become verdict findings.
   - The insights gain a persona counterfactual: same data, other persona.

After these come:
- the intake fixes (US6);
- the validation gaps (FR-030 to FR-034, all small and pure);
- graph robustness (FR-027 to FR-029);
- last, candidate selection without named cars (US7).

Details: [research.md](./research.md) R1–R12.

## Technical Context

**Language/Version**: Python 3.13 (backend), TypeScript 5.6 (frontend). Unchanged.

**Primary Dependencies**: unchanged (FastAPI, LangGraph, LangChain gateway, SQLAlchemy, Alembic, React, Zustand, Zod). No new libraries.

**Storage**: Docker Postgres 16. Migration `0010_learned_sources` adds:
- table `learned_sources`: domain, area, market, source_type, accepted_runs, misses, first_seen, last_seen, unique (domain, area, market);
- column `search_cache.empty bool` (whether the empty-result TTL applies).

Case file JSON changes (no migration; `CaseFile` validators upgrade old rows on read):
- `profile.basis`;
- `ownership_years`;
- `weight_adjustments`;
- `fingerprint_data`, `fingerprint_params`.

**Testing**:
- Unit tests (pure, written first):
  - `search_plan.short_identity` and query rendering, with chat 757cff3d identities;
  - `learned.update` (promotion and expiry);
  - `weights.breakdown` (one test per rule plus caps);
  - `ask_value.questions` (asks only when the winner flips);
  - `policy` RESCORE selection;
  - `fingerprint` split;
  - TCO horizon;
  - budget findings;
  - counterfactual insight;
  - number reading ("20к", "тыщ", "млн", "Golf 7 2015");
  - FR-030 to FR-034 regressions with the review's examples.
- Graph tests with fakes:
  - PATCH → rescore turn: zero search and interpret calls, new verdict;
  - confirmation-card persona change → research plan areas;
  - intake: an offered option is accepted.
- Goldens G31–G36 (fake model + recorded search), listed in quickstart.md.
- vitest:
  - profile editor;
  - weight reasons and manual badge;
  - changed-score highlight.

**Target Platform**: unchanged.

**Project Type**: web application (backend + SPA), one repository.

**Performance Goals**:
- RESCORE: under 2 s end to end; 0 web searches, 0 interpreter calls, at most 1 reporter call (SC-004).
- Question-by-value: at most 3 × 3 extra scorings per turn, pure and under 50 ms.
- Learned-source update: one SQL upsert per research run.

**Constraints**:
- At most 1 profile question before the first research.
- A learned source is never MANUFACTURER unless it is official by the existing rules.
- Deny-listed sites are never learned.
- Classifieds are never read.
- One turn per chat: a PATCH during a running turn still returns 409, and the UI keeps the edit and sends it when the turn ends.

**Scale/Scope**:
- 13 criteria;
- about 25 profile rules;
- 4 personas;
- 1–3 cars per chat;
- single-user LAN deployment.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | How 007 complies | Status |
|---|---|---|
| I. Evidence first | Profile defaults are labelled ASSUMED and never shown as facts. Learned sources are only a search hint; values from them pass the same excerpt and sense checks. | PASS |
| II. Exact identity | The short query identity is only for searching. The relevance gate and the validator still check the full variant. An offered option resolves to its exact variant id. | PASS |
| III. Deterministic | Weights, questions-by-value, RESCORE, TCO horizon, budget findings and counterfactuals are pure code. The model only infers profile fields (with evidence) and writes text over facts. | PASS |
| IV. Provenance | Profile fields carry STATED, INFERRED or ASSUMED; weights carry reasons. | PASS |
| V. Layering | `domain/weights.py`, `domain/ask_value.py`, `domain/learned.py` and the `search_plan` changes are pure. `application/learned_sources.py` and `application/rescore.py` do the I/O. Nodes delegate. The frozen import-linter ignore count (14) must not grow. | PASS |
| VI. Bounded, human-steered | RESCORE does no research. New-data needs ("used") are offered, not started. The empty-result retry is bounded to 1 per query. Hop counter (FR-027). | PASS |
| VII. Provider independence | No new role. The rescore text uses the existing reporter role through the gateway. | PASS |
| VIII. Untrusted content | No new fetch path. A learned domain is still checked against the deny-list and robots on every fetch. | PASS |
| IX. Test-first | Pure modules first. Graph tests with fakes. Goldens. | PASS |
| X. Simplicity | One table, one YAML file, one policy action. No queue and no new service. | PASS |
| XI. Quality gates | Area minimums are unchanged. Learned sources need ≥3 accepted runs before they are used. | PASS |

Post-design re-check: PASS (no violations, so Complexity Tracking is empty).

## Turn graph (changes)

```text
PATCH /case ──► save version ──► runner.run_turn(preset={kind:"rescore", changes}) (NEW, immediate)

START → load_case → understand (preset rescore → skip interpret) → apply_delta → identify → assess → policy
policy (rules, in order):
  0   hops ≥ max_hops → ANSWER_FROM_CONTEXT(partial)                                  (NEW, FR-027)
  1   no cars + class/need + budget → SELECT_CANDIDATES (US7, last increment)          (NEW)
  1b  no cars otherwise → general
  2   intake step: ASK (≤1 profile question, by value)                                 (CHANGED)
  3   CONFIRM_INTAKE (card edits profile + weights; applied before research)          (CHANGED)
  4   data part changed or stale → RESEARCH (plan areas from persona)
  5   only params part changed, data fresh → RESCORE                                   (NEW)
  6   neither → nothing new / answer / report
RESCORE → compute (weights breakdown, TCO over ownership_years, budget findings, counterfactual)
        → report_rescore (one LLM call over facts: "what changed") → done
```

## Project Structure

### Documentation (this feature)

```text
specs/007-profile-assessment/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R12
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── case-patch-and-rescore.md
│   └── learned-sources.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks (not yet)
```

### Source Code (repository root)

```text
backend/
├── config/
│   ├── queries.yaml              # short favourite templates {make} {model} {key}; ES/DE/EN area words
│   ├── search.yaml               # empty_result_ttl_hours: 6; learned: {min_runs: 3, max_misses: 5, per_area: 4}
│   │                             # intake.full_intake: false; graph.max_hops
│   ├── profile_rules.yaml        # NEW: field → value → {criterion: points, reason}
│   ├── profile_defaults.yaml     # NEW: per persona: ownership_years, annual_km, condition
│   └── rates.yaml                # horizon_years stays the fallback
├── alembic/versions/0010_learned_sources.py
├── src/automind/
│   ├── domain/
│   │   ├── search_plan.py        # short_identity(), variant_key(), shorter() fallback form
│   │   ├── learned.py            # NEW: promote/expire rules (pure)
│   │   ├── weights.py            # NEW: breakdown(case, model, rules) → WeightBreakdown
│   │   ├── criteria.py           # weights_for → weights.breakdown(...).final
│   │   ├── ask_value.py          # NEW: which profile question changes the answer
│   │   ├── casefile.py           # ProfileBasis, ownership_years, weight_adjustments, upgrade of old rows
│   │   ├── policy.py             # RESCORE, split fingerprint, hops, SELECT_CANDIDATES
│   │   ├── tco.py                # horizon from the case
│   │   ├── verdict.py / insights # budget findings, persona counterfactual
│   │   └── evidence.py           # FR-030..032 (gap limit, number boundaries, text agreement)
│   ├── application/
│   │   ├── interpret.py          # numbers_in (FR-004), history window from config
│   │   ├── research.py           # learned sources into round 0; record accepted domains
│   │   ├── learned_sources.py    # NEW: load / update learned_sources (I/O)
│   │   ├── rescore.py            # NEW: patch → changes summary for the preset turn
│   │   ├── resolve.py / identify.py  # FR-024, FR-025
│   │   └── candidates.py         # NEW (US7): profile + budget → 2–3 candidates via lineup
│   ├── infrastructure/
│   │   ├── search/cache.py       # empty results: short TTL
│   │   └── db/models.py, repositories.py  # LearnedSource
│   ├── orchestration/
│   │   ├── nodes/understand.py   # preset rescore; profile inference merge; stable stated fields
│   │   ├── nodes/compute.py      # breakdown, horizon, findings
│   │   ├── nodes/report.py       # report_rescore ("what changed")
│   │   ├── guard.py              # FR-033 (small ints/years only from facts), FR-034 word boundaries
│   │   ├── runner.py             # hops, partial result on timeout (FR-029)
│   │   ├── graph.py              # RetryPolicy on LLM nodes (FR-028); RESCORE edge
│   │   └── prompts/interpreter.md  # infer profile from dialogue with evidence (FR-002)
│   └── api/rest.py               # CasePatch: profile fields, ownership_years, weights reset; triggers rescore
└── tests/ (unit/domain, unit/application, graph, golden)

frontend/src/
├── components/CasePanel/CasePanel.tsx   # AboutYou → editable ProfileEditor (chips per field + basis badge)
├── components/CasePanel/Weights.tsx     # reasons per weight, "set manually" badge, "back to automatic"
├── components/blocks/CriteriaScores.tsx # highlight changed scores (delta from previous report)
├── components/IntakeCard*               # profile chips: persona, years, new/used, km, budget
├── lib/protocol.ts                      # CasePatch v2, weight_breakdown, profile.basis
└── store/case.ts                        # queue a patch while a turn runs
```

**Structure Decision**: same layout as 005. New pure modules sit in `domain/` and new I/O sits in `application/`. The graph gains one action and one report node; no new subgraph is introduced in this spec.

## Increments (each one PR, merged to main)

| # | Scope | FR | Ships when |
|---|---|---|---|
| A | Search recall + learned sources | FR-020 to FR-023 | Chat 757cff3d replay (recorded search) finds round-0 pages; unit tests pass |
| B | Profile model, inference, numbers, questions by value, `full_intake: false` | FR-001 to FR-007 | G31, G32 pass |
| C | Weight breakdown + profile rules + manual adjustments + UI reasons | FR-008 to FR-011 | Rule tests; vitest |
| D | Split fingerprint + RESCORE + PATCH trigger + panel editor + card edits before research | FR-012 to FR-015 | Graph test: 0 searches, under 2 s |
| E | TCO horizon, budget findings, counterfactual, persona-led text | FR-016 to FR-019 | Three-profile test (SC-005) |
| F | Intake fixes | FR-024, FR-025 | 757cff3d intake replay |
| G | Validation gaps | FR-030 to FR-034 | Regression set |
| H | Graph robustness | FR-027 to FR-029 | Graph tests for hops, retry, timeout |
| I | Candidate selection without cars | FR-026 | G36 |

## Complexity Tracking

None.
