# Golden dialogues (FR-046, SC-001, SC-002)

Seven scripted conversations with expected actions, case-file fields and resolved variants per turn
(not prose). Format: `schema.py`; runner: `runner.py`.

| ID | What it checks |
|---|---|
| G1 `g1_bigster_prado` | Asks the used Prado's age → J150 (never J250) → confirm → buyer report from cache → "status" from context → "I meant the used 150" changes nothing |
| G2 `g2_bmw_vs_golf_age20` | Russian in/out; age 20, city + mountains → performance persona; years → F30 and Mk7.5 |
| G3 `g3_persona_expert` | "the same, but I'm a car engineer" → expert order (engineering first), no research |
| G4 `g4_buyer_followup` | "and for a smart buyer?" → buyer order, nothing researched, no repeated report |
| G5 `g5_add_third_car` | Adding the Tesla researches only the Tesla; a 4th car → "which 3?" |
| G6 `g6_no_repeat` | Same request twice → "nothing new", no repeated report |
| G7 `g7_cost_confirmation` | Deep research of 3 uncached cars asks for cost confirmation first; skip → no research; cap €1.00 |

## Running

```bash
uv run pytest tests/golden                       # replay: scripted model outputs + fixture search (free)
GOLDEN_VERBOSE=1 uv run pytest -s tests/golden   # with per-turn action, case, variants, duration
uv run pytest tests/golden -m live               # real models + Tavily (costs money)
uv run pytest tests/golden -m live --record      # also rewrite the cassettes from the live outputs
```

The cassettes in `cassettes/` are hand-written to match the live model behaviour; the live run validates
them against the real models (see below).

## Live run — 2026-11-02

All 7 dialogues **passed** with `openai:gpt-5.4` (interpreter, reporter, answerer) and
`openai:gpt-5.4-mini` (asker, resolver, extractor, validator), real Tavily search.

- Total: 20 turns, 2 min 13 s, **≈ €0.45** (estimate: `config/prices.yaml` holds placeholder prices).
- Earlier live runs found and fixed two real problems: a correction without the age reset a confirmed
  car (now the known context is kept), and `model: "Golf GTI"` duplicated a catalog entry (now model
  lines are matched by prefix).

| Measure | Target | Live result |
|---|---|---|
| Answers from cache (REPORT / ANSWER_FROM_CONTEXT, no research) | ≤ 15 s p90 (SC-004) | 3.8–8.6 s (max 8.6 s) ✅ |
| Weight change via chat ("if I prefer status") | ≤ 5 s (SC-009) | 5.8 s ❌ — two model calls (understand + answer); the recompute itself takes milliseconds. Via the case panel the weights apply instantly and the next message recomputes. |
| Research of one new car at Standard depth (G5, Tesla) | — | 24.5 s, 16 model calls, 7 searches, €0.14 |
| New 2-car comparison at Standard depth | ≤ 3 min p90 over ≥ 5 runs (SC-005) | **not measured yet** — needs ≈ €1–2 of live research; run on request |

Durations are stored per turn in `turns.duration_ms`.
