# Implementation Plan: Research Quality and Search v2

**Branch**: `003-research-quality-search-v2` | **Date**: 2026-11-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-research-quality-search-v2/spec.md`

## Summary

The research pipeline gets better input and stricter filters. Each research job (car × area × round)
now works like this:

1. **Search plan (code).** Favourite sites for the area and the user's market come first, grouped
   into `site:a OR site:b` queries. The open web follows only for areas below their minimum. Last,
   bounded AI-proposed queries run, without any page text.
2. **Search.** One cache-first `Searcher` sits over interchangeable providers: Serper by default,
   Tavily as fallback.
3. **Fetching.** Pages come from our own `PageStore`: deny-list, robots incl. Crawl-delay, rate
   limits. Main content is taken from HTML (trafilatura) and PDF (pypdf). Results are cached in
   Postgres.
4. **Relevance gate before extraction.** Deterministic variant matching, with the LLM only for
   uncertain pages. Wrong-variant pages are rejected with a reason.
5. **Reading.** Deterministic site readers handle the favourite spec sites; the LLM extractor
   handles everything else.
6. **Checks.** Unit normalisation, plausibility rules, excerpt check, then a case-aware validator
   for uncertain or conflicting claims, then the 002 selection rules.

On the conversation side the case file records **constraints**: budget, running-cost limit, usage.
A deterministic **feasibility engine** gives a verdict per car before the report. For used cars the
age range comes from a labelled depreciation estimate, refined by editorial used-price ranges from a
new `used_price` research area. The policy asks one `BUDGET_INTENT` question when needed and
replies `FEASIBILITY` before `REPORT`.

Storage moves to one Docker Postgres for development and deployment, with a one-time migration from
the embedded database, cache retention, and chat deletion with tombstones.

Details: [research.md](./research.md) R1–R16.

## Technical Context

**Language/Version**: Python 3.13 (backend, uv 0.13.6); TypeScript 5.6 strict (frontend). Unchanged.

**Primary Dependencies**:
- **Backend (existing)**: FastAPI, Pydantic v2, LangGraph 1.2, LangChain 1.4, SQLAlchemy 2 async +
  asyncpg, Alembic, httpx, langgraph-checkpoint-postgres, tavily-python (now fallback only).
- **Backend (new)**:
  - trafilatura 2.3 (Apache-2.0): main content and tables;
  - pypdf 6 (BSD-3): PDF text;
  - selectolax 1.0 (MIT): site readers;
  - Serper REST API via httpx (no SDK).
- **Frontend**: unchanged stack. Additions: chat deletion (list, multi-select, confirm), the
  feasibility block, rejected sources in the sources block, constraints in the case panel.

**Storage**: PostgreSQL 16 in Docker Compose for development and deployment. The embedded pgserver
is retired after a one-time migration. New tables: `search_cache`, `page_relevance`,
`used_price_ranges`, `site_reader_stats`, `feasibility_checks`, `deleted_chats`. `documents` is
extended into a page store. Alembic `0005_search_v2`.

**Testing**:
- pytest: unit tests for the pure domain (relevance, plausibility, feasibility, search plan), site
  readers on saved HTML fragments, cache and page store with a fake provider and local HTTP fixtures.
- Graph tests: feasibility interrupt, budget question, deletion during a turn.
- Golden dialogues G8–G11 (replay and live).
- Live eval `tests/eval/test_research_quality.py` on a benchmark of ≥ 20 cars, run once for the
  baseline (Tavily) and once for the new build.
- vitest for the new blocks and the chat list.

**Target Platform**: Linux, single user; Docker Compose; modern browsers.

**Project Type**: Web application (Python backend + React SPA), one repository.

**Performance Goals**:
- New 2-car Standard research ≤ 3 min p90 (SC-010).
- A repeat research within freshness makes 0 paid searches and 0 fetches (SC-006).
- Chat deletion ≤ 5 s including cancelling a running turn.

**Constraints**:
- Fetching per site: robots Crawl-delay is respected (ultimatespecs 30 s), ≤ 2 concurrent requests
  per host, 8 global.
- `max_pages_per_job` 8; per-turn cost cap as in 002.
- Readers run only for sites with `tos_checked` set.
- No headless browser.
- No classifieds (deny-list).

**Scale/Scope**: single user; catalog of hundreds of variants; page store of tens of thousands of
pages (≈ 50–200 MB of text) with retention.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.* Constitution v1.1.1.

| # | Principle | Design compliance | Pre | Post |
|---|---|---|---|---|
| I | Evidence first | Site-reader values carry source, excerpt (table row) and date like LLM values. Editorial used-price ranges are excerpt-validated. Depreciation estimates are labelled ASSUMPTION with their inputs. "Insufficient data" stays. | ✅ | ✅ |
| II | Exact identity | Relevance gate per (page, variant) before extraction. Readers isolate the variant's column or return `ambiguous`. The validator checks claims against the case identity (R7, R9). | ✅ | ✅ |
| III | Deterministic computation | Search plan, relevance rules, plausibility and feasibility are pure functions. LLMs only propose queries (no page text), judge uncertain relevance, extract and explain. | ✅ | ✅ |
| IV | Provenance classes | Unchanged classes. New fields: `extracted_by`, favourite flag. Feasibility numbers carry SOURCED/ASSUMPTION. | ✅ | ✅ |
| V | Layered monolith | Pure rules in `domain/`. Searcher, PageStore and readers are ports, implemented in `infrastructure/`. Orchestration uses ports only; import-linter contracts stay. | ✅ | ✅ |
| VI | Bounded, human-steered | AI follow-up queries are bounded per area and by budget. The `used_price` area is planned only when needed and counts in the cost estimate and confirmation. The feasibility verdict is a human decision point (confirm options). | ✅ | ✅ |
| VII | Provider independence | Search providers are interchangeable through config (Serper/Tavily/Parallel/Brave adapters). New LLM roles go through the gateway per role. | ✅ | ✅ |
| VIII | Untrusted content | Relevance and extraction roles are web readers without tools. The query planner never sees page text. Our fetcher enforces deny-list, robots (incl. 401/403 = disallow, Crawl-delay), rate, size, timeouts and re-checks after redirects. Provider keys stay in backend env. | ✅ | ✅ |
| IX | Test-first core | Domain unit tests and reader fixture tests before code. Golden dialogues G8–G11. Baseline and after evals on the same benchmark. | ✅ | ✅ |
| X | YAGNI | No headless browser, no vector DB, no Redis (cache in Postgres). Only 3–4 site readers. Favourites are data. | ✅ | ✅ |
| XI | Quality gates | Per-area minimums kept, `used_price` minimum added. The validation step is strengthened (plausibility + case-aware validator). | ✅ | ✅ |
| Tech constraints | Docker Compose for local development, one primary DB | This feature removes the 002 deviation (embedded dev DB). | ✅ | ✅ |

No violations; Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/003-research-quality-search-v2/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R16
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── rest-and-protocol.md   # chat deletion, feasibility block/action, sources with rejections, metrics
│   └── search-and-config.md   # Searcher/PageStore/SiteReaders ports, pure functions, config schemas
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── config/
│   ├── search.yaml                 # new: provider, fallback, locales, TTLs, limits
│   ├── sources.yaml                # + favourites
│   ├── queries.yaml                # favourite/open templates, used_price
│   ├── site_readers.yaml           # new: label → attribute maps
│   ├── plausibility.yaml           # new
│   ├── feasibility.yaml            # new: depreciation, usage thresholds, currency
│   ├── models.yaml / prices.yaml   # + query_planner, relevance; serper price
├── src/automind/
│   ├── domain/
│   │   ├── search_plan.py          # new (pure)
│   │   ├── relevance.py            # new (pure)
│   │   ├── plausibility.py         # new (pure)
│   │   ├── feasibility.py          # new (pure)
│   │   ├── casefile.py             # + constraints, feasibility_ack, set_constraints
│   │   ├── policy.py               # + BUDGET_INTENT question, FEASIBILITY action
│   │   └── research_plan.py        # + used_price area
│   ├── application/
│   │   ├── ports.py                # Searcher, PageStore, SiteReaders replace Search
│   │   ├── research.py             # job flow: plan → search → fetch → relevance → read/extract → checks
│   │   ├── extraction.py           # + used_price schema, case-aware validator, relevance role
│   │   ├── feasibility.py          # gathers car facts, persists feasibility_checks
│   │   ├── chats.py                # new: delete chats (cancel → delete → tombstone)
│   │   └── interpret.py            # + constraints with evidence check
│   ├── orchestration/
│   │   ├── nodes/feasibility.py    # new node + confirm handling
│   │   ├── graph.py                # route FEASIBILITY
│   │   └── prompts/                # query_planner.md, relevance.md; interpreter/validator updated
│   ├── infrastructure/
│   │   ├── search/                 # new package: serper.py, tavily.py, cache.py (Searcher)
│   │   ├── pages.py                # new: PageStore (fetch.py + trafilatura/pypdf + cache)
│   │   ├── fetch.py                # + Crawl-delay, redirects re-check, per-host concurrency
│   │   ├── site_readers/           # new: km77.py, ultimatespecs.py, auto_data.py (+ adac.py)
│   │   ├── retention.py            # new: periodic cleanup
│   │   └── db/                     # models + migration 0005_search_v2; repositories for new tables
│   └── api/rest.py                 # DELETE chats, metrics; 410 for deleted; PATCH constraints
├── tests/
│   ├── unit/domain/                # search_plan, relevance, plausibility, feasibility, policy additions
│   ├── unit/infrastructure/        # site readers (fixtures/html/*.html), cache keys, page store
│   ├── graph/                      # feasibility flow, budget question, delete during turn
│   ├── golden/                     # G8–G11
│   └── eval/test_research_quality.py
└── eval/research_benchmark.yaml    # ≥ 20 cars incl. ≥ 8 generation traps
frontend/src/
├── components/ChatList.tsx         # delete, multi-select, confirm
├── components/blocks/Feasibility.tsx
├── components/blocks/Sources.tsx   # rejected pages (collapsed), favourite marks
├── components/CasePanel/Constraints.tsx
└── lib/protocol.ts                 # schemas for the additions
scripts/
├── dev.sh                          # compose Postgres (dev override) + migrations + API
├── migrate-embedded.sh             # one-time embedded → Docker copy with count check
└── deploy.sh                       # unchanged interface
docker-compose.yml                  # Postgres also published on 127.0.0.1:5433 for dev and tests
```

