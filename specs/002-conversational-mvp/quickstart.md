# Quickstart and Validation: AutoMind Conversational MVP

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) |
**Contracts**: [chat-protocol.md](./contracts/chat-protocol.md), [rest-and-mcp.md](./contracts/rest-and-mcp.md)

## Prerequisites

- `.env` with `OPENAI_API_KEY` and `TAVILY_API_KEY` (see `.env.example`).
- `uv` and Node 22 in `~/.local/bin`.
- Local dev uses the embedded Postgres in `./.pgdata` (`scripts/dev.sh`). Deployment uses Docker
  Compose.

## Run

```bash
cd frontend && npm install && npm run build && cd ..
scripts/dev.sh                     # DB + migrations + API (+ built UI) → http://127.0.0.1:8000
# UI development: cd frontend && npm run dev → http://127.0.0.1:5173
```

## Test gates

```bash
cd backend
uv run ruff check src tests && uv run mypy src/automind/domain && uv run lint-imports
uv run pytest tests/unit                     # pure rules: case file, policy, criteria, TCO, resolution, cost, physics
uv run pytest tests/graph                    # graph mechanics with scripted fake LLM + fixture search
uv run pytest tests/golden                   # golden dialogues, replay mode (recorded LLM outputs)
uv run pytest tests/golden -m live           # golden dialogues against real models and search (≈ €0.50, opt-in)
cd ../frontend && npm run typecheck && npm test
```

## Golden dialogues (FR-046, SC-001/002)

Assertions check the action, case-file changes and resolved variants per turn, not exact prose.

| ID | Turns (user) | Expected |
|---|---|---|
| G1 | "I don't want to spend too much… brand-new Dacia Bigster or a used Land Cruiser Prado?" | ASK (≤3 questions, includes Prado age or generation); case: Bigster NEW, Prado USED, persona BUYER (inferred), priorities include ownership_cost, reliability |
| | "about 10 years old, the 150" | CONFIRM_VARIANTS with Prado 150 (generation years include ~2015); no J250 anywhere |
| | (confirm) | CONFIRM_COST or RESEARCH → REPORT with buyer order (criteria_scores, tco, reliability…); tco shows BIG_TICKET + BASE_RESERVE for the Prado |
| | "if I prefer status, who wins?" | ANSWER_FROM_CONTEXT; status added to priorities; 0 search calls; indicators named |
| | "but I meant the used 150, not new" | Nothing to correct (already the 150). The answer confirms the current variant; no research, no repeated report |
| G2 | "I'm 20, I can buy a used BMW 320d M Sport or Golf R-Line 4Motion — compare on drag race, city and mountains" | case: age 20, both USED (asks year if more than one generation is plausible), usage CITY + MOUNTAINS, persona PERFORMANCE; report order starts with race_chart; criteria include offroad_mountain, traction |
| G3 | After G1's report: "the same, but I'm a car engineer" | Persona → EXPERT; ANSWER_FROM_CONTEXT or RESEARCH(engineering only); report order starts with engineering |
| G4 | "Golf GTI Mk8 vs i30 N for a race enthusiast" → "and for a smart buyer?" | 2nd turn: no research for specs (cache), only missing buyer areas; persona or weights change; not a repeat |
| G5 | Then "add the Tesla Model 3 Performance" | Only the Tesla researched; 3 cars; a 4th car → ASK which 3 |
| G6 | "Golf GTI Mk8 vs i30 N" twice in a row | 2nd: ANSWER_FROM_CONTEXT "nothing new", fingerprint equal, no repeated report (FR-004) |
| G7 | Deep research of 3 new cars | CONFIRM_COST with estimate ≥ €0.30; "skip" → no research; total turn cost never > €1.00 |

## Manual validation scenarios

| # | Scenario | Expected | Validates |
|---|---|---|---|
| V1 | Open the case panel and change the persona to BUYER, then send "and now?" | Report reordered for buyer, recomputed without research in < 5 s | FR-009, FR-029, SC-009 |
| V2 | Move the "status" weight slider to 40% | criteria_scores recomputed; winner may change; no search | FR-026, FR-029 |
| V3 | Ask "how does a turbo work?" | General answer with "no sources" notice; no car figures | FR-011 |
| V4 | Reload the browser mid-research | Progress continues; no missed events (replay) | R13 |
| V5 | Stop the backend mid-research and start it again | Turn resumes; done jobs not re-run (job attempts unchanged) | FR-044, SC-013 |
| V6 | Press Cancel during research | Turn cancelled; validated data stays in cache | FR-043 |
| V7 | Check the usage badge vs DB `llm_calls` + `search_calls` for the turn | Equal, including reporter agent calls | FR-042, SC-012 |
| V8 | Ask about a 30-year-old car | Early warning about scarce sources; insufficient-data sections | edge cases |
| V9 | Ask for "a nice colour" | Reported as not assessable (unmapped wish) | FR-028 |
| V10 | Write in Russian, then Spanish | Replies follow the language; labels consistent | FR-001 |
