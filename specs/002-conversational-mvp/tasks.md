---

description: "Task list for 002-conversational-mvp (AutoMind conversational MVP)"
---

# Tasks: AutoMind Conversational MVP

**Input**: `/specs/002-conversational-mvp/` (plan.md, spec.md, research.md, data-model.md,
contracts/chat-protocol.md, contracts/rest-and-mcp.md, quickstart.md)

**Tests**: Included. Constitution IX requires tests first for pure rules. FR-046 / SC-001
require golden dialogues. Tests for pure rules are written before their implementation.

**Starting point**: the concept-demo code in `backend/` and `frontend/`, which works and has 22
tests passing. Phase 1 refactors it into the plan's layers without changing behaviour.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on incomplete tasks)
- **[Story]**: US1…US7 from spec.md
- Backend paths are relative to `backend/`, frontend paths to `frontend/`

---

## Phase 1: Setup (refactor demo into layers, tooling)

**Purpose**: The plan's layout and quality gates, with demo behaviour unchanged. Run
`uv run pytest` after each move.

- [X] T001 Move the demo packages to the plan layout with `git mv`-style moves and updated imports:
  - `src/automind/infra/` → `src/automind/infrastructure/` (`db.py` → `db/models.py` + `db/session.py`; `llm.py` → `llm_gateway.py`; `search.py` → `search_tavily.py`);
  - `src/automind/services/` → `src/automind/application/` (`catalog.py` → `resolve.py`; `research.py`; `analysis.py` → `compose.py`);
  - `src/automind/agents/graph.py` → `src/automind/orchestration/graph.py`;
  - `src/automind/api/app.py` stays.

  All 22 existing tests must pass.
- [X] T002 Add dependencies to `pyproject.toml` with `uv add`: `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`, `alembic`, `pyyaml`; dev: `ruff`, `mypy`, `import-linter`, `hypothesis`. Commit `uv.lock`
- [X] T003 [P] Configure ruff (line-length 120, select E,F,B,SIM,C90,I) and mypy (strict for `automind.domain`) in `pyproject.toml`. Fix the 28 existing ruff findings, including the `zip(strict=)` and `B008` default arg
- [X] T004 [P] Add `.importlinter`: `automind.domain` must not import langgraph, langchain*, fastapi, sqlalchemy, httpx, tavily, mcp, or `automind.{application,orchestration,infrastructure,api}`; `automind.application` must not import `automind.{orchestration,infrastructure,api}`, langgraph, fastapi, or sqlalchemy (constitution V)
- [X] T005 [P] Reduce complexity below 10 (C901). In `src/automind/domain/dragrace.py`, split `_simulate_one` into `_assumptions(...)`, `_forces(...)` and `_integrate(...)` with identical outputs (the existing race tests must stay green). Split `application/research.py` `_research_round` into `_collect_docs`, `_extract_all` and `_persist_claims`
- [X] T006 [P] Create config files:
  - `config/models.yaml`: roles interpreter, asker, resolver, extractor, validator, reporter, answerer, general → `provider:model`;
  - `config/prices.yaml`: € per 1M tokens per model, Tavily credit € price, credits per search/extract;
  - `config/sources.yaml`: move `MANUFACTURER_MARKERS`, `INSTRUMENTED`, `ENCYCLOPEDIA`, `SPEC_DB` and `DENYLIST` out of `domain/evidence.py` into config, loaded in `infrastructure/config.py` and passed into the domain.
- [X] T007 [P] Create `config/aliases.yaml` (make aliases: VW→Volkswagen, Mercedes→Mercedes-Benz, "Land Rover Prado"→Toyota Land Cruiser Prado; generation aliases: J150/150/Prado 150, J250/250, L320/Mk1 Range Rover Sport, F30, Mk8, Mk8.5) and `config/rates.yaml` (fuel 1.60 €/l, electricity 0.25 €/kWh, labour 75 €/h, annual_km 15000, tyre life km by class, the base reserve table from research.md R9 with age bands `0–4, 5–9, 10–14, 15+` × classes `small, compact, mid_large, premium_suv_4x4`)
- [X] T008 Set up Alembic in `alembic.ini` + `alembic/env.py` (async, `DATABASE_URL` from settings). Create the baseline migration `alembic/versions/0001_demo_baseline.py` from the existing demo tables. Replace `create_all` in startup with `alembic upgrade head`, called from `scripts/dev.sh`
- [X] T009 [P] Update `scripts/dev.sh` to run migrations and create the `automind_test` DB, and add `uv run ruff check`, `uv run mypy src/automind/domain` and `uv run lint-imports` to a new `scripts/check.sh`

---

## Phase 2: Foundational (blocking prerequisites)

**⚠️ No user story work can begin until this phase is complete.**

