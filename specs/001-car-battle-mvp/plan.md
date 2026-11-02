# Implementation Plan: Ultimate Car Battle (AutoMind MVP)

**Branch**: `001-car-battle-mvp` | **Date**: 2026-11-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-car-battle-mvp/spec.md`

## Summary

The MVP lets a user compare 2–4 exact vehicle variants (ICE, EV, HEV/PHEV) using technical data
that has a source for every value. The user enters cars; the system resolves exact variants
(reusing the local catalog when data is fresh) and waits for plan approval. It then fans out
parallel research workers that retrieve documents and extract claims, and a deterministic
validator checks that each claim really appears in its source. Next, it verifies claims
(mismatches, units, conflicts resolved by authority order and then majority) with bounded
follow-up rounds. Finally, deterministic Python code computes metrics, rankings, rule-based
confidence levels, and a drag race simulation v0.1, and the result is an immutable report.

Technical approach: a Python modular monolith (domain → application → orchestration →
infrastructure → API). Orchestration uses LangGraph 1.2 with an interrupt for approval, `Send`
for fan-out, verification and analysis subgraphs, and a Postgres checkpointer for restart
recovery. All LLM calls go through a single OpenAI/Anthropic gateway with call budgets. FastAPI
serves REST and SSE (with replay). A thin React + TypeScript UI renders backend data. Details:
[research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.12+ (backend; uv-managed, target 3.13); TypeScript 5.x
(frontend, strict)

**Primary Dependencies**:
- **Backend**: FastAPI, Pydantic v2, pydantic-settings, LangGraph 1.2.x,
  langgraph-checkpoint-postgres 3.x, langchain-core, langchain-anthropic, langchain-openai,
  SQLAlchemy 2 (async) + asyncpg, psycopg 3 (checkpointer), Alembic, sse-starlette, httpx,
  tavily-python (default search), rapidfuzz, structlog, langsmith.
- **Frontend**: React 19, Vite, TanStack Query, Zustand, React Router, ECharts, Tailwind CSS, Zod.

**Storage**: PostgreSQL 16 (domain tables + separate LangGraph checkpoint tables); document text
and simulation time series as content-addressed files under `data/artifacts/`

**Testing**: pytest, pytest-asyncio, hypothesis, respx, a fake LLM with recorded outputs, and a
FixtureProvider (backend); vitest + Testing Library and one Playwright smoke test (frontend);
an opt-in evaluation suite against the reference set

**Target Platform**: Local Linux/macOS developer machine via Docker Compose (Postgres); backend
and frontend run natively or in containers; modern desktop browser

**Project Type**: Web application (backend API + frontend SPA) in one repository

**Performance Goals**: 3-vehicle research completes in < 10 min (p90, SC-002); progress
visible in < 5 s (SC-010); drag race simulation < 200 ms for 4 vehicles; plan ready in < 60 s (SC-014)

**Constraints**: All numbers come from deterministic code; every value has evidence or a
provenance label; per-research budgets (default 150 LLM calls, 2 follow-up rounds, concurrency
6, 30 s request timeout); untrusted web content never reaches a model that has tools; API bound
to localhost; secrets only from `.env`

**Scale/Scope**: Single local user; ≤ 2 concurrent researches; ≤ 4 vehicles per research; ~6–12
worker tasks per research; catalog of hundreds of variants; ~5 UI pages

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | How the design complies | Pre | Post |
|---|---|---|---|---|
| I | Evidence first, never invent | Each claim requires evidence and an excerpt; the excerpt validator rejects text not found in the source (R5); missing values stay `available=false`; conflicts are persisted and surfaced (FR-017); evidence is kept in DB and artifact files, independent of graph state | ✅ | ✅ |
| II | Exact vehicle identity | `vehicle_variants` with `canonical_key`, separate from `vehicle_specs`; ambiguity blocks approval; claims from a mismatched variant are rejected (data-model §3) | ✅ | ✅ |
| III | Deterministic computation | Units, conflicts, confidence, metrics, rankings, and simulation are pure domain functions; `Decimal` storage; fixed-step simulation with `input_hash`; the LLM only extracts and writes narrative that references computed values | ✅ | ✅ |
| IV | Provenance classes | A `Provenance` enum on every SpecValue, metric (DERIVED), simulation (SIMULATED_ESTIMATE), and assumption (ASSUMPTION); confidence is H/M/L and never a probability | ✅ | ✅ |
| V | Layered modular monolith | Package layout below; the domain imports nothing external except Pydantic; nodes call application services; the frontend uses only `/api/v1` DTOs; SSE payloads are DTOs | ✅ | ✅ |
| VI | Bounded, stateful, human-steered | Interrupt-based approval; `Send` fan-out with append reducers; the follow-up loop is limited by `max_followup_rounds`; gateway call budget; `recursion_limit`; Postgres checkpointer plus startup resume; cancel flag; a failed task leaves the session running | ✅ | ✅ |
| VII | Provider independence | `LLMGateway` port; per-role model config; both providers wired; `llm_calls` usage and cost | ✅ | ✅ |
| VIII | External content untrusted | Delimited documents; the extractor has no tools; least-privilege tools per role; search APIs plus an allow-listed fetcher with robots, timeout, and size limits; no scraping of spec databases; keys only on the backend | ✅ | ✅ |
| IX | Test-first core & reproducibility | Unit and property tests for the core before implementation; 10 graph scenarios; versioned rules and simulation; immutable report artifact; calibration test gates the "realistic" wording (SC-009) | ✅ | ✅ |
| X | Simplicity / YAGNI | No queue, Redis, vector DB, or microservices; in-process runner; MARKET category stubbed only; export deferred | ✅ | ✅ |
| Stack | Technology & Data Constraints | Matches the constitution's stack exactly; psycopg 3 is added only because the official checkpointer requires it (R11) | ✅ | ✅ |

**Result**: PASS (pre-research and post-design). No violations, so Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-car-battle-mvp/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1–R14
├── data-model.md        # Phase 1: entities, enums, state machine, graph state
├── quickstart.md        # Phase 1: run + validation scenarios V1–V20
├── contracts/
│   ├── openapi.yaml     # REST /api/v1 (validated OpenAPI 3.1)
│   └── sse-events.md    # Event stream contract
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
docker-compose.yml               # postgres (+ optional backend/frontend services)
.env.example
eval/
└── reference_vehicles.yaml      # ≥20 vehicles: specs + instrumented results (SC-004/005/009)

backend/
├── pyproject.toml
├── alembic/                     # domain tables only (checkpointer owns its own)
├── config/
│   ├── models.yaml              # role → provider/model/limits; price table
│   └── sources.yaml             # domain → SourceType registry; fetch allow-list
├── src/automind/
│   ├── domain/                  # pure: no LangGraph/FastAPI/SQLAlchemy/LLM imports
│   │   ├── vehicles.py          # VehicleVariant, canonical key, freshness
│   │   ├── specs.py             # SpecAttribute registry, SpecValue, tiers, tolerances
│   │   ├── units.py             # Quantity, conversions, weight definitions
│   │   ├── evidence.py          # Evidence, Claim, excerpt validation
│   │   ├── conflicts.py         # detect/resolve (FR-017)
│   │   ├── confidence.py        # H/M/L rules (FR-018)
│   │   ├── comparison.py        # derived metrics, rankings
│   │   ├── issues.py            # TechnicalIssue, recurrence rule
│   │   ├── research.py          # Research, Plan, Task, state machine
│   │   └── simulation/
│   │       ├── assumptions.py   # defaults by body class / powertrain
│   │       └── dragrace_v0_1.py # simulate() pure function
│   ├── application/
│   │   ├── ports.py             # LLMGateway, SearchProvider, PageFetcher, repositories, EventBus
│   │   ├── catalog_service.py
│   │   ├── planning_service.py
│   │   ├── research_service.py  # extraction pipeline per task
│   │   ├── verification_service.py
│   │   ├── analysis_service.py
│   │   ├── simulation_service.py
│   │   └── report_service.py
│   ├── orchestration/
│   │   ├── state.py             # TypedDicts + reducers
│   │   ├── main_graph.py        # parse → resolve → plan → approve(interrupt) → fan-out → …
│   │   ├── worker_graph.py      # reusable worker subgraph (category-parameterized)
│   │   ├── verification_graph.py
│   │   ├── analysis_graph.py
│   │   ├── prompts/             # versioned prompt templates
│   │   └── runner.py            # ResearchRunner: tasks, resume on startup, cancel
│   ├── infrastructure/
│   │   ├── config.py            # pydantic-settings
│   │   ├── db/                  # SQLAlchemy models, repositories, session
│   │   ├── checkpoint.py        # AsyncPostgresSaver setup
│   │   ├── llm/gateway.py       # init_chat_model, structured output, budget, usage
│   │   ├── search/              # tavily.py, brave.py, fixtures.py
│   │   ├── fetch.py             # allow-listed httpx fetcher (robots, limits)
│   │   ├── artifacts.py         # content-addressed file store
│   │   ├── events.py            # research_events + in-memory pub/sub
│   │   └── observability.py     # structlog, LangSmith
│   ├── api/
│   │   ├── app.py               # FastAPI factory, lifespan (runner resume)
│   │   ├── schemas.py           # request/response DTOs (match contracts/openapi.yaml)
│   │   ├── routers/             # researches.py, vehicles.py, simulations.py, health.py
│   │   └── sse.py
│   └── cli.py                   # `automind serve | research | eval`
└── tests/
    ├── unit/                    # domain + application (fakes)
    ├── graph/                   # 10 constitution scenarios
    ├── integration/             # postgres, adapters (respx), SSE replay
    ├── contract/                # OpenAPI diff
    ├── eval/                    # opt-in, reference set, calibration
    └── fixtures/                # documents, search results, recorded LLM outputs, scenarios

frontend/
├── package.json
├── src/
│   ├── api/                     # fetch client, Zod schemas (from contracts), SSE hook
│   ├── stores/                  # Zustand: UI drafts only
│   ├── pages/                   # NewResearch, Research (plan/progress/results), DragRace, History, Catalog
│   ├── components/              # SpecTable, ProvenanceBadge, ConfidenceBadge, EvidenceLink,
│   │                            # ConflictPanel, TaskList, RaceCharts, RaceAnimation, RaceSettings
│   └── main.tsx
└── tests/                       # vitest + one Playwright smoke (backend fixture mode)
```

