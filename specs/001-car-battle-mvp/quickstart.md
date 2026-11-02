# Quickstart & Validation Guide: Ultimate Car Battle (AutoMind MVP)

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) |
**Contracts**: [openapi.yaml](./contracts/openapi.yaml), [sse-events.md](./contracts/sse-events.md)

This guide shows how to run the MVP and prove it works. Each scenario lists the user story or
success criterion it validates.

## Prerequisites

- Docker and Docker Compose v2
- `uv` (Python 3.12+ is installed automatically from `.python-version`)
- Node.js 22 LTS and `pnpm`
- An API key for at least one LLM provider (`ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY`) and one
  search provider (`TAVILY_API_KEY` or `BRAVE_API_KEY`). These are **not needed in fixture
  mode**.

## Setup

```bash
cp .env.example .env                 # fill in keys; never commit .env
docker compose up -d postgres
cd backend && uv sync && uv run alembic upgrade head && cd ..
cd frontend && pnpm install && cd ..
```

## Run

```bash
# Real providers
docker compose up -d postgres
cd backend && uv run automind serve            # API on http://127.0.0.1:8000
cd frontend && pnpm dev                        # UI on http://127.0.0.1:5173

# Offline demo with fixture data and a fake LLM (deterministic, free)
AUTOMIND_MODE=fixtures uv run automind serve
```

There's also a CLI that runs the first technical demo (`sec.md` §16) with no frontend:

```bash
uv run automind research "VW Golf GTI Mk8" "Hyundai i30 N" "Tesla Model 3 Performance" \
    --auto-approve --json > out/report.json
```

## Automated test gates

```bash
cd backend
uv run pytest tests/unit                 # deterministic core: units, rules, metrics, simulation
uv run pytest tests/graph                # 10 constitution graph scenarios (fixtures + fake LLM)
uv run pytest tests/integration          # needs postgres from docker compose
uv run pytest tests/contract             # generated OpenAPI matches contracts/openapi.yaml
uv run pytest tests/eval -m eval         # opt-in: real providers, reference set (costs money)
cd ../frontend && pnpm test && pnpm test:e2e   # e2e runs against backend in fixture mode
```

## Validation scenarios

| # | Scenario | Steps | Expected outcome | Validates |
|---|---|---|---|---|
| V1 | Happy path, 3 vehicles | In the UI, enter Golf GTI Mk8, i30 N, Model 3 Performance → Submit | Plan appears with exact variants, task count and categories; no research tasks run before approval | US1-1, FR-005, SC-001 |
| V2 | Approve & watch | Approve the plan | Progress shows phase and per-task status updating live; no model reasoning text is shown | US4-1, FR-032, SC-010 |
| V3 | Evidence | Open the comparison | Every Tier 1 value has unit, provenance badge, confidence (H/M/L) and an evidence link; missing values say "unavailable" | US1-3/4, SC-003 |
| V4 | Derived metrics | Look at the metrics tab | Power-to-weight etc. are labeled "derived", show their inputs, and are ranked; vehicles with missing inputs are listed as excluded | US1-5, FR-020/021 |
| V5 | Vehicle count | Try to submit 1 or 5 vehicles | Validation message; API returns 422 `VEHICLE_COUNT_OUT_OF_RANGE` | US1-6 |
| V6 | Ambiguity | Enter just "Golf GTI" | Plan marks it AMBIGUOUS with alternatives; Approve is disabled until one is chosen | FR-004 |
| V7 | Conflicts (fixtures) | Run fixture scenario `conflicting_power` | Conflict shown with both values and sources; authority rule recorded or marked unresolved | US3, FR-017, SC-007 |
| V8 | Variant mismatch (fixtures) | Run fixture scenario `wrong_generation_source` | Claims from the wrong-generation source are rejected and the mismatch is listed | US3-5 |
| V9 | Drag race | Open Drag Race, keep defaults, run | Charts of speed, distance and acceleration over time; table with 0–100, 0–200 (or "not reached"), 400 m time and speed; "simulated estimate" label; claimed and measured values beside it; assumptions listed | US2-1/4, FR-025/026 |
| V10 | EV & hybrid | Include a BEV and a PHEV | BEV shows no shift behavior; PHEV note says "combined system power simplification" | US2-2/3 |
| V11 | Determinism | Run the same race twice | Identical results and `input_hash` | SC-008 |
| V12 | Race settings & prediction | Set wet surface and +200 kg, predict an order, run | Slower times than dry; settings shown; prediction compared; both runs listed | FR-041, US2-7 |
| V13 | Restart recovery | During RUNNING, stop the backend (`Ctrl+C`) and start it again | Research continues automatically; completed tasks are not re-run (check task `attempt` counts and logs) | US4-3, SC-011 |
| V14 | Reconnect | During RUNNING, reload the browser | Progress view restores state with no missing events (SSE replay) | US4-2 |
| V15 | Cancel | Start a research and cancel it | State becomes CANCELLED; no new tasks start; partial report is viewable | US4-4, FR-034 |
| V16 | Worker failure (fixtures) | Run fixture scenario `source_down` | Other tasks complete; failure shown; affected data "unavailable"; research COMPLETED | US4-5, SC-012 |
| V17 | Limits | Create a research with `max_llm_calls: 20` | Research completes with partial data; report lists `max_llm_calls` in limits reached; usage shown | FR-036/037, SC-013 |
| V18 | Catalog reuse | Research the same car again within 90 days | Plan offers REUSE vs RESEARCH; choosing REUSE skips tasks for that vehicle | FR-040 |
| V19 | Technical issues | View a vehicle with a known issue (e.g. a DSG/mechatronic case) | Issues listed with component, sources, RECURRING/ISOLATED; no opinions; otherwise "no documented issues found" | US5 |
| V20 | History | Open History | Past researches with state and date; completed reports open unchanged; interrupted ones offer Resume | US6, FR-035 |

## Evaluation (success criteria SC-004, SC-005, SC-006, SC-009)

```bash
uv run automind eval --reference eval/reference_vehicles.yaml --out out/eval.json
```

It reports variant accuracy (≥ 90%), Tier 1 coverage (≥ 80%) and accuracy (≥ 95% within
tolerance), invented values (must be 0), simulated vs. measured 0–100 within ±15% (≥ 80% of
vehicles), plus total cost and duration.