- [X] T010 Create the migration `alembic/versions/0002_conversation.py` with the new tables from data-model.md:
  - `chats(id, title ≤60, language, created_at, updated_at)`;
  - `case_files(chat_id, version, data jsonb, changed_by in (user, hub), change_log jsonb, created_at)` with PK `(chat_id, version)`;
  - `turns(...)` with all fields from data-model §1, `action` enum, `status` enum `RUNNING|WAITING_CONFIRMATION|DONE|CANCELLED|FAILED`;
  - `turn_events(chat_id, seq bigint, turn_id, type, payload jsonb, created_at)` with PK `(chat_id, seq)`;
  - `research_jobs(...)` with status `PENDING|RUNNING|DONE|FAILED|SKIPPED`;
  - `search_calls`;
  - new columns on `chat_messages.turn_id`, `llm_calls.turn_id`, `llm_calls.cost_eur`, `vehicle_variants.generation_years_from/to`, `vehicle_variants.class`, `vehicle_variants.segment`, `documents.content_sha256` (unique), `evidence.snippet_only`, `claims.area`, `research_runs.rounds_used`, `research_runs.minimum_met`; `research_runs` re-keyed to `(variant_id, area)`.
- [X] T011 [P] Add ORM models for the new tables in `src/automind/infrastructure/db/models.py` and repositories in `src/automind/infrastructure/db/repositories.py` (chats, case_files with `latest()`, `save_version()`; turns; turn_events with `append()` assigning the next seq atomically and `since(seq)`; research_jobs)
- [X] T012 Define the application ports in `src/automind/application/ports.py`: `LLM` (structured, text, agent), `Search` (search, extract, fill_full_text), `CaseRepo`, `TurnRepo`, `EventBus`, `CatalogRepo`, `EvidenceRepo`, `JobRepo`, `Clock`, `Usage`
- [X] T013 Implement `UsageCallbackHandler` in `src/automind/infrastructure/usage_callback.py` (LangChain callback: on_llm_end → tokens and model → €, using `config/prices.yaml`). Attach it to **every** model created in `infrastructure/llm_gateway.py`, including models passed to `create_agent`. `TurnBudget` tracks calls, tokens and € (LLM + search) and enforces a hard cap of €1.00 → `BudgetExceeded` (FR-041, FR-042, R12). Also add the configurable limits `max_llm_calls_per_turn`, `max_concurrency` (research jobs, default 4, an `asyncio.Semaphore`), `job_timeout_s` (default 90) and `turn_timeout_s` (default 300) in settings; reaching any limit ends the turn with available data plus a `notice` naming the limit. Tests in `tests/unit/test_turn_budget.py`
- [X] T014 [P] Record Tavily calls in `src/automind/infrastructure/search_tavily.py` as `search_calls` rows (kind search/extract, credits, €), charged to the `TurnBudget`
- [X] T015 Implement the checkpointer factory in `src/automind/infrastructure/checkpoint.py`: `AsyncPostgresSaver` from a psycopg `AsyncConnectionPool` built from `DATABASE_URL` (convert `postgresql+asyncpg://…?host=/path` to a psycopg conninfo), calling `setup()` at startup
- [X] T016 [P] Implement the event bus in `src/automind/infrastructure/events.py`: `publish(chat_id, turn_id, type, payload)` → persist via the turn_events repo (seq) and fan out to WebSocket subscribers; `replay(chat_id, after_seq)`
- [X] T017 [P] Create the scripted fake LLM in `tests/fakes/fake_llm.py`. It implements the `LLM` port and returns queued structured outputs or texts per role, raising if the queue is empty. It also offers a `create_agent`-compatible fake that emits a fixed answer and records tool calls
- [X] T018 [P] Create the fixture search provider in `tests/fakes/fixture_search.py` (scenario dirs `tests/fixtures/scenarios/<name>/` with `search.json` and `docs/*.txt`; injectable failures per URL)
- [X] T019 Build the golden dialogue runner in `tests/golden/runner.py` and the schema `tests/golden/schema.py`:
  - YAML format: `turns: [{user|confirm, expect: {action, case: {jsonpath: value}, variants: [...], no_search: bool, max_cost_eur}}]`;
  - **replay mode**: fake LLM outputs from `tests/golden/cassettes/<id>/<turn>.json` plus fixture search;
  - **live mode** (`-m live`): real gateway, recording cassettes with `--record`.
- [X] T020 Rewrite the WebSocket endpoint as protocol v2 in `src/automind/api/ws.py` per contracts/chat-protocol.md:
  - `hello{last_seq}` → replay;
  - `user_message`, `confirm`, `cancel`;
  - every server message carries `seq` and `turn_id`;
  - v1 messages stay compatible.

  Move REST to `src/automind/api/rest.py` under `/api/v1` (keep the `/api/health` and `/api/chats/{id}/messages` aliases).
- [X] T021 Implement `ChatRunner` in `src/automind/orchestration/runner.py`:
  - one graph thread per chat (`thread_id = chat_id`);
  - `run_turn(chat_id, text)`;
  - `resume(chat_id, payload)` via `Command(resume=...)`;
  - one active turn per chat (a second message while RUNNING → error "busy");
  - a turn record and `TurnBudget` set per turn.
