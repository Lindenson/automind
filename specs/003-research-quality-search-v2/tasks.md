---

description: "Task list for 003-research-quality-search-v2 (research quality and search v2)"
---

# Tasks: Research Quality and Search v2

**Input**: `/specs/003-research-quality-search-v2/` (plan.md, spec.md, research.md R1–R16,
data-model.md, contracts/rest-and-protocol.md, contracts/search-and-config.md, quickstart.md)

**Tests**: Included. Constitution IX requires tests before code for pure rules. The success criteria
need golden dialogues and a before/after eval. Pure-rule tests are written first and must fail before
the implementation.

**Starting point**: the 002 build (branch `002-conversational-mvp`, 199 tests passing).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on incomplete tasks)
- **[Story]**: US1…US5 from spec.md
- Backend paths are relative to `backend/`, frontend paths to `frontend/`, scripts to the repo root

**Story order note**: US2 (search and pages) comes before US1 (reliable data) although both are P1.
US1's relevance gate and site readers work on pages from US2's `PageStore`.

---

## Phase 1: Setup

**Purpose**: Dependencies, configuration skeletons and keys.

- [ ] T001 Add dependencies with `uv add` in `backend/`: `trafilatura>=2.3,<3`, `pypdf>=6,<7`, `selectolax>=1.0,<2`; commit `uv.lock`; run `scripts/check.sh`
- [ ] T002 [P] Add `SERPER_API_KEY=`, `SERPAPI_API_KEY=` (and the commented `PARALLEL_API_KEY`) to `.env.example`. Add `serper_api_key: str | None`, `serpapi_api_key: str | None` and `search_provider: str | None` (env override of `config/search.yaml`) to `src/automind/config.py`. Report key presence (booleans only) in `/api/v1/health` `search.keys`
- [ ] T003 [P] Create `config/search.yaml` exactly as in contracts/search-and-config.md (provider `serper` | `serpapi` | `tavily`, default `serper`, fallback `[tavily]`, `num: 10`, `cache_ttl_days {default: 7, price: 3}`, markets ES/EN/DE → gl/hl, `ai_followup {max_queries_per_area: 3, depths: [DEEP, STANDARD]}`, `limits {max_pages_per_job: 8, max_fetch_bytes_per_turn: 40000000}`). Add a loader `search_config()` in `src/automind/infrastructure/config.py` with validation (unknown provider → error at start)
- [ ] T004 [P] Add the `favourites:` section to `config/sources.yaml` with the initial list from research.md R5. Each entry has `domain`, `source_type` ∈ {MANUFACTURER, INSTRUMENTED_TEST, SPEC_DATABASE, PUBLICATION, ENCYCLOPEDIA}, `areas`, `markets` ⊆ {ES, EN, DE, ANY}, `priority` 1–3, `reader` (km77 | ultimatespecs | auto_data | adac | null) and `tos_checked: null`. Extend the `SourcePolicy` loader so a favourite on the deny-list fails at start
- [ ] T005 [P] Reshape `config/queries.yaml`: each area gets `favourite: "<template with {sites}>"` and `open: [...]` (the existing templates), plus the new area `used_price` (templates from contracts/search-and-config.md). Update the loader in `infrastructure/config.py` and the `Reference.queries` type in `application/ports.py`
- [ ] T006 [P] Create `config/plausibility.yaml` and `config/feasibility.yaml` with the starting values from contracts/search-and-config.md, plus loaders `plausibility_rules()` and `feasibility_rules()`. Add `serper` search prices (`search.providers.serper.per_query_eur`, verified on serper.dev and dated in a comment) to `config/prices.yaml`. Add roles `query_planner` and `relevance` (`openai:gpt-5.4-mini`) to `config/models.yaml`

---

## Phase 2: Foundational (blocking)

**Purpose**: Schema, ports and the baseline measurement. No story work starts before this phase ends.

