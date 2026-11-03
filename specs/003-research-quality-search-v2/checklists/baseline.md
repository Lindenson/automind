# Baseline: 002 research pipeline (Tavily), before spec 003

**Date**: 2026-11-02 · **Run**: `uv run python eval/run_research_eval.py --provider tavily --label baseline1 --cars 1`
(the user chose a one-car baseline; result file `backend/eval/out/baseline1-2026-11-02.{json,md}`).

## One-car run (Toyota Land Cruiser Prado J150 2.8 D-4D 177 CV, Standard depth)

| Metric | Value |
|---|---|
| Areas meeting their minimum | 4 of 6 (67%): specs ✅, maintenance ✅, reliability ✅, reviews ✅, measured ❌, price ❌ (after 2 rounds) |
| Search calls | 22 (Tavily advanced search + extract) |
| Search cost | €0.326 (89% of the total) |
| LLM cost | €0.041 |
| Accepted values | 87 (cost per accepted value €0.0042) |
| Wrong-variant power | none (130.2 kW = 177 CV) |
| Duration | 34.9 s |

## Development database (002 live use, many chats)

| Metric | Value |
|---|---|
| Tavily search / extract | 77 calls ≈ €1.14 / 26 calls ≈ €0.39 |
| All LLM calls | ≈ €0.55 |
| Instrumented-test (measured) jobs with nothing accepted | 7 of 12 |
| Official-price jobs with nothing accepted | 4 of 7 |
| Reliability claims accepted / rejected | 33 / 39 |

These are the reference numbers for SC-001 (minimum met), SC-002 (search cost), SC-003 (cost per accepted
value) and SC-010 (duration). The comparison run of the new pipeline uses the same car first, then the
full benchmark.
