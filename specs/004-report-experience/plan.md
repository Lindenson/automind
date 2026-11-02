# Implementation Plan: Report Experience

**Branch**: `004-report-experience` | **Date**: 2026-11-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-report-experience/spec.md`

## Summary

The report becomes a product of code first and words second. Building a report now goes in four steps:

1. **Sense-checked facts.** A new sense layer validates every value against the meaning of its attribute.
   Variants carry their gearbox and drive.
2. **Deterministic insights.** Code computes meaningful differences per attribute against thresholds and
   ranks them by the user's profile. It detects trade-offs (e.g. "pays back in N years at your km") and
   groups ties.
3. **A verdict built by code.** The pick or a tie, the reasons, the trade-off, a confidence level with its
   reason, and "what would change it".
4. **Writing and checking.** The reporter writes the headline and the explanation from the insights. The
   section depth follows the profile. A consistency check removes numbers that are not in the facts, false
   "no data" claims, wins below the threshold and winners in a tie.

New research areas bring sourced depreciation and value retention, the manufacturer's situation and
model-year changes. A small catalogue of technology explainers makes engineering differences concrete.

The UI gets:
- the verdict card first;
- collapsible sections ordered by a declarative per-profile layout;
- a comparison table without empty rows;
- one data panel with "find it";
- next-step suggestions, "this is wrong" on values and a rating control;
- a live car × area progress grid;
- the interface in ru/es/en and a phone layout.

The dialogue gets:
- profile inference with evidence;
- 1–3 questions only when they change the answer;
- critique that always leads to research or a reworked report.

Details: [research.md](./research.md) R1–R13.

## Technical Context

**Language/Version**: Python 3.13 (backend), TypeScript 5.6 (frontend). Unchanged.

**Primary Dependencies**: unchanged (FastAPI, LangGraph, LangChain + Gemini/OpenAI gateway, SQLAlchemy,
Alembic, React, Zustand, Zod, Tailwind). No i18n library: a small typed dictionary.

**Storage**: Docker Postgres 16 (003). New tables:
- `value_retention`;
- `report_ratings`;
- `value_challenges`.

New columns:
- `vehicle_variants.transmission` and `.drive`;
- the case profile gains fields with evidence.

`manufacturer_facts.kind` gains new values. Migration `0007_report_experience`.

**Testing**:
- Unit tests for pure modules: insights, verdict, sense, profile_gaps, layouts, report_check. The
  2026-11-02 defect regression set is included.
- Graph tests: critique leads to research or rework; challenge leads to a re-check; profile questions.
- Golden dialogues G12–G18 (replay and live).
- vitest: verdict card, data panel, suggestions, i18n, table.
- A layout check at 375 px.

**Target Platform**: unchanged (Linux, Docker, desktop and phone browsers).

**Project Type**: web application (backend + SPA), one repository.

**Performance Goals**:
- Verdict card within 30 s from cached data (SC-007).
- Progress events within 5 s.
- Insights and verdict computed in under 100 ms.

**Constraints**:
- Numbers only from code (constitution III).
- At most one regeneration of the text per report.
- At most 3 questions in one round.
- Cost per turn unchanged (limits ask, never cancel).

**Scale/Scope**: 1–3 cars per report. Three interface languages, four profile layouts.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.* Constitution v1.1.1.

| # | Principle | Design compliance | Pre | Post |
|---|---|---|---|---|
| I | Evidence first | Depreciation, manufacturer and model-year facts are sourced or labelled as estimates. Sense checks reject values that do not mean what their attribute means. | ✅ | ✅ |
| II | Exact identity | Variants carry gearbox and drive. Values of another gearbox or drive are rejected. Mixed variants are re-identified. | ✅ | ✅ |
| III | Deterministic computation | Insights, trade-offs, verdict, confidence, ties, layouts and suggestions are pure code. The model phrases and explains. The consistency check enforces this. | ✅ | ✅ |
| IV | Provenance classes | Unchanged; value retention and verdict reasons carry sources and bases. | ✅ | ✅ |
| V | Layered monolith | New pure modules live in `domain/` (insights, verdict, sense, profile_gaps). Layouts are config. UI uses protocol DTOs. | ✅ | ✅ |
| VI | Bounded, human-steered | Questions are bounded (≤ 3, one round). "Find it" and critique run research with the usual cost confirmation and limit questions. | ✅ | ✅ |
| VII | Provider independence | No change (gateway per role). | ✅ | ✅ |
| VIII | Untrusted content | New areas use the same web readers without tools. Explainers are config, not web text. | ✅ | ✅ |
| IX | Test-first core | The defect regression set and golden dialogues G12–G18 are written before the code. | ✅ | ✅ |
| X | YAGNI | No i18n framework. Layouts, thresholds and explainers are YAML. No new services. | ✅ | ✅ |
| XI | Quality gates | Section minimums kept. Verdict confidence depends on coverage and source agreement. | ✅ | ✅ |

No violations; Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/004-report-experience/
├── spec.md · plan.md · research.md · data-model.md · quickstart.md
├── contracts/report-blocks-and-protocol.md
└── checklists/requirements.md
```