- [X] T022 [P] Update the frontend protocol schemas to v2 in `src/lib/protocol.ts`: `seq`/`turn_id`, `case_file`, `confirm_request`, `usage`, `turn_cancelled`, and the new block types per contracts/chat-protocol.md, with unknown types ignored. Update `src/lib/transport.ts` to send `hello{last_seq}` on connect and track `last_seq`. Add vitest cases in `src/lib/protocol.test.ts`

**Checkpoint**: the demo flow still works through the new runner (v1 behaviour), and the fakes
and golden runner exist.

---

## Phase 3: User Story 1: The expert understands me and remembers (P1) 🎯 MVP

**Goal**: A persisted case file, interpretation into typed deltas, the deterministic action
policy, clarifying questions, context-aware resolution with confirmation, corrections, and no
repeated reports.

**Independent Test**: Golden G1 (up to the variant confirmation), G2 (case fields) and G6 (no
repeat) in replay mode. Case-file assertions and actions per turn, with no live research.

### Tests for US1 (write first)

- [X] T023 [P] [US1] Write unit tests for the case file in `tests/unit/domain/test_casefile.py`:
  - apply each `CaseDelta` operation;
  - latest statement wins;
  - `replace_car` keeps the key and resets `variant_id`/`resolution`;
  - "≤3 cars (more → ASK)";
  - "`age_years` and `year` are consistent: year = current_year − age ± 1";
  - "Weights are ≥0 and sum to 100 ±0.01";
  - unknown criterion keys rejected;
  - the change_log text for each change.
- [X] T024 [P] [US1] Write unit tests for the policy in `tests/unit/domain/test_policy.py`, one test per rule of research.md R5 in order:
  - general/chitchat → ANSWER_GENERAL;
  - essentials missing → ASK (≤3 questions; a used car without age when the model spans >1 generation; >3 cars; persona unknown and the recommendation depends on persona);
  - ambiguous, used or uncatalogued variant → CONFIRM_VARIANTS;
  - estimate ≥ €0.30 → CONFIRM_COST, otherwise RESEARCH;
  - weights_change/follow_up with data → ANSWER_FROM_CONTEXT;
  - fingerprint equal to the last report → ANSWER_FROM_CONTEXT "nothing new";
  - otherwise REPORT;
  - a single car → REPORT as a profile (no ranking, no winner, no race) (FR-012).
- [X] T025 [P] [US1] Write unit tests for identity in `tests/unit/domain/test_identity.py`:
  - aliases (VW→Volkswagen, "Land Rover Prado"→Toyota Land Cruiser Prado, J150=150);
  - `canonical_key` equal for alias spellings;
  - generation year-range check (a ~2015 Prado → 150 accepted, 250 rejected);
  - fuzzy de-dup threshold 92 on the same make, model, generation and powertrain.
- [X] T026 [P] [US1] Create golden dialogues G1, G2 and G6 as YAML in `tests/golden/g1_bigster_prado.yaml`, `g2_bmw_vs_golf_age20.yaml` and `g6_no_repeat.yaml`, per the quickstart.md table (actions, case fields, variants), with replay cassettes for the fake LLM outputs and fixtures under `tests/fixtures/scenarios/` (Prado 150 and 250 pages, Bigster, BMW F30 320d, Golf Mk7/Mk8 R-Line). G2 is written in Russian and asserts `language: ru` (FR-001). The cassettes are hand-written at this stage; T084 replaces them with recorded ones
- [X] T027 [P] [US1] Write a graph test for persistence in `tests/graph/test_persistent_thread.py`: two turns through two separate `ChatRunner` instances on the same Postgres checkpointer keep the case and context. An interrupt survives a runner restart and resumes with `Command(resume=...)`

### Implementation for US1