- [ ] T007 Alembic migration `src/automind/infrastructure/db/migrations/versions/0005_search_v2.py` and models in `db/models.py`, exactly per data-model.md:
  - **new tables**: `search_cache`, `page_relevance`, `used_price_ranges`, `site_reader_stats`, `feasibility_checks`, `deleted_chats`;
  - **`documents`**: + `url_hash char(64) unique`, `final_url`, `status varchar(16)` (`OK|NO_CONTENT|REFUSED|ERROR`), `fail_reason`, `content_type varchar(60)`, `reader varchar(40)`, `fetched_at`, `expires_at` (indexed), `bytes int`. Backfill `url_hash` from `url` and `expires_at = retrieved_at + 365 days`. Replace the unique constraint on `content_sha256` with a plain index;
  - **`claims`**: + `reject_rule varchar(40)`, `extracted_by varchar(12)` (`READER|LLM`, default `LLM`);
  - **`evidence`**: + `favourite bool default false`, `favourite_priority smallint`;
  - **`research_jobs`**: + `queries jsonb`, `pages_found int`, `pages_cached int`, `pages_rejected jsonb`, `values_rejected jsonb`, `reader_values int`, `search_cost_eur numeric(10,4)`;
  - **`search_calls`**: + `cached bool default false`.

  Test: `tests/integration/test_migrations.py` upgrade/downgrade on `automind_mig`.
- [ ] T008 [P] Ports in `src/automind/application/ports.py` per contracts/search-and-config.md:
  - new: `SearchHit`, `SearchProvider`, `Searcher`, `Page`, `PageStore`, `SiteReading`, `SiteReaders`;
  - `Ports` gets `searcher`, `pages` and `readers` in place of `search`.

  Keep a temporary adapter so 002 code paths still work until T021.
- [ ] T009 [P] Test fakes: `tests/fakes/fixture_search.py` becomes a `FakeSearcher` (fixtures keyed by query substring, records calls and `cached`). Add `tests/fakes/fake_pages.py` (`FakePageStore` serving HTML/text fixtures from `tests/fixtures/pages/`) and `tests/fakes/fake_readers.py`. Update `tests/graph/conftest.py::make_ports`
- [ ] T010 Benchmark list `eval/research_benchmark.yaml`:
  - ≥ 20 cars built in the last 15 years and sold in Spain, each with make, model, generation, variant, years, market and expected critical attributes (source to be filled when sourced);
  - ≥ 8 generation traps: Prado J150/J250, Golf Mk7/Mk8, BMW 3 Series F30/G20, BMW 5 Series G30/G60, E-Class W212/W213, Octavia Mk3/Mk4, RAV4 XA40/XA50, Civic FK/FL.
- [ ] T011 Eval harness `tests/eval/test_research_quality.py` (marker `live`):
  - runs a new Standard research for each benchmark car in an isolated DB schema or fresh catalog;
  - computes per area: minimum-met share; pages found, cached and rejected by reason; values accepted and rejected by reason; reader share; search and fetch cost; LLM cost; cost per accepted value; wrong-variant values in selected values; duration;
  - writes `eval/out/<provider>-<date>.json` and a markdown summary;
  - respects `SEARCH_PROVIDER` env.
- [ ] T012 Run the baseline: `SEARCH_PROVIDER=tavily uv run pytest tests/eval/test_research_quality.py -m live -s` on the 002 search path. Record the result in `specs/003-research-quality-search-v2/checklists/baseline.md` (numbers and cost). **Ask the user before running** (estimated several euros)

**Checkpoint**: schema, ports and baseline ready.

---

## Phase 3: User Story 2 — Search that costs less and is not paid twice (P1)

**Goal**: cache-first search over interchangeable providers, own fetching and main-content
extraction, usage with cache hits, a code-built search plan with favourites first, bounded AI
follow-up.

**Independent Test**: repeat the same research → 0 paid searches and 0 fetches (SC-006); provider
switch by config; fallback when Serper fails; deny-listed and robots-forbidden URLs never fetched.

### Tests first (US2)

- [ ] T013 [P] [US2] `tests/unit/domain/test_search_plan.py` covers `domain/search_plan.queries(area, identity, market, favourites, templates, round)`:
  - round 0 → favourite groups of ≤ 4 sites, ordered by priority, filtered by area and market (ANY matches all), `{sites}` rendered as `site:a OR site:b`;
  - round ≥ 1 → open templates;
  - deny-listed favourites never appear;
  - market locale gl/hl from config;
  - no duplicate queries.
