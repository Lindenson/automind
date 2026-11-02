# Evaluation data

- `reference_vehicles.yaml` — Tier 1 reference set for SC-007 (coverage/accuracy) and SC-011 (race
  calibration ±15% against instrumented 0–100 tests). **Empty on purpose**: every value must come from a
  cited source (manufacturer data, magazine instrumented tests), so the set is curated, not generated.
  Add ≥ 20 entries in the documented format; `tests/eval/test_reference_set.py` then runs the
  calibration offline (free) and the coverage check live (≈ €0.15 per vehicle).
- `../tests/eval/used_resolution.yaml` — 22 used-car requests with the expected generation (SC-003).
  Live run 2026-11-02: 22/22 correct (100%), ≈ €0.35.