- [X] T028 [P] [US1] Implement `CaseFile`, `CaseCar`, `CaseDelta` and the pure `apply(case, delta) -> (case, change_log)` in `src/automind/domain/casefile.py`, with the exact fields and enums from data-model.md §2 (persona `EXPERT|PERFORMANCE|BUYER|UNKNOWN`, persona_source `INFERRED|ASKED|USER_EDIT`, usage set `CITY|MOTORWAY|MOUNTAINS|OFFROAD|TRACK|FAMILY`, depth `QUICK|STANDARD|DEEP` default STANDARD, annual_km default 15000, cars max 3 with keys `car#N`, resolution `UNRESOLVED|PROPOSED|CONFIRMED|AUTO_OK`), so that T023 passes
- [X] T029 [P] [US1] Implement `domain/identity.py` (alias normalization from loaded aliases, `canonical_key`, `generation_matches(year, from, to)`, `is_duplicate(a, b)` using rapidfuzz ≥ 92 passed in as a function to keep the domain dependency-free) so that T025 passes
- [X] T030 [US1] Implement `domain/policy.py` with `decide(case, interpretation, cache_state, cost_estimate, last_fingerprint) -> Action` and `fingerprint(case)`, so that T024 passes. Thresholds come from config (confirmation €0.30, cap €1.00)
- [X] T031 [P] [US1] Write the interpreter prompt in `src/automind/orchestration/prompts/interpreter.md`: the role; the case JSON; the pending item; the last 6 turns; criteria keys with one-line definitions; rules (car refs by key, unknown wishes → `unmapped_wishes`, persona inference cues per FR-005a); and few-shots from golden dialogues, including "but i asked about used 10 yrs old LC prado 150 not new" → `replace_car(car#2, …, condition USED, age 10, generation_hint "150")` and "if i prefer status" → `add_priorities[status HIGH]`, request `weights_change`
- [X] T032 [US1] Implement `application/interpret.py`: build the prompt from the case and history; call the `interpreter` role with structured output `Interpretation {delta: CaseDelta, request: enum, language}`; validate car keys and criteria keys; return a validated object or raise `InterpretError` (→ ASK "could you rephrase")
- [X] T033 [P] [US1] Write the asker prompt in `orchestration/prompts/asker.md` and question templates in `config/questions.yaml` (used-car age/generation, trim, more than 3 cars, persona). Implement `application/ask.py`, which phrases ≤3 template questions in the user's language and records `case.pending = {kind: QUESTIONS, items}`
- [X] T034 [US1] Rework resolution in `application/resolve.py`:
  - catalog-first lookup using normalized make/model plus generation hint plus the year overlap (`generation_years_from/to`);
  - on a miss, the resolver prompt (`orchestration/prompts/resolver.md`, no tools) gets the case context (condition, year/age, fuel hint) and returns `VariantIdentity` with `generation_years_from/to`, `alternatives` and `certainty`;
  - code validates the year in range;
  - the de-dup check runs before insert (FR-007, FR-008, FR-024).
- [X] T035 [US1] Implement the turn graph nodes in `src/automind/orchestration/nodes/`:
  - `load_case.py`, `interpret.py` and `apply_delta.py` (persists the new case version and publishes `case_file` with changes);
  - `policy.py`;
  - `ask.py` (ends the turn with the questions);
  - `confirm_variants.py` (resolve, then `interrupt({kind: variants, options})`, then on resume apply the choice or route free text back to interpret);
  - `general.py` (labelled "no sources", from the demo).

  Wire them in `orchestration/graph.py` per the plan's turn graph. Research, report and answer nodes call the existing demo compose path for now.
- [X] T036 [US1] Implement the no-repeat behaviour: store `turns.fingerprint` and `case.shown`. The policy uses the last report fingerprint. The answer-from-context node (`nodes/answer.py`) states what is unchanged or new and does not resend unchanged blocks (FR-004)
- [X] T037 [US1] Implement the case REST in `api/rest.py`: `GET /api/v1/chats/{id}/case` and `PATCH /api/v1/chats/{id}/case` (persona, usage, budget, annual_km, rates_override, depth, weights → `weights_overridden=true`, remove priority). Return 409 if a turn is RUNNING and 422 on validation error. Write a version with `changed_by=user` and publish `case_file`
- [X] T038 [P] [US1] Build the frontend case panel in `src/components/CasePanel/CasePanel.tsx` and `src/store/case.ts`: persona select, usage chips, budget, annual km, depth, priorities list, rates (fuel €/l, electricity €/kWh, labour €/h → `rates_override`, FR-034), and cars with condition/year and resolution badge. Edits PATCH the case. Collapsible sidebar on desktop, bottom sheet under 768 px
- [X] T039 [P] [US1] Build the frontend confirmation card in `src/components/ConfirmCard.tsx`: variant options as buttons, a "something else" free-text reply, and a cost card with estimate, cars, areas and depth plus Run/Skip, sending `confirm{request_id, choice}`
- [X] T040 [US1] Make golden G1 (to confirmation), G2 and G6 pass in replay mode (`uv run pytest tests/golden -k "g1 or g2 or g6"`) and T027 pass; fix the prompts and policy until green

**Checkpoint**: the hub asks, remembers, corrects and confirms. The Prado 150 case is handled.

---

## Phase 4: User Story 2: Research-grade comparison (P2)

**Goal**: Case-driven research across areas, with validation, section minimums, gap rounds by
depth, cost estimate and confirmation, jobs and cache.

**Independent Test**: Fixture scenarios for 2 cars at Standard depth: every value is labelled,
"insufficient data" appears below the minimums, the cost confirmation shows above €0.30, and a
repeat within freshness runs 0 searches.

### Tests for US2 (write first)

