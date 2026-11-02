# Implementation Plan: AutoMind Conversational MVP

**Branch**: `002-conversational-mvp` | **Date**: 2026-11-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-conversational-mvp/spec.md`

## Summary

This feature turns the working concept demo into a conversational expert that understands and
remembers the user. Each chat gets a persisted, user-editable **case file**: persona, new/used,
age, usage, budget, weighted priorities, cars and results already shown. The LangGraph hub runs
as **one persistent thread per chat** with a Postgres checkpointer. Each turn works like this:
1. An LLM **interprets** the message into a typed case-file delta.
2. A deterministic **policy** chooses the action: ask, confirm variants (interrupt), confirm cost
   (interrupt), research, answer from context, or report. It never repeats a report.
3. **Research** is planned from the case file's criteria across areas: specs, maintenance,
   reviews, reliability, price, manufacturer, used-car issues. It uses validated extraction and
   bounded gap rounds by depth.
4. Deterministic engines compute **criteria scores**, **TCO** (with the two-part used-car
   reserve) and the drag race.
5. **Persona reporters** (analyst agents with scoped MCP tools) write the explanation. The
   backend orders the blocks per persona.

The demo's tested domain code (units, specs, evidence rules, drag race, number guard), Tavily
adapter, LLM gateway, MCP server and React app are reused and refactored. Details:
[research.md](./research.md) R1–R18.

## Technical Context

**Language/Version**: Python 3.13 (backend, uv); TypeScript 5.6 strict (frontend, Vite 5, React
18). Both are from the demo.

**Primary Dependencies**:
- **Backend (demo)**: FastAPI, Pydantic v2, pydantic-settings, LangGraph 1.2, LangChain 1.4
  (`init_chat_model`, `create_agent`), langchain-openai and langchain-anthropic,
  langchain-mcp-adapters 0.3, mcp 1.30 (FastMCP), SQLAlchemy 2 async + asyncpg, tavily-python,
  rapidfuzz, structlog.
- **Backend (new)**: langgraph-checkpoint-postgres 3.x + psycopg 3 (pool), Alembic, PyYAML.
- **Frontend (demo)**: React, Zustand, Zod, ECharts, Tailwind, react-markdown.

**Storage**: PostgreSQL (dev: embedded via pgserver in `./.pgdata`; deploy: Docker Compose
Postgres 16). Domain tables are under Alembic; LangGraph checkpoint tables are separate.

**Testing**:
- **Backend**: pytest, pytest-asyncio; a scripted fake LLM; a fixture search provider; golden
  dialogue runner (replay and live); ruff, mypy (strict for the domain), import-linter.
- **Frontend**: vitest.

**Target Platform**: Local Linux machine (single user); modern desktop and phone browsers;
Docker for deployment.

**Project Type**: Web application (Python backend + React SPA) in one repository.

**Performance Goals**:
- follow-up from cache ≤ 15 s (p90, SC-004);
- weight change ≤ 5 s (SC-009);
- new 2-car Standard research ≤ 3 min (p90, SC-005);
- progress events within 5 s.

**Stack deviations from the constitution (recorded in ADR-016)**: TanStack Query, React Router
and LangSmith tracing are deferred. The SPA has one screen, and server state comes over
WebSocket (Zustand). Tracing uses structlog plus the `llm_calls`/`search_calls` tables (principle X).

**Constraints**:
- **Cost per turn**: confirmation above €0.30, hard cap €1.00.
- **AI roles**: web readers have no tools; analysts get scoped MCP tools on validated data only.
- **Numbers**: every number in AI text is checked; numbers are computed only by code.
- **Sources**: no classifieds.
- **Network**: localhost bind; secrets only from `.env`.

**Scale/Scope**: 1 user; tens of chats; catalog of hundreds of variants; 1–3 cars per
comparison; about 8 research areas; 4 report personas; 13 criteria.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Design compliance | Pre | Post |
|---|---|---|---|---|
| I | Evidence first | Every area extraction is excerpt-validated; "insufficient data" per section minimum (FR-019); TCO items labelled sourced or assumption; status only via sourced indicators | ✅ | ✅ |
| II | Exact identity | Context-aware resolution (age → generation), generation year-range validation, aliases + de-dup, confirmation for ambiguous or used variants (R6, FR-006) | ✅ | ✅ |
| III | Deterministic computation | policy, case delta apply, criteria scoring, TCO, cost estimation and race are pure functions; LLMs interpret and explain only; number guard | ✅ | ✅ |
| IV | Provenance classes | Unchanged from the demo, plus TCO `basis`; scores are explicitly labelled as indices | ✅ | ✅ |
| V | Layered monolith | `domain/` (pure) → `application/` (services, ports) → `orchestration/` (graph, prompts) → `infrastructure/` → `api/`; import-linter enforced; UI uses only protocol DTOs | ✅ | ✅ |
| VI | Bounded, stateful, human-steered (v1.1.1: "expensive" = estimate ≥ threshold) | Persistent thread per chat, checkpointer, interrupts for variant and cost confirmation, depth-bounded rounds, per-turn caps, cancel, restart resume, hub + specialists (R2, R5, R10, R14) | ✅ | ✅ |
| VII | Provider independence | Gateway per role (`provider:model`), usage callback on all models, OpenAI default + Anthropic supported | ✅ | ✅ |
| VIII | Untrusted content | Web readers have no tools; reporters have scoped MCP tools without web access; deny-list; robots and rate limits; delimited documents | ✅ | ✅ |
| IX | Test-first core | Unit tests for every policy rule and engine before implementation; graph tests with scripted LLM; golden dialogues (replay + live) | ✅ | ✅ |
| X | YAGNI | No queue or vector DB; in-process jobs; LangGraph Store deferred; reuse demo code | ✅ | ✅ |
| XI | Research depth and quality gates | Per-section minimums, gap rounds by depth, validator role for uncertain variant matches (R8), "insufficient data", assumptions labelled | ✅ | ✅ |

**Result**: PASS (pre and post design). No violations.

## Project Structure

### Documentation (this feature)

```text
specs/002-conversational-mvp/
├── spec.md · plan.md · research.md · data-model.md · quickstart.md
├── contracts/ chat-protocol.md · rest-and-mcp.md
├── checklists/requirements.md
└── tasks.md                  (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml · uv.lock · alembic.ini · alembic/versions/
├── config/
│   ├── models.yaml        role → provider:model; prices.yaml (LLM + search prices)
│   ├── criteria.yaml      criteria dictionary v1 (R7)
│   ├── rates.yaml         TCO rates + base reserve table (R9)
│   ├── aliases.yaml       make/model/generation aliases (R6)
│   ├── sources.yaml       source typing, deny-list, fetch policy
│   ├── questions.yaml     clarification question templates
│   ├── queries.yaml       per-area search query templates (EN + ES)
│   └── severity.yaml      issue severity keyword rules
├── src/automind/
│   ├── domain/                       # pure, no I/O (mypy strict)
│   │   ├── units.py specs.py evidence.py dragrace.py      (demo, kept)
│   │   ├── metrics.py                demo metric functions (from scoring.py)
│   │   ├── casefile.py               CaseFile, CaseCar, CaseDelta, apply()
│   │   ├── policy.py                 decide() → Action (R5)
│   │   ├── criteria.py               dictionary model, weights, score() (R7)
│   │   ├── research_plan.py          areas, minimums, gaps, depth rounds (R8)
│   │   ├── tco.py                    TCO engine + reserve (R9)
│   │   ├── cost.py                   turn cost estimate (R12)
│   │   ├── identity.py               canonical key, aliases, generation-year checks (R6)
│   │   ├── reliability.py reviews.py recurrence, severity, minimums
│   │   └── report_layout.py          persona block order (FR-030)
│   ├── application/
│   │   ├── ports.py                  LLM, Search, Repos, EventBus, Clock
│   │   ├── interpret.py              LLM → Interpretation (validated)
│   │   ├── ask.py                    template questions phrased by the asker
│   │   ├── extraction.py             area schemas + extractor/validator calls
│   │   ├── resolve.py                catalog-first, context-aware resolution
│   │   ├── research.py               area workers (from demo research.py, split by area)
│   │   ├── compose.py                deterministic blocks per persona
│   │   └── usage.py                  turn budget, caps, accounting
│   ├── orchestration/
│   │   ├── state.py  graph.py  nodes/ (interpret, policy, ask, confirm, resolve, plan, research, compute, report, answer, general)
│   │   ├── agents.py                 persona reporters + answerer (create_agent + scoped MCP tools)
│   │   ├── runner.py                 per-chat turn runner, cancel, startup resume
│   │   └── prompts/*.md              versioned prompts (interpreter, asker, resolver, extractors, reporters…)
│   ├── infrastructure/
│   │   ├── config.py db/ (models, repositories) checkpoint.py llm_gateway.py usage_callback.py
│   │   ├── search_tavily.py fetch.py events.py
│   ├── mcp_server.py                 tools per contracts/rest-and-mcp.md
│   └── api/ app.py ws.py rest.py
└── tests/
    ├── unit/   graph/   golden/ (*.yaml + runner + cassettes/)   integration/   fixtures/

frontend/src/
├── lib/protocol.ts (v2 schemas) transport.ts
├── store/chat.ts case.ts
├── components/ CasePanel/ ConfirmCard.tsx ChatList.tsx CancelButton.tsx
└── components/blocks/ CriteriaScores.tsx Tco.tsx Reliability.tsx Reviews.tsx Engineering.tsx Manufacturer.tsx CaseSummary.tsx (+ demo blocks)
```

**Structure Decision**: Keep the demo's web-app layout (`backend/` + `frontend/`) and refactor
`backend/src/automind` into the constitution's five layers. Demo modules move:
- `agents/graph.py` → `orchestration/`;
- `services/*` → `application/`;
- `infra/*` → `infrastructure/`;
- `domain/scoring.py` → `domain/criteria.py` + `domain/tco.py`.

## Turn graph (reference)

```text
START → load_case → interpret (LLM) → apply_delta (code) → policy (code)
  ├─ ANSWER_GENERAL      → general (LLM, labelled) ───────────────────────────────┐
  ├─ ASK                 → ask (LLM phrases ≤3 template questions) → END (pending) │
  ├─ CONFIRM_VARIANTS    → resolve (catalog → resolver) → interrupt(variants) ─────┤→ (resume) → policy
  ├─ CONFIRM_COST        → estimate → interrupt(cost) ─────────────────────────────┤→ (resume) → policy
  ├─ RESEARCH            → plan_research → Send(job per car×area) ×N → gaps? ↺ (≤ depth rounds) → compute
  ├─ ANSWER_FROM_CONTEXT → compute → answerer (LLM + MCP tools) ───────────────────┤
  └─ REPORT              → compute → reporter_{persona} (LLM + MCP tools) ─────────┤
compute (code): criteria scores, TCO, race, blocks in persona order
→ guard (number check) → persist turn + fingerprint → END
```

## Implementation phases (input for `/speckit-tasks`)

1. **Foundation and refactor**: move demo code into the layers; Alembic baseline; the
   checkpointer; config files; ruff, mypy and import-linter green; demo tests still pass.
2. **Case file and policy (US1 core, tests first)**: `casefile.apply`, `policy.decide`,
   `identity` + aliases + de-dup, interpret prompt with golden few-shots, ask, confirm
   interrupts, persistent thread; golden G1, G2, G6 in replay mode.
3. **Research areas (US2)**: research planner, area extractors (maintenance, reviews,
   reliability, used_issues, price, manufacturer, engineering), minimums, gap rounds, jobs +
   resume, cost estimation + caps, usage callback.
4. **Criteria and persona reports (US3)**: criteria dictionary + scoring, report layout,
   reporters + answerer with scoped MCP tools, weights PATCH → recompute.
5. **TCO (US4)**, **reliability and reviews (US5)**: engines, blocks, frontend components.
6. **Race (US6)**: move the existing engine into the new compute node and blocks; simulations
   persisted.
7. **Frontend v2 and US7**: protocol v2, case panel, confirmation cards, chat list, cancel,
   usage badge, replay on reconnect.
8. **Golden dialogues live run, evaluation, polish**: G1–G7 live, reference-set evaluation,
   calibration, Docker deployment check, README and ADRs.

## Complexity Tracking

No constitution violations; nothing to justify.
