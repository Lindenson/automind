# Concept Demo (mini-MVP): scope

**Goal**: demonstrate the AutoMind concept end to end in one day. A chat with the hub agent
compares 2–3 cars; the hub reuses the cache or runs a research loop (search → extract →
validate → store); analyst agents use deterministic MCP tools (metrics, drag race, profile
scores); and the answer appears in a browser as text plus visual blocks.

This is a **spike**: it follows constitution v1.1.0, but skips the full Spec Kit cycle. The full
MVP is re-specified from `docs/vision.md` afterwards, and demo code is reused where it fits.

## In scope

| Area | Demo version |
|---|---|
| Chat | Browser chat page ⇄ WebSocket ⇄ FastAPI; streamed status events and final answer |
| Hub agent | LangGraph: understand request (cars, profile) → cache check → research if needed → analyst → answer with blocks |
| Research | Per car: web search (Tavily) → page text → LLM extraction (web reader, **no tools**) of Tier 1 specs + official ES price + maintenance interval if found → **excerpt validator** → store |
| Cache | Variants, specs, and evidence stored in DB with timestamps; freshness per category (config); reused on repeat questions |
| MCP tools | Python MCP server (stdio): `get_cached_vehicle`, `compute_metrics`, `simulate_drag_race` (v0.1, ICE/BEV/hybrid), `score_profiles` (performance / smart buyer / tech, configurable weights), `maintenance_cost_estimate` (assumption-labeled) |
| Analyst | Profile/comparison agent that calls MCP tools (scoped) and writes the conclusion; numbers only from tool results |
| UI blocks | `spec_table`, `metric_bars`, `race_chart` (speed vs time), `profile_scores`, `sources`; provenance and confidence badges |
| Providers | LLM via gateway (Anthropic or OpenAI from `.env`); **fixture mode** (recorded search and LLM outputs) runs with no keys |

## Out of scope for the demo

Plan-approval dialog (hub states the resolved variants and proceeds), conflict follow-up loops,
depth levels, reviews and reliability research, manufacturer section, restart recovery,
cancellation, history UI, Alembic migrations, full React build (see "Frontend" below), Docker.

## Technical shortcuts (documented deviations)

- **Database**: a local PostgreSQL cluster in `./.pgdata` (no Docker). Tables are created at
  startup with SQLAlchemy `create_all`.
- **Frontend**: a single-page React + TypeScript app built with Vite if Node.js is available.
  Otherwise a static page served by FastAPI (React from CDN) as a temporary fallback.
- **Checkpointer**: LangGraph `MemorySaver` (Postgres checkpointer in the full MVP).

## Demo script

1. "Compare VW Golf GTI Mk8 and Hyundai i30 N for a race enthusiast."
   - The hub resolves the variants and researches both live (status messages stream in).
   - The answer shows the spec table with sources, metrics, the drag race chart, profile scores,
     and the conclusion.
2. "And for a smart buyer?"
   - The answer comes from the cache (no new search) with smart-buyer scores and a maintenance
     estimate labeled "assumption".
3. "Add the Tesla Model 3 Performance."
   - Only the Tesla is researched, and the comparison and race are redone for 3 cars.