**Structure Decision**: A web application with `backend/` (Python modular monolith; the layer
packages enforce constitution V, checked by an import-linter contract in CI) and `frontend/`
(Vite SPA). `eval/` holds the shared reference dataset. A single `docker-compose.yml` provides
PostgreSQL; the app services can optionally be containerized for the demo.

## Main graph (reference)

```text
START → parse_request → resolve_variants → build_plan → approval (interrupt)
   ├─ EDIT → resolve_variants (re-plan, plan_version+1)
   ├─ REJECT → END (state CANCELLED, no tasks run)
   └─ APPROVE → fan_out (Send per vehicle × category, skipping REUSE vehicles)
        → worker_subgraph ×N  [search → fetch → extract (no tools) → validate excerpts → persist claims]
        → aggregate → verification_subgraph [variant match → units → conflicts → resolve → gaps]
             ├─ follow-ups needed & round < max → fan_out (targeted follow-up tasks)
             └─ else → analysis_subgraph [normalize → SpecValues+confidence → metrics → rankings]
        → simulate_default_race → write_report → END
```

Cross-cutting: every node checks `cancel_requested`. External-call nodes have a `RetryPolicy`
(3 attempts, exponential backoff, retrying only transient errors). `BudgetExceeded` routes to
the next phase with `limits_reached` updated. Events go out through the EventBus.