**Structure Decision**: the existing layered monolith (002). New capabilities are added as ports and
pure domain modules; infrastructure gets a `search/` package and `site_readers/`. There are no new
services.

## Research job flow (reference)

```text
job(car, area, round)
  → search_plan.queries(area, identity, market, favourites, round)        # pure
  → Searcher.search(q)  [search_cache → serper → fallback]                 # usage: cost or cached=0
  → PageStore.get(url)  [documents cache → fetch (deny, robots, rate) → main content]
  → relevance.judge(page, target, siblings) → UNCERTAIN? → LLM relevance  # page_relevance row
  → SiteReaders.read(page) ?? extraction.extract(page)                     # READER | LLM
  → unit normalise → plausibility.check → excerpt check → [validator(case)]
  → persist claims / items → reselect → minimum_met → metrics on research_jobs
  → round < depth and below minimum → open-web queries → AI follow-up (bounded)
```

## Implementation phases (input for `/speckit-tasks`)

1. **Storage foundation (US5).**
   - Compose dev override; `dev.sh` on Docker Postgres.
   - `migrate-embedded.sh` with count check.
   - Alembic 0005 (all new tables and columns); retention task.
2. **Baseline.**
   - Benchmark list (≥ 20 cars, ≥ 8 traps).
   - Eval harness `test_research_quality.py`.
   - Run once with Tavily (cost noted).
