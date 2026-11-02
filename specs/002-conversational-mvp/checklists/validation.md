# Validation: quickstart V1–V10 and gates

**Date**: 2026-11-02 · **Build**: branch `002-conversational-mvp` · **Models**: `openai:gpt-5.4` (interpreter,
reporter, answerer), `openai:gpt-5.4-mini` (asker, resolver, extractor, validator) · **Search**: Tavily

The scenarios were run against a live server (`uvicorn`, port 8002) through the WebSocket protocol v2
and the `/api/v1` REST API, the same calls the UI makes; no browser was available in this session.
Scenarios that need a crash or a reload are covered by graph tests with the real Postgres checkpointer.

## Gates

- [x] `scripts/check.sh`: ruff, ruff format, mypy (strict, domain), import-linter (2 contracts), pytest
  (198 passed, 1 skipped: reference-set calibration has no sourced data yet), frontend typecheck + vitest (15).
- [x] Golden dialogues G1–G7: replay ✅; live ✅ (7/7, ≈ €0.45) — see `backend/tests/golden/README.md`.
- [x] Used-car generation resolution (SC-003): 22/22 = 100% live (≈ €0.35).

## Scenarios

| # | Scenario | Result | How verified |
|---|---|---|---|
| V0 | "Golf GTI Mk8 vs i30 N for a race enthusiast", new research | ✅ i30 N variant confirmed, research of missing areas, REPORT in 28 s; measured vs claimed 0–100 shown; "insufficient data" where minimums were not met | live |
| V0b | Same request later, data cached | ✅ REPORT from cache in 12.8–15.5 s, 0 searches | live |
| V1 | Panel: persona → BUYER, then "and now?" | ✅ after fixes (see below). Buyer areas were not cached, so the hub offered research (€0.34); after "answer with what you have" it answered from cache in 3.7 s with 0 searches and kept BUYER. Reordered blocks for the new persona: graph test `test_persona_changed_in_panel_reorders_and_is_not_overwritten` | live + graph test |
| V2 | Panel: weights (performance 50 / efficiency 50), "and now?" | ✅ ANSWER_FROM_CONTEXT, criteria scores recomputed, 0 searches, 6.1 s end to end (two model calls; recompute itself < 0.1 s) | live + `test_weights_recompute.py` |
| V3 | "how does a turbo work?" | ✅ ANSWER_GENERAL, no car figures, ends with "General knowledge — no sources checked." | live |
| V4 | Reload mid-research | ✅ `hello{last_seq}` replays exactly the missed events (seq 3–6 after a reconnect at 2) | live smoke (WebSocket) |
| V5 | Backend killed mid-research, restarted | ✅ the turn resumes from the checkpoint; jobs already DONE are not rerun (attempts unchanged) | `test_cancel_and_resume.py` |
| V6 | Cancel during research | ✅ turn CANCELLED, open jobs SKIPPED, validated claims stay cached | `test_cancel_and_resume.py` |
| V7 | Usage badge vs DB | ✅ shown usage = `llm_calls` + `search_calls` rows of the turn, incl. failed calls and agent steps | `test_usage_accounting.py` |
| V8 | Used 1994 Mercedes E-Class W124 | ✅ resolved W124 (1985–1995), confirmed, early warning "older than 25 years — sources are scarce", report marks insufficient data | live |
| V9 | "I'd also like a nice colour" | ✅ recorded as not assessable; answer says it cannot rank by colour from data | live |
| V10 | Russian, then Spanish | ✅ answers and fixed phrases (cost/variant confirmations) in the user's language | live |

## Problems found by this validation and fixed

1. **Repeated cost question.** After the user ignored a research offer, every next message asked again.
   Now a declined plan is remembered (`case.declined_plan`) and not offered again until it changes.
2. **Persona overwritten from history.** "and now?" made the model re-infer "race enthusiast" from the
   first message and overwrite the persona set in the panel. Now a persona change needs verbatim words
   from the current message (`persona_evidence`, checked by code).
3. **Panel persona change showed only scores.** Answers now show the full report in the new persona's
   order when the persona differs from the last report's.

Earlier live runs in this session also fixed: a correction without the age reset a confirmed car;
`model: "Golf GTI"` duplicated a catalog entry; concurrent research jobs raced on the selected values
(advisory lock); failed model calls were counted but not recorded.

## Open

- SC-005 (new 2-car Standard research ≤ 3 min p90 over ≥ 5 runs): one live 2-car research took 28 s;
  the 5-run measurement (≈ €1–2) has not been run.
- SC-007 / SC-011: the reference set `backend/eval/reference_vehicles.yaml` needs ≥ 20 sourced vehicles
  (manufacturer data + instrumented tests); the evaluation code is ready.
- SC-014 (usability check with 3 people) is a human test.
- Docker image and compose: updated, not run (Docker is not installed on this machine).
- `config/prices.yaml` holds placeholder model prices; € figures are estimates until verified.
- Priorities inferred from the first message (e.g. performance from "race enthusiast") stay after a
  persona change; the user can remove them in the case panel.