- [X] T041 [P] [US2] Write unit tests for the research planner in `tests/unit/domain/test_research_plan.py`:
  - areas per criteria and persona (expert → Tier 2 engineering; buyer → maintenance, reliability, reviews, price; used → used_issues);
  - per-area freshness defaults "specs 365, maintenance 365, reliability and reviews 180, official price 30, manufacturer 30";
  - rounds "Quick 0, Standard 1, Deep 2";
  - section minimums "key specs: manufacturer + 1 independent or 2 independent; maintenance: manufacturer schedule or 2 independent; reviews ≥5 from ≥2 sources; reliability ≥2 independent";
  - freshness for the extra areas per research.md R8 (engineering, practicality, measured 365; used_issues 180);
  - early warnings: a car older than 25 years → "sources are scarce" notice; no ES market source → "not sold in Spain" notice.
- [X] T042 [P] [US2] Write unit tests for the cost estimate in `tests/unit/domain/test_cost.py` (cars × areas × depth × per-area averages × prices + search credits; fallback averages from config; monotonic in cars and depth)
- [X] T043 [P] [US2] Write a graph test for research in `tests/graph/test_research_flow.py` (fixture scenario: jobs created per car × area; one source failing doesn't fail the turn; a gap round runs only for the missing items; a second run within freshness → 0 search calls; estimate ≥0.30 → CONFIRM_COST, skip → no jobs)

### Implementation for US2

- [X] T044 [P] [US2] Implement `domain/research_plan.py` (areas, attribute needs per criterion, minimum rules, freshness per area, early warnings, gap computation from the selected values, rounds per depth) so that T041 passes
- [X] T045 [P] [US2] Implement `domain/cost.py` `estimate(plan, averages, prices)` so that T042 passes. Compute per-area averages from `llm_calls` and `search_calls` history in `infrastructure/db/repositories.py`
- [X] T046 [P] [US2] Extend the attribute registry in `src/automind/domain/specs.py` with practicality and Tier 2 engineering attributes: rear legroom if sourced, `ground_clearance` mm, `low_range` bool, `tyre_size`, `fiscal_hp`, `euro_ncap_stars`, `segment`, `engine_layout`, `cylinders`, `aspiration`, `bore`, `stroke`, `compression_ratio`, `gear_count`, `platform`, `suspension_front/rear`, `drag_coefficient`, each with units, tolerances and plausibility ranges, plus tests in `tests/unit/test_domain.py`
- [X] T047 [P] [US2] Implement `src/automind/infrastructure/fetch.py` per research.md R8: deny-list check first, robots.txt (cached per host 24 h), per-host rate limit (1 request / 2 s), timeout 15 s, max 3 MB, HTML/PDF/text only. Use it for pasted URLs (`CaseCar.constraints.url`: the first source and a resolution hint in `application/resolve.py`). Tests in `tests/unit/infrastructure/test_fetch.py` (deny-listed host never requested; robots disallow; size and timeout limits) (constitution VIII, FR-022, edge case "pasted URL")
- [X] T048 [US2] Create area extraction schemas and prompts (web readers, no tools, `<untrusted_document>` delimiters): `MaintenanceItems`, `ReviewItems` (polarity PRO/CON, tag in `comfort|handling|quality|practicality|noise|reliability|value|other`, reviewer EXPERT/OWNER), `IssueItems` (component, description, age/mileage window, severity wording), `ReliabilityStats`, `ManufacturerFacts` (kind `MARKET_POSITION` must state premium/mainstream/budget in the excerpt → mapped by code to `vehicle_variants.brand_positioning` for the status criterion, FR-028) and `PriceClaims`, in `src/automind/application/extraction.py` with prompts in `orchestration/prompts/extract_<area>.md`. All items require a verbatim excerpt that is checked by `domain/evidence.validate_excerpt`
- [X] T049 [US2] Implement the validator role (constitution XI, research.md R8) in `src/automind/application/extraction.py` with the prompt `orchestration/prompts/validator.md` (web reader, no tools): pages with an uncertain variant match → per claim `SAME_VARIANT|OTHER_VARIANT|GENERATION_WIDE|UNCLEAR`. Only SAME_VARIANT is stored as a variant value; GENERATION_WIDE → confidence LOW; the rest are rejected and counted. The uncertainty trigger is a pure function in `domain/evidence.py`. Tests: `tests/unit/test_domain.py` (trigger) and `tests/graph/test_research_flow.py` (fake validator rejects a Prado 250 page for a Prado 150)
- [X] T050 [US2] Add the result tables via migration `alembic/versions/0003_research_areas.py`: `maintenance_items`, `review_items`, `issues`, `reliability_stats` and `manufacturer_facts` with the fields from data-model.md §4. Add repositories
- [X] T051 [US2] Refactor `application/research.py` into area workers: `run_job(job)` = queries for the area (EN + ES templates in `config/queries.yaml`) → search with full text (`fill_full_text`) → extraction → validation → persist → mark the job DONE. One job failing never fails the turn (FR-023). Publish `status` with car and area, including accepted and rejected claim counts (FR-016)
- [X] T052 [US2] Implement the research nodes in `orchestration/nodes/research.py`:
  - `plan_research` → `estimate` → (policy may interrupt for cost) → `Send` per job → `gaps` (recompute after the round) → loop ≤ the depth's rounds → `compute`.

  Mark `research_runs.minimum_met` and the area freshness. Publish `followup` status for each gap round.
- [X] T053 [US2] Implement the cost confirmation node `orchestration/nodes/confirm_cost.py` (`interrupt({kind: cost, estimate})`; Run → research, Skip → answer with what exists) and enforce the €1.00 cap via `TurnBudget` (FR-041, SC-015)
- [X] T054 [US2] Add "insufficient data" notices and per-section `minimum_met` flags to the composed blocks in `application/compose.py` (FR-019)

**Checkpoint**: research is driven by the case file and validated; costs are confirmed and
capped.

---

## Phase 5: User Story 3: Report for who I am, with criteria (P3)

**Goal**: The criteria dictionary, deterministic scoring with visible weights, persona block
order, persona reporters and answerer with scoped MCP tools, and recompute on weight change.

**Independent Test**: The same 2 cached cars with 3 personas give different block order and
wording. A weight PATCH recomputes in under 5 s with 0 searches. "nice colour" → not assessable.

### Tests for US3 (write first)

- [X] T055 [P] [US3] Write unit tests for criteria in `tests/unit/domain/test_criteria.py`:
  - persona default weights exactly as research.md R7;
  - wish strength LOW/MEDIUM/HIGH → +10/+20/+30, then normalize to 100;
  - per-criterion scales;
  - status = price class + segment + brand positioning, age-adjusted for used cars;
  - review_balance uses only recurring validated items;
  - a criterion with no data → `insufficient: true`;
  - a car with covered weight < 60% → `ranked: false`;
  - a single car → absolute scores, `ranked: false`, `winner: null` (FR-012);
  - deterministic outputs.
- [X] T056 [P] [US3] Write unit tests for the report layout in `tests/unit/domain/test_report_layout.py` (the exact persona block orders from contracts/chat-protocol.md; warning notices first; a single car → profile layout without `race_chart` and with `winner_car_id=null`, FR-012)

### Implementation for US3

- [X] T057 [P] [US3] Write `config/criteria.yaml` v1 with all 13 criteria from research.md R7 (key, label, definition, inputs, scale, min_data, persona default weights)
- [X] T058 [US3] Implement `domain/criteria.py` (load the model, `weights_for(case)`, `score(cars_data, weights) -> CriteriaScore`). Move the demo `domain/scoring.py` metric functions into `domain/metrics.py` and delete `PROFILES`. T055 must pass
- [X] T059 [P] [US3] Implement `domain/report_layout.py` `order_blocks(persona, blocks)` so that T056 passes
- [X] T060 [US3] Rework the MCP server `src/automind/mcp_server.py` per contracts/rest-and-mcp.md:
  - tools `get_case`, `get_vehicle_specs`, `compute_metrics` (labelled metrics), `score_criteria` (labelled scores), `simulate_drag_race`, `compute_tco`, `get_reliability`, `get_reviews`, `get_engineering`, `get_manufacturer`, `list_catalog`;
  - remove the private cross-module imports (use public `application/compose.py` functions);
  - add tests in `tests/integration/test_mcp_tools.py`.
- [X] T061 [US3] Implement the persona reporters and answerer in `orchestration/agents.py`: a factory `make_agent(role, persona)` loading `prompts/reporter_{expert,performance,buyer,balanced}.md` or `prompts/answerer.md`, with the scoped MCP tool subset per the contracts table. Inject the MCP session (no module global), use a recursion limit of 14, and attach the usage callback
- [X] T062 [US3] Implement `orchestration/nodes/compute.py` (criteria scores, metrics, race, TCO, blocks via `application/compose.py`, ordered by `report_layout`), `nodes/report.py` (persona reporter) and `nodes/answer.py` (answerer, no research), plus the guard node (demo `check_numbers` with the case numbers allowed; removal notice)
- [X] T063 [US3] Implement a weights change through PATCH and chat: recompute in `src/automind/orchestration/nodes/compute.py` from cached data, with the policy guaranteeing no research unless a new criterion lacks data (FR-029, SC-009)
- [X] T064 [P] [US3] Build frontend blocks `src/components/blocks/CriteriaScores.tsx` (bars per car with contribution segments, insufficient markers, weights, unmapped wishes), `CaseSummary.tsx`, `Engineering.tsx` and `Manufacturer.tsx`, registered in `BlockView.tsx`
- [X] T065 [P] [US3] Add weight sliders to `CasePanel` (normalized display; PATCH on release) in `src/components/CasePanel/Weights.tsx`
- [X] T066 [US3] Create golden G3 (persona switch to expert) as `tests/golden/g3_persona_expert.yaml` with a cassette, and make it pass in replay mode

---

## Phase 6: User Story 4: Ownership cost (P4)

**Goal**: Itemized annual and 5-year TCO, sourced vs assumption, with the two-part used-car
reserve.

**Independent Test**: A new car and a ~10-year-old used car: totals, items and labels; the used
car shows BIG_TICKET and BASE_RESERVE separately.

- [X] T067 [P] [US4] Write unit tests for TCO in `tests/unit/domain/test_tco.py`:
  - item kinds `MAINTENANCE|ENERGY|TYRES|ROAD_TAX|BIG_TICKET|BASE_RESERVE`;
  - maintenance from the sourced schedule vs labour × rate assumption;
  - energy;
  - tyres by class and life;
  - road tax only if a rate is found, otherwise "not included";
  - big-ticket items whose age/mileage window falls in the next 5 years;
  - the base reserve from the table by age band × class;
  - annual_km override;
  - every item labelled SOURCED or ASSUMPTION with inputs.
- [X] T068 [US4] Implement `domain/tco.py` `compute(car_data, case, rates) -> TcoEstimate` so that T067 passes. Remove `ownership()` from the old scoring module
- [X] T069 [US4] Add the migration `alembic/versions/0004_tco_simulations.py` with `tco_estimates` (fields from data-model §5) and `simulations`. Persist the TCO per turn in `nodes/compute.py`
- [X] T070 [P] [US4] Build the frontend block `src/components/blocks/Tco.tsx` (annual and 5-year per car, stacked item bars, SOURCED/ASSUMPTION badges, inputs on hover, used-car reserve shown in two parts). Remove the `Maintenance.tsx` usage for v2 payloads

---

## Phase 7: User Story 5: Reliability and reviews (P5)

**Goal**: Issues with recurrence and severity, reliability statistics, review pros and cons with
recurring vs isolated, and minimums.

**Independent Test**: A fixture variant with a documented recurring issue, plus reviews: the
blocks show the issue (RECURRING, ≥2 domains), pros and cons with sources, and `minimum_met`.
A variant without issues shows "no documented issues found".

- [X] T071 [P] [US5] Write unit tests in `tests/unit/domain/test_reliability_reviews.py`: "recurring requires ≥2 independent sources"; severity from the keyword rules in `config/severity.yaml` (research.md R8); the review minimum "≥5 reviews from ≥2 sources"; recurring pros and cons = the same tag and polarity from ≥2 domains; `none_found` semantics; subjective opinions ("boring", "ugly") are never listed as issues (FR-036)
- [X] T072 [US5] Implement `domain/reliability.py` and `domain/reviews.py` (merge, recurrence, severity from `config/severity.yaml`, minimums) so that T071 passes
- [X] T073 [US5] Build the `reliability` and `reviews` blocks in `application/compose.py`, using the used-car emphasis: issues whose age window overlaps the car's age come first
- [X] T074 [P] [US5] Build the frontend blocks `src/components/blocks/Reliability.tsx` and `Reviews.tsx` (recurrence and severity badges, sources popovers, insufficient-data state)

---

## Phase 8: User Story 6: Drag race in the new flow (P6)

**Goal**: The demo race engine inside the compute node, with settings and prediction from the
case, persisted simulations.

**Independent Test**: The same inputs twice give an identical hash. Wet +200 kg gives slower
times. The prediction is compared.

- [X] T075 [US6] Map race settings and prediction from chat to the case (`case.race_settings`, `case.prediction`) via interpreter delta ops `set_race_settings` and `set_prediction`. Persist `simulations` (model_version, settings, prediction, inputs, assumptions, results, input_hash) in `nodes/compute.py`
- [X] T076 [P] [US6] Add the prediction result to `race_chart` (`prediction`, `prediction_correct`) in `application/compose.py`, and show it in `src/components/blocks/RaceChart.tsx`
- [X] T077 [P] [US6] Add a graph test `tests/graph/test_race_turn.py` ("race them in the wet with 2 passengers" → ANSWER_FROM_CONTEXT with recomputed race; identical rerun hash)

---

## Phase 9: User Story 7: Progress, limits, history (P7)

**Goal**: Cancel, restart resume, chat list, usage badge, replay on reconnect.

**Independent Test**: Quickstart V4–V7.

- [X] T078 [P] [US7] Write a graph test `tests/graph/test_cancel_and_resume.py`: cancel mid-research → turn CANCELLED and validated data kept. Kill the runner mid-research, start a new runner → `resume_incomplete()` continues and DONE jobs keep `attempts` unchanged (SC-013)
- [X] T079 [US7] Implement cancel in `orchestration/runner.py` (cancel flag checked between jobs, task cancellation, `turn_cancelled` event) and `resume_incomplete()` at app startup (threads whose checkpoint is mid-turn, not interrupted → `ainvoke(None)`), in `api/app.py` lifespan
- [X] T080 [US7] Implement `GET /api/v1/chats` (title from the first message ≤60 chars, cars, persona) in `api/rest.py`. Publish the `usage` message at turn end from `TurnBudget`
- [X] T081 [P] [US7] Build frontend `src/components/ChatList.tsx` (history drawer, open and continue), `CancelButton.tsx` (visible during RUNNING) and a usage badge per assistant message (calls, tokens, €)
- [X] T082 [US7] Write a test for usage accuracy in `tests/graph/test_usage_accounting.py`: the turn usage equals the sum of `llm_calls` + `search_calls` rows for the turn, including reporter-agent calls (SC-012)

---

## Phase 10: Polish & cross-cutting

- [X] T083 Create golden G4, G5 and G7 YAML with cassettes in `tests/golden/`, and make all G1–G7 pass in replay mode (SC-001, SC-002)
- [ ] T084 Run the golden dialogues live (`uv run pytest tests/golden -m live --record`), fix prompts and policy until all pass, and commit the refreshed cassettes. Record the cost per run in `tests/golden/README.md`. Store `turns.duration_ms` and assert in the live run: from-cache answers ≤ 15 s p90 (SC-004), weight change ≤ 5 s (SC-009), new 2-car Standard research ≤ 3 min p90 over ≥5 runs (SC-005); write the measured values to the README
- [X] T085 [P] Build the used-car resolution test set `tests/eval/used_resolution.yaml` (≥20 requests "used <model>, <age/year>" with expected generation) and the eval `tests/eval/test_used_resolution.py` (marker `live`, target ≥95%, SC-003)
- [ ] T086 [P] Build the Tier 1 reference set `eval/reference_vehicles.yaml` (≥20 variants incl. used generations, with published instrumented 0–100) and the eval for coverage/accuracy (SC-007) and race calibration ±15% (SC-011)
- [X] T087 [P] Update the Docker deployment: `Dockerfile` runs `alembic upgrade head` before uvicorn, and `docker-compose.yml` is checked once Docker is installed. Document this in `README.md`
- [X] T088 [P] Write ADRs `docs/adr/ADR-001…ADR-015.md`: sec.md's 12, plus ADR-013 persistent chat thread and case file, ADR-014 deterministic action policy, ADR-015 criteria dictionary, ADR-016 deferring TanStack Query, React Router and LangSmith (plan.md stack deviations)
- [X] T089 [P] Update `README.md` (architecture diagram of the turn graph, how to read the code: start with `domain/`, how to run golden dialogues)
- [X] T090 Run `scripts/check.sh` (ruff, mypy domain, import-linter) and the full test suite green, then run quickstart V1–V10 manually and record the results in `specs/002-conversational-mvp/checklists/validation.md`

---

## Dependencies & Execution Order

- **Phase 1** comes first. T001 blocks the others; T003–T009 can run in parallel afterwards.
- **Phase 2** depends on Phase 1 and blocks all stories.
- **US1 (Phase 3)** is the MVP increment and depends on Phase 2.
- **US2 (Phase 4)** depends on US1's graph (T035). T041–T047 can start right after Phase 2.
- **US3 (Phase 5)** depends on US2's compute inputs. T055–T059 can start after Phase 2.
- **US4 (Phase 6)** and **US5 (Phase 7)**: the domain parts (T067–T068, T071–T072) can start
  after Phase 2; the wiring needs US2 data and US3 compute.
- **US6 (Phase 8)** depends on US3 compute.
- **US7 (Phase 9)**: T078–T079 need the US2 jobs; T080–T081 can start after Phase 2.
- **Polish** comes last. T085 and T086 can start any time.

**Story order**: US1 → US2 → US3 → (US4 ∥ US5) → US6 → US7 → Polish

## Parallel examples

```text
Phase 1: T003 ∥ T004 ∥ T005 ∥ T006 ∥ T007 ∥ T009   (after T001, T002)
Phase 2: T011 ∥ T014 ∥ T016 ∥ T017 ∥ T018 ∥ T022
US1 tests: T023 ∥ T024 ∥ T025 ∥ T026 ∥ T027 → impl: T028 ∥ T029 ∥ T031 ∥ T033 → T030 → T032 → T034 → T035 …
US1 UI: T038 ∥ T039 (after T022)
Pure domain work that can run alongside US1: T041 ∥ T042 ∥ T055 ∥ T056 ∥ T067 ∥ T071
```

## Implementation strategy

1. **Phases 1–2**: refactor plus infrastructure; the demo keeps working through the new runner.
2. **US1 (MVP increment)**: demo it with your real dialogues (Bigster vs Prado 150, BMW vs Golf
   at age 20, "status") using cached data. This proves the hub is no longer "deaf".
3. **US2 + US3**: research and reports tailored to the person (second demo).
4. **US4 + US5**: TCO and reliability, the main value for buyers.
5. **US6 + US7 + Polish**: race in the new flow, robustness, live golden runs, evaluation,
   deployment.

## Notes

- Constraints quoted in tasks come verbatim from data-model.md, research.md and the spec. Do not
  relax them.
- Never put rules in prompts that the policy or domain must guarantee (constitution III, IX).
- Commit after each task or logical group.