- [ ] T014 [P] [US2] `tests/unit/infrastructure/test_search_cache.py` covers the cache key: normalisation (lowercase, collapsed spaces, sorted `site:` group), the same key for equivalent queries, expiry by area TTL, and a cache hit returning stored hits with `cached=True` and cost 0
- [ ] T015 [P] [US2] `tests/unit/infrastructure/test_fetch_policy.py` covers the fetcher against a local `httpx.MockTransport`:
  - robots `Crawl-delay` respected (second request delayed);
  - robots 401/403 → disallow all;
  - a redirect to a deny-listed host is refused;
  - ≤ 2 concurrent requests per host;
  - size limit;
  - content-type limit.
- [ ] T016 [P] [US2] `tests/unit/infrastructure/test_page_store.py` covers the page store:
  - HTML main content keeps tables as markdown (trafilatura) on fixture pages in `tests/fixtures/pages/`;
  - PDF text (pypdf) on a small fixture PDF;
  - < 400 chars → `NO_CONTENT`;
  - second `get` within `expires_at` makes no request;
  - refused URL stored with `status=REFUSED` and reason.

### Implementation (US2)

- [ ] T017 [P] [US2] Pure `src/automind/domain/search_plan.py` (`PlannedQuery {text, kind: FAVOURITE|OPEN|AI, area, market, sites}`) passing T013
- [ ] T018 [P] [US2] Providers in `src/automind/infrastructure/search/`:
  - `serper.py`: `POST https://google.serper.dev/search` with `X-API-KEY`, body `{q, gl, hl, num}`, maps `organic[]` → `SearchHit`, timeout, raises `SearchUnavailable` on 401/402/429/5xx;
  - `serpapi.py` (serpapi.com, a different company from Serper): `GET https://serpapi.com/search.json` with `engine=google`, `q`, `gl`, `hl`, `num`, `api_key`, maps `organic_results[]` → `SearchHit`, same error mapping;
  - `tavily.py`: the 002 client reduced to search only, mapped to `SearchHit`.

  Test both on recorded JSON fixtures.
- [ ] T019 [US2] `src/automind/infrastructure/search/cache.py`: `CachedSearcher` implements `Searcher`:
  - `search_cache` lookup;
  - primary provider, then the fallback list;
  - deny-list filter;
  - store with `expires_at`;
  - usage through `TurnBudget.before_search/after_search` with the provider price;
  - `search_calls` row with `provider`, `cached`, `area`, `job_id`.

  Passes T014.
- [ ] T020 [US2] Fetcher and page store:
  - extend `src/automind/infrastructure/fetch.py`:
    - Crawl-delay from robots (max with config interval);
    - robots 401/403 = disallow;
    - redirects ≤ 5 with deny/robots re-check of the final URL;
    - per-host semaphore 2, global 8.
  - new `src/automind/infrastructure/pages.py` (`DbPageStore`):
    - `documents` lookup by `url_hash`;
    - fetch;
    - trafilatura `extract(include_tables=True, output_format="markdown")` with fallback to `html_to_text`;
    - pypdf for PDFs (first 30 pages);
    - `NO_CONTENT` < 400 chars;
    - store `status`, `reader`, `expires_at` from the area freshness;
    - keep raw HTML in memory for readers only.

  Passes T015 and T016.
- [ ] T021 [US2] Rewire `src/automind/application/research.py`:
  - `queries_for` → `search_plan.queries`;
  - `_collect` → `Searcher.search` then `PageStore.get` with `max_pages_per_job`, dropping `NO_CONTENT/REFUSED` with reasons counted;
  - remove `fill_full_text` and the old `Search` port adapter from T008;
  - pasted URLs (`resolve.py`) use `PageStore.get`;
  - record `queries`, `pages_found`, `pages_cached`, `search_cost_eur` on `research_jobs`.
- [ ] T022 [US2] Open-web and AI follow-up rounds in `application/research.py`:
  - round 1 runs open-web queries for areas below their minimum;
  - round 2 (DEEP, or STANDARD with budget left) runs role `query_planner` with a new prompt `orchestration/prompts/query_planner.md`:
    - inputs: variant identity, area, missing attributes, tried queries;
    - **no page text**;
    - structured output `{queries: [str] ≤ 3}`.
  - code drops queries mentioning deny-listed domains, longer than 200 chars, or repeated, and checks the budget before running them.

  Graph test in `tests/graph/test_research_flow.py`.
