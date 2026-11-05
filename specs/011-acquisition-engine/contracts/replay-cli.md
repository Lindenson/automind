# Contract: Replay command (`python -m automind.acquisition.replay`)

Offline evaluation of a reader or extractor version over stored snapshots against gold values (FR-004, SC-001).

```text
python -m automind.acquisition.replay
    (--reader KEY | --reader-spec FILE.json | --extractor KEY [--model MODEL])
    [--since 30d | --from 2026-10-01 --to 2026-11-05]
    [--domain km77.com] [--attribute max_power ...] [--limit-pages N]
    [--json] [--mismatches N]
```

- `--reader km77@v2`: a stored `parser_versions` row (before US4: `km77@v1` = the legacy YAML reader).
- `--reader-spec`: a candidate spec not stored yet (validated by `ParserSpec` first; exit 2 on schema error).
- `--extractor extract_specs@v4`: worker-only by default (needs model calls; refused with exit 3 unless
  `--allow-llm` is passed and the budget allows); uses `extraction_cache`.
- Offline: readers run with the socket guard on; any network attempt aborts with exit 4. No `llm_calls` row is
  written for a reader replay.

## Output (`--json`)

```json
{
  "version": "km77@v2", "period": {"from": "2026-10-06", "to": "2026-11-05"},
  "pages": 50, "pages_with_fields": 47, "fields_per_page": 11.2,
  "rows_read": 590, "rows_accepted": 560, "pass_rate": 0.949,
  "gold_covered": 50, "gold_match": 48, "accuracy": 0.96, "accuracy_lb": 0.865,
  "by_attribute": {"max_power": {"covered": 12, "match": 12}, "curb_mass": {"covered": 9, "match": 8}},
  "mismatches": [
    {"snapshot_id": "…", "url": "https://www.km77.com/…", "variant_id": "…", "attribute": "curb_mass",
     "ours": 1540.0, "gold": 1465.0, "unit": "kg", "gold_rule": "exact+eu_running_order_minus_driver",
     "gold_dataset": "eea_co2_2024", "quote": "Peso 1540 kg"}
  ],
  "duration_s": 12.4, "network_calls": 0, "llm_calls": 0
}
```

Text mode prints the same as a short table and the first `--mismatches` (default 10) mismatches.

## Library form

`acquisition.replay.run(ReplayRequest) -> ReplayReport` (same fields); the gates (`gate_replay`) call it with an old
and a new version on the same corpus and compare with `domain/gates.py`.

## Exit codes

0 ok · 1 no pages in the period · 2 invalid spec · 3 extractor replay refused (LLM/budget) · 4 network attempt.
