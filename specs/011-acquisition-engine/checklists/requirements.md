# Specification Quality Checklist: Acquisition Engine

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-05
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Technical terms that appear (worker, task queue, import contracts, Prometheus-free wording) name the owner's accepted architecture from the review, not implementation choices left open; the plan decides the details.
- Staging (US1 → US5) is the core constraint: agents (US5) are not enabled before measurability (US1), separation (US2), honest reputation (US3) and parser versions (US4).
- Stage 1 check (T036, 2026-11-05): goldens green; the diff of `backend/src/automind/application/research.py` against
  main is 5 insertions, 6 deletions (net -1). SC-001 timing of `python -m automind.acquisition.replay --reader km77@v1
  --since 1h` measured on the test database (the shared dev database stays at 0017 until this branch is merged, so it
  was not migrated): 3,007 stored km77 pages in 1.65 s wall (about 0.55 ms per page, batches of 500, zero network
  and model calls), i.e. about 17 s for 30,000 pages, inside the 5-minute target. Re-measure on the dev database with
  `--since 30d` after the merge.
- Stage 2 strangler check (T059, part, 2026-11-05, branch `011-us2-strangler`): goldens green after every step S0–S8
  (12 passed each time) and the full suite green (1,124 passed); `lint-imports` 9 contracts kept, with no `research`
  exception (`FROZEN_LEGACY_IGNORES` 14 → 12) and `chat-uses-acquire-only` over application, orchestration and
  domain without `ignore_imports`; `test -e backend/src/automind/application/research.py` fails (deleted in T049).
  The facade test (T038) returns the values recorded from the pre-move `run_job` on `bmw520`. Open: the SC-005
  measurement (p50/p95 of `automind_turn_duration_seconds` on 10 live turns with the worker's prefetch running vs
  stopped) needs the worker (T054–T057, branch `011-us2-worker`) and live model/search calls; T059 stays open for it.