3. **Search and pages (US2).**
   - Ports.
   - Serper and Tavily adapters behind a cache-first Searcher.
   - PageStore: fetch extensions, trafilatura and pypdf.
   - Usage with `cached`; the 002 `Search` port replaced; prices.
4. **Favourites and search plan (US1/US2).**
   - `sources.yaml` favourites; `queries.yaml` favourite and open templates.
   - Pure `search_plan`; AI follow-up role.
5. **Relevance and checks (US1).**
   - Pure `relevance` with generation-trap tests; LLM relevance for uncertain pages.
   - `plausibility`; case-aware validator; claim statuses and reasons; metrics on jobs.
6. **Site readers (US1).**
   - km77, ultimatespecs, auto-data (+ adac) with fixtures; label maps; stats.
   - Fallback to the LLM extractor.
7. **Feasibility (US3).**
   - Case constraints and interpreter evidence rule.
   - Pure `feasibility` with depreciation.
   - `used_price` area and schema.
   - Policy (`BUDGET_INTENT`, `FEASIBILITY`), node and confirm options.
   - Block, case panel; golden G8–G11.
8. **Chat deletion (US4).**
   - Application service, REST, WS tombstone, checkpoint thread delete.
   - Frontend list/multi-select/confirm.
9. **UI for sources and metrics.**
   - Rejected sources and favourite marks; metrics endpoint.
10. **Validation.**
    - Eval run (SC-001..SC-006, SC-010); golden live; quickstart; ADRs: search provider, page
      store and readers, feasibility; README.

## Complexity Tracking

None. The Constitution Check has no violations.