- [ ] T023 [US2] Composition in `src/automind/infrastructure/adapters.py::live_ports`:
  - `CachedSearcher` from `config/search.yaml`, with the `SEARCH_PROVIDER` env override;
  - `DbPageStore`;
  - readers registry (empty until US1).

  The cost estimator (`LiveEstimator`) uses the provider price and expected cache hits. Update graph tests and golden replays to the new fakes; all existing tests green.
- [ ] T024 [US2] Graph test `tests/graph/test_search_cache.py`:
  - the same 1-car research in two chats → the second turn has `search_calls` rows only with `cached=true` and no fetches (SC-006);
  - primary provider raising `SearchUnavailable` → fallback used;
  - both failing → areas marked "search unavailable", turn DONE.

**Checkpoint**: research runs on Serper with our own pages; repeat research is free.

---

## Phase 4: User Story 1 — Reliable data for the exact car (P1) 🎯 MVP

**Goal**: relevance gate before extraction, deterministic site readers, plausibility, case-aware
validator, rejection reasons visible, per-area metrics.

**Independent Test**: benchmark research. SC-001 ≥ 80% of areas meet their minimum; SC-004 zero
wrong-variant values and ≥ 95% wrong-variant pages rejected; SC-005 ≥ 90% of favourite spec pages
read without AI.

### Tests first (US1)

- [ ] T025 [P] [US1] `tests/unit/domain/test_relevance.py` covers `domain/relevance.judge`:
  - generation traps: a J250 page for a J150 target → `OTHER_VARIANT("J250 …")`; Mk8 for Mk7; G20 for F30; W213 for W212; G60 for G30;
  - years outside the generation → `OTHER_VARIANT`;
  - engine signature mismatch (power ±5%, displacement, fuel) → `OTHER_VARIANT`;
  - a multi-engine table page → `MULTI_VARIANT`;
  - no make/model → `NOT_ABOUT_CAR`;
  - conflicting or absent signals → `UNCERTAIN`;
  - property test (hypothesis): verdicts are deterministic.
- [ ] T026 [P] [US1] `tests/unit/domain/test_plausibility.py` covers `domain/plausibility.check` with the ranges from `config/plausibility.yaml`:
  - 0–100 of 1.9 s for an ICE diesel saloon → rejected (`measured_0_100.ICE`);
  - curb mass of 150 kg → rejected;
  - power-to-weight > 1 kW/kg → rejected (`pw_ratio`);
  - normal values pass;
  - units are normalised before checking.
- [ ] T027 [P] [US1] Site reader fixtures:
  - save trimmed table fragments of real pages in `tests/fixtures/html/` (`km77_bmw_520d_g30.html`, `ultimatespecs_bmw_g30_520d.html`, `auto_data_bmw_g30_520d.html`, and a multi-engine page for each). Fetch them once with our fetcher; keep only the spec tables and the title.
  - tests in `tests/unit/infrastructure/test_site_readers.py`:
    - expected rows (attribute, raw value, unit, excerpt = row text) for power, torque, curb mass, length/width/height, wheelbase, boot, claimed 0–100, top speed, consumption;
    - multi-engine page with the right column isolated, otherwise `ambiguous=True`;
    - unknown layout → `None`.

### Implementation (US1)

- [ ] T028 [P] [US1] Pure `src/automind/domain/relevance.py` (`PageFacts`, `Relevance {verdict, other, reason}`), using the generation info from `config/generations.yaml` and the existing `_mentions` / `_sibling_code` helpers moved from `domain/evidence.py`. Passes T025
- [ ] T029 [P] [US1] Pure `src/automind/domain/plausibility.py` (`PlausibilityResult {ok, rule_id, message}`; rules injected), passing T026
- [ ] T030 [US1] LLM relevance for `UNCERTAIN` pages:
  - role `relevance` (web reader, no tools);
  - prompt `orchestration/prompts/relevance.md`;
  - input: case identity + ≤ 3,000 chars of the page;
  - structured `{verdict, other, reason}`.

  Persist every verdict in `page_relevance` (method `RULES|LLM`). In `application/research.py`, only `RELEVANT` pages and the isolated parts of `MULTI_VARIANT` pages go on to reading. Rejections are counted by reason into `research_jobs.pages_rejected`