### Source Code (repository root)

```text
backend/
├── config/
│   ├── insights.yaml          # thresholds per attribute, relevance rules
│   ├── sense.yaml             # sense rules per attribute (magnitude, meaning, cross-checks, result ranges)
│   ├── report_layouts.yaml    # sections per profile: order, open_by_default, depth
│   ├── tech_explainers.yaml   # short explanations of powertrain/gearbox/platform technologies
│   ├── queries.yaml / sources.yaml   # + depreciation area; manufacturer kinds
│   └── generations.yaml       # + transmissions/drives per generation where several exist
├── src/automind/domain/
│   ├── insights.py  verdict.py  sense.py  profile_gaps.py  suggestions.py   # new, pure
│   ├── report_layout.py       # declarative layouts (replaces fixed ORDER)
│   ├── casefile.py / policy.py  # profile with evidence, critique/challenge kinds, questions
│   └── research_plan.py       # + depreciation area
├── src/automind/application/
│   ├── compose.py             # verdict card, data panel, comparison table without empty rows, retention, manufacturer
│   ├── research.py / extraction.py  # depreciation schema, manufacturer kinds, variant gearbox/drive checks
│   └── challenge.py           # re-check of a challenged value
├── src/automind/orchestration/
│   ├── nodes/report.py        # insights → verdict → reporter → report_check → regenerate once
│   ├── guard.py               # report_check (numbers, absence claims, sub-threshold wins, tie winners)
│   └── prompts/reporter_*.md  # write from insights and verdict, per section depth
└── alembic/versions/0007_report_experience.py
frontend/src/
├── i18n/{en,ru,es}.ts + useT()
├── components/blocks/{Verdict,DataPanel,Suggestions,ValueRetention,Manufacturer,ComparisonTable}.tsx
├── components/ProgressGrid.tsx · RatingControl.tsx · ChallengeButton.tsx
└── lib/protocol.ts            # new blocks and messages
```

**Structure Decision**: the existing layered monolith; the new logic is pure domain code plus configuration;
the reporter's role shrinks to phrasing.

## Report pipeline (reference)

```text
facts (sense-checked) ─► insights(profile, thresholds) ─► verdict(ranking, insights, coverage)
        │                         │                               │
        └──────────► blocks (layout per profile) ◄────────────────┘
                                  │
                     reporter(profile, section depth, insights, verdict) ─► report_check ─► (regenerate once)
                                  │
                     reply = verdict card + text + sections + data panel + suggestions
```

## Implementation phases (input for `/speckit-tasks`)

1. **Foundations.** Migration 0007, config files, protocol blocks, i18n skeleton.
2. **Sense and identity** (FR-027/028).
   - `domain/sense.py` with the defect regression set.
   - Gearbox and drive on variants, the resolver, the relevance signal and rejection of contradicting claims.
   - Re-identification of mixed variants.
3. **Insights and verdict** (US1/US3).
   - `insights.py`, `verdict.py`, `report_check`.
   - Reporter prompts rewritten to write from insights.
   - Verdict card block.
4. **Layouts and table** (US3/US2).
   - Declarative per-profile layouts and section depth.
   - Comparison table without empty rows; scores with their basis.
5. **Rich content** (US2).
   - Depreciation area and value-retention block.
   - Manufacturer kinds and block; model-year changes; technology explainers.
6. **Data panel and "find it"** (US4). Panel block, `research_more` with areas, before/after diff.
7. **Dialogue** (US5).
   - Profile fields with evidence; `profile_gaps` and questions.
   - Suggestions; the critique kind (research or rework); challenge and re-check; ratings.
8. **Progress, language, layout** (US6/US7). Progress events and grid, i18n ru/es/en, phone layout.
9. **Validation.**
   - Golden G12–G18; live runs on the configured model.
   - Usability check with people (SC-001), run by the user.
   - ADRs and README.

## Complexity Tracking

None. The Constitution Check has no violations.