## Implementation phases (input for `/speckit-tasks`)

1. **Foundation**: repo layout, uv/pnpm, docker compose, settings, logging, Alembic baseline,
   import-linter layer contract.
2. **Deterministic core (tests first)**: units, spec registry, conflicts, confidence, metrics,
   rankings, state machine, simulation v0.1 with assumptions. → US1/US2/US3 core.
3. **Ports + adapters**: LLM gateway (both providers, budget, usage), search (Tavily, Brave,
   fixtures), fetcher, artifact store, repositories.
4. **Graph**: state and reducers, worker subgraph, main graph with interrupt, verification and
   analysis subgraphs, runner (resume and cancel). The CLI demo is the first milestone
   (`sec.md` §16).
5. **API + SSE**: routers per contract, event store and replay, contract test.
6. **Frontend**: new research → plan approval → progress → results (specs, metrics, conflicts,
   issues) → drag race (settings, prediction, charts, animation) → history and catalog.
7. **Evaluation**: reference set, eval command, calibration of the simulation (v0.1.x if tuned).

Stories map to phases as follows: US1 → 2, 3, 4, 5, 6; US2 → 2, 6; US3 → 2, 4; US4 → 4, 5, 6;
US5 → 3, 4; US6 → 5, 6.

## Complexity Tracking

No constitution violations; nothing to justify.
