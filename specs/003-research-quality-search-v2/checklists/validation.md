# Validation: 003 research quality and search v2

**Date**: 2026-11-02 · **Branch**: `003-research-quality-search-v2`

## Gates

- [x] `scripts/check.sh`: ruff, format, mypy (domain), import-linter, pytest (271 passed, 1 skipped), frontend (16).
- [x] Golden dialogues G1–G7 live on the new pipeline: 7/7 after G7 was adapted (see below).

## Eval: one car, clean databases (user chose a one-car comparison)

Toyota Land Cruiser Prado J150 2.8 D-4D 177 CV, Standard depth, each run on an empty database
(`backend/eval/out/*-2026-11-02.md`).

| Metric | 002 pipeline (old code, Tavily) | 003 pipeline, Tavily | 003 pipeline, Serper (default) |
|---|---|---|---|
| Areas meeting their minimum | 67% (specs, maint., reliab., reviews) | 67% | **83%** (+ official price) |
| Accepted values | 79 | 254 | 178 |
| Search cost | €0.326 | €0.370 | **€0.024** (−93%, SC-002 ✅ on this car) |
| LLM cost | €0.038 | €0.063 | €0.053 |
| Cost per accepted value | €0.0046 | €0.0017 | **€0.00043** (−91%, SC-003 ✅ on this car) |
| Wrong-variant power | none | none | none |
| Duration | 31 s | 118 s | 79 s (ultimatespecs asks for 30 s between requests) |

Still open on this car: instrumented 0–100 (measured) is not found by any pipeline. SC-001 (≥ 80% over
20 cars), SC-004 (≥ 95% wrong-variant pages rejected on a labelled sample) and SC-005 (≥ 90% reader
share) need the full benchmark run.

## Problems found and fixed during validation

1. **Eval wrote into the development database.** Settings were cached before the eval switched the
   database URL; the first two one-car runs used `automind` (with earlier data). Fixed
   (`settings.cache_clear()` + assertion), rows of those runs removed, all numbers above re-measured on
   clean databases. The 002 baseline was re-run from commit `3e391cd` in a separate worktree.
2. **AI call limit 80 cut research short** with more pages per area. Raised to 160 per turn (the €1 cost cap
   still bounds a turn); pages per job 6.
3. **Limits cancelled research** (user feedback). Research now pauses near a limit and asks
   "continue / answer with what you have" (FR-032, T024a).
4. **G7 (cost confirmation)** no longer triggered: with Serper a deep 3-car research is estimated below
   €0.30. The dialogue now sets a lower threshold for itself to keep testing the confirmation.
5. **Event seq collisions** under parallel research jobs ("could not allocate event seq"): allocation is
   serialised per chat with an advisory lock.

## Note on spend

Live runs in this session: one-car evals ≈ €0.42 + €0.43 + €0.36 (old code), golden dialogues run twice by
mistake (≈ €0.5) plus G5/G7 reruns (≈ €0.1).