- [ ] T031 [US1] Site readers in `src/automind/infrastructure/site_readers/`: `km77.py`, `ultimatespecs.py`, `auto_data.py`, a registry in `__init__.py` keyed by domain, and label maps in `config/site_readers.yaml`. A reader runs only when the favourite's `tos_checked` is set. Count `ok/failed/ambiguous` per domain per day in `site_reader_stats`. Passes T027
- [ ] T032 [US1] Reading path in `application/research.py`:
  - `SiteReaders.read(page, target)`, falling back to `extraction.extract` (LLM) when it returns `None`;
  - reader rows become claims with `extracted_by=READER`, the excerpt being the row text;
  - then unit normalisation, `plausibility.check` (reject → `REJECTED_IMPLAUSIBLE` with `reject_rule`), the excerpt check and selection (002 rules);
  - mark `evidence.favourite` and `favourite_priority`.
- [ ] T033 [US1] Case-aware validator:
  - `extraction.validate_claims` gets the case identity (make, model, generation, years, engine/trim, body, market, condition, user's year);
  - verdicts `SAME_VARIANT | OTHER_VARIANT | OTHER_MARKET | OTHER_YEAR | UNSUPPORTED` map to the claim statuses `REJECTED_OTHER_VARIANT | REJECTED_OTHER_MARKET | REJECTED_OTHER_YEAR`;
  - it runs for `MULTI_VARIANT`/`UNCERTAIN` pages and for claims that disagree with an already selected value beyond tolerance;
  - update `orchestration/prompts/validator.md`.

  Graph test: a page whose power is true for another market is rejected.
- [ ] T034 [US1] Per-area metrics on `research_jobs` (`pages_rejected`, `values_rejected` by reason, `reader_values`) and the REST endpoint `GET /api/v1/research/metrics?days=7` in `src/automind/api/rest.py`, as in contracts/rest-and-protocol.md. Add a test
- [ ] T035 [US1] Sources with reasons:
  - `compose.py` builds `SourceRef` with `favourite`, `extracted_by` and `rejected {reason, other}`; the sources block lists accepted sources first, then rejected pages for this turn's cars;
  - frontend: extend `SourceRefSchema` in `src/lib/protocol.ts`; in `src/components/blocks/Sources.tsx` mark favourites, show "read from table" for READER, and a collapsed "Rejected pages (n)" list with reasons;
  - vitest for the schema.
- [ ] T036 [US1] Golden dialogue update: G1–G7 replay fixtures re-recorded for the new pipeline (FakeSearcher/FakePageStore). Live run of G1–G7 green
- [ ] T037 [US1] Run the eval (`uv run pytest tests/eval/test_research_quality.py -m live -s`, default provider) and compare with the baseline in `checklists/baseline.md`: SC-001, SC-002, SC-003, SC-004, SC-005, SC-010. Record the results in `checklists/validation.md`. **Ask the user before running**

**Checkpoint**: data quality measurably better than the baseline. This is the MVP of 003.

---

## Phase 5: User Story 3 — Honest answer when the request does not fit (P2)

**Goal**: constraints in the case, deterministic feasibility with the used-price estimate (Q1 = C),
a budget-intent question, the FEASIBILITY action before the report.

**Independent Test**: golden G8–G11 → 100% verdict or one question before any report (SC-007,
SC-007a).

### Tests first (US3)

- [ ] T038 [P] [US3] `tests/unit/domain/test_casefile_constraints.py`:
  - `CaseDelta.set_constraints` merges partially;
  - amounts must be > 0 and currency ∈ {EUR, GBP, USD, null};
  - `intent` ∈ {NEW, USED, ANY, UNKNOWN} and `kind` ∈ {TOTAL, MONTHLY};
  - the fingerprint changes when constraints change;
  - `feasibility_ack` is reset when constraints change.
- [ ] T039 [P] [US3] `tests/unit/domain/test_feasibility.py` covers `domain/feasibility.evaluate`:
  - **budget**:
    - new price ≤ budget → FITS;
    - new price > budget, intent NEW → DOES_NOT_FIT;
    - intent ANY/USED → USED_ONLY with an age range from the depreciation curve (labelled ASSUMPTION, inputs shown);
    - an editorial range present → it decides, and both are shown when they disagree;
    - no price → UNKNOWN(missing: official price).
  - **running cost**: TCO per month vs the limit, with the TCO assumptions carried.
  - **usage space**: passengers × luggage threshold vs boot litres and seats.
  - **usage power**: kW/t vs the mountains/towing thresholds.
  - **usage range**: BEV `daily_km × margin` vs range.
  - **general**: every number carries basis and sources; deterministic.
- [ ] T040 [P] [US3] `tests/unit/domain/test_policy_feasibility.py` covers `decide`:
  - budget with intent UNKNOWN where new and used verdicts would differ → `ASK [BUDGET_INTENT]` (still ≤ 3 questions, one round, not re-asked once in `asked`);
  - after research, any non-FITS verdict without a matching `feasibility_ack` → `FEASIBILITY`;
  - with the ack → `REPORT`;
  - all FITS → `REPORT`;
  - `used_price` is planned in `research_plan` only when a budget is set and (the new price does not fit or the condition is USED).

### Implementation (US3)

- [ ] T041 [US3] `domain/casefile.py`:
  - `Constraints` model (budget, running_cost_limit, usage, evidence), `feasibility_ack`;
  - `CaseDelta.set_constraints` and `constraints_evidence`;
  - `fingerprint` includes constraints;
  - question kinds `BUDGET_INTENT`, `BUDGET_CURRENCY`, `BUDGET_KIND` with templates in `config/questions.yaml` (ru/es/en).

  Passes T038.
- [ ] T042 [US3] Interpreter: update `orchestration/prompts/interpreter.md` and `application/interpret.py` to fill `set_constraints`. Code drops any number not present verbatim (after number normalisation) in `constraints_evidence` from the current message, the same as `persona_evidence`. Graph test: a budget from an earlier message is not re-derived
- [ ] T043 [P] [US3] Pure `src/automind/domain/feasibility.py` (`CarFacts` for feasibility, `CheckResult`, `CarFeasibility`, depreciation from rules). Passes T039
- [ ] T044 [US3] `used_price` research area:
  - `research_plan.AREAS` + freshness 30 days + minimum (≥ 1 accepted editorial range for the model years);
  - extraction schema `UsedPriceItems {ranges: [{model_year_from, model_year_to, min, max, currency, market, quoted_on, excerpt}]}` with an extractor prompt section;
  - persist into `used_price_ranges` (GBP/USD → EUR via `feasibility.yaml` rates, labelled);
  - deny-list enforced.

  Unit test for normalisation, graph test with fixture pages.
- [ ] T045 [US3] Policy and graph:
  - extend `domain/policy.decide` and pass T040;
  - new node `orchestration/nodes/feasibility.py`: gathers facts (`application/feasibility.py`), evaluates, persists `feasibility_checks`, builds the `feasibility` block, emits `confirm_request kind:"feasibility"` with options `report|used|alternatives`;
  - on resume: `report` → store `feasibility_ack` → REPORT; `used` → set the condition to USED for cars over budget, then re-assess; `alternatives` → answerer suggests cars of a fitting class, labelled as suggestions, no numbers without data;
  - route in `orchestration/graph.py`;
  - fixed phrases in `orchestration/phrases.py` (ru/es/en).
- [ ] T046 [US3] Frontend:
  - `FeasibilityBlockSchema` in `src/lib/protocol.ts`;
  - `src/components/blocks/Feasibility.tsx`: verdict per car and check, numbers compared with basis badges, used age range with EDITORIAL/ASSUMPTION;
  - `ConfirmCard` handles `kind: "feasibility"`;
  - `src/components/CasePanel/Constraints.tsx` (view/edit budget, running-cost limit, usage) via `PATCH /api/v1/chats/{id}/case`;
  - backend PATCH validation;
  - vitest.
- [ ] T047 [US3] Golden dialogues G8–G11 as in quickstart.md §4 (`tests/golden/dialogues/g08_budget_new_infeasible.yaml` … `g11_budget_intent_question.yaml`), replay fixtures plus a live run. Assert: no REPORT before a verdict or question; the verdict carries numbers; a used age range is present with its basis; zero values from classifieds

**Checkpoint**: impossible requests are named, not silently reported.

---

## Phase 6: User Story 4 — Delete old chats (P2)

**Goal**: delete one or many chats; chat-scoped data removed; shared knowledge kept; tombstones.

**Independent Test**: quickstart.md §5 (SC-008).

- [ ] T048 [P] [US4] Test `tests/graph/test_delete_chat.py`:
  - deleting a chat with a finished research removes all rows with its `chat_id` from `chat_messages`, `case_files`, `turn_events`, `turns`, `research_jobs`, `llm_calls`, `search_calls`, `feasibility_checks`, `chats`, and the checkpoint thread;
  - `vehicle_variants`, `documents`, `evidence`, `claims`, `spec_values` and `research_runs` counts are unchanged;
  - deleting during a running turn cancels it first;
  - deleting during a turn waiting for confirmation works;
  - idempotent;
  - a tombstone row exists;
  - a new chat about the same car → no searches (cache and freshness).
- [ ] T049 [US4] `src/automind/application/chats.py::delete_chats(ids)`:
  - `runner.cancel` and wait ≤ 5 s;
  - one transaction deleting the chat-scoped tables;
  - `AsyncPostgresSaver.adelete_thread(chat_id)` through a port method `Checkpoints.delete_thread`;
  - insert `deleted_chats {chat_id, deleted_at, counts}`.

  Passes T048.
- [ ] T050 [US4] API:
  - `DELETE /api/v1/chats/{id}` and `POST /api/v1/chats/delete {ids: 1..100}`;
  - `410 {code: "chat_deleted"}` from messages/case for tombstoned chats;
  - WebSocket `hello` on a tombstoned chat → `error {code: "chat_deleted"}` and close (`api/ws.py`);
  - contract tests in `tests/api/test_chats_delete.py`.
- [ ] T051 [US4] Frontend `src/components/ChatList.tsx`:
  - delete button per chat;
  - multi-select mode with "Delete selected (n)";
  - confirm dialog naming the count;
  - optimistic removal with rollback on error;
  - clear the sessionStorage `last_seq` of deleted chats;
  - when the current chat is deleted → new chat;
  - deleted-chat screen on `chat_deleted`;
  - vitest for the store logic.

**Checkpoint**: the chat list can be cleaned; research knowledge survives.

---

## Phase 7: User Story 5 — One database for development and deployment (P3)

**Goal**: Docker Postgres for development and deployment, one-time migration of the embedded data,
retention.

**Independent Test**: quickstart.md §1 (SC-009); retention removes only expired, unreferenced cache
entries.

**Prerequisite**: this session can reach the Docker daemon (re-login after joining the `docker`
group).

- [ ] T052 [P] [US5] `docker-compose.dev.yml` override: publishes `postgres` on `127.0.0.1:${AUTOMIND_DB_PORT:-5433}:5432` and reads `POSTGRES_PASSWORD` from `.env.docker`. Rewrite `scripts/dev.sh`:
  - `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres`;
  - wait for health;
  - export `DATABASE_URL=postgresql+asyncpg://automind:…@127.0.0.1:5433/automind`;
  - migrate;
  - start the API on :8000.

  Share the `.env.docker` creation with `scripts/deploy.sh` through `scripts/lib/env.sh`.
- [ ] T053 [US5] `scripts/migrate-embedded.sh`:
  - start the embedded server (`.pgdata/pg`);
  - `pg_dump --format=custom` of `automind` with pgserver's pg_dump;
  - stop the API if running (refuse otherwise);
  - start the compose Postgres;
  - `pg_restore --clean --if-exists --no-owner`;
  - compare `count(*)` of every table (domain + checkpoint tables) before and after;
  - exit non-zero on any mismatch;
  - print a summary;
  - keep `.pgdata/` untouched (the operator deletes it later).

  Dry-run flag `--check`.
- [ ] T054 [US5] Retention `src/automind/infrastructure/retention.py`:
  - delete `search_cache` rows with `expires_at < now()`;
  - delete `documents` with `expires_at < now()` and no `evidence.document_id` reference;
  - delete `page_relevance` rows of deleted documents;
  - delete `site_reader_stats` older than 180 days;
  - runs in the API lifespan at start and every 24 h as an asyncio task, logging counts.

  Test `tests/integration/test_retention.py`.
- [ ] T055 [US5] Tests run against the compose Postgres: the test settings read `TEST_DATABASE_URL` (default `…:5433/automind_test`), created by `scripts/dev.sh`. `scripts/check.sh` starts Postgres via compose when not running. Retire `scripts/db.sh` and pgserver from the dev dependencies after T053 succeeds. Update the README
- [ ] T056 [US5] Run the migration on this machine (`scripts/migrate-embedded.sh`), open old chats in the UI, run `scripts/deploy.sh` (build, health), and record the results in `checklists/validation.md`

**Checkpoint**: one database setup everywhere.

---

## Phase 8: Polish & Cross-Cutting

- [ ] T057 [P] ADRs in `docs/adr/`:
  - ADR-017: search provider port and Serper;
  - ADR-018: own page store, readers and the relevance gate;
  - ADR-019: feasibility engine and the used-price estimate (Q1 = C);
  - ADR-020: one Docker Postgres for development.

  Update `docs/adr/README.md`.
- [ ] T058 [P] README: the search provider and keys, favourites and `tos_checked`, the metrics endpoint, chat deletion, the new dev flow, eval commands
- [ ] T059 [P] Cost estimator calibration: per-area averages in `LiveEstimator` from the new `research_jobs` and `search_calls` (Serper price, cache share), so cost confirmations match reality (±30% on the eval run)
- [ ] T060 Full quickstart run (§0–§6) and `scripts/check.sh` green. Update `checklists/validation.md` with each SC result (met / not met with numbers) and the open items
- [ ] T061 Memory update (`automind-project.md`): 003 state, provider choice, open items

---

## Dependencies & Execution Order

- **Setup (T001–T006)** → **Foundational (T007–T012)** → stories.
- **US2 (T013–T024)** must finish before **US1 (T025–T037)**: US1 needs the page store and searcher.
- **US3 (T038–T047)** depends on Foundational and on US2 for the `used_price` research; its pure parts (T038–T041, T043) can start right after Foundational.
- **US4 (T048–T051)** depends only on Foundational (T007 for tombstones) and can run in parallel with US1–US3.
- **US5 (T052–T056)** depends on Docker access; T052–T055 can start any time after Foundational. **T012 (baseline) should run before T053** so the baseline uses the same data as before, or after a fresh catalog — the eval harness isolates its catalog either way.
- **Polish** after the stories it documents.

### Parallel opportunities

- Setup: T002–T006 together.
- Foundational: T008 and T009 together after T007; T010 in parallel with T007–T009.
- US2: tests T013–T016 together, then T017 and T018 together.
- US1: tests T025–T027 together, then T028, T029 and T031 together.
- US3: T038–T040 together, then T043 in parallel with T041–T042.
- US4 as a whole in parallel with US1/US3 (different files: `application/chats.py`, `api/`, `ChatList.tsx`).
- US5 T052 and T054 in parallel.

### Parallel example (US1)

```text
Task: "T025 relevance tests in tests/unit/domain/test_relevance.py"
Task: "T026 plausibility tests in tests/unit/domain/test_plausibility.py"
Task: "T027 site reader fixtures and tests in tests/unit/infrastructure/test_site_readers.py"
→ then
Task: "T028 domain/relevance.py"   Task: "T029 domain/plausibility.py"   Task: "T031 site_readers/*"
```

## Implementation Strategy

1. **MVP = Setup + Foundational + US2 + US1.** This gives better data at lower cost, proven by the
   eval against the baseline (T037). Stop and review the numbers with the user.
2. **Then US3** (feasibility), the second most visible failure.
3. **US4** (deletion) can ship any time; it is small and independent.
4. **US5** as soon as Docker access is available; T053 is a one-time, verified copy.
5. Live runs that cost money (T012, T037, T047 live, T056) are announced with an estimate before
   running.
