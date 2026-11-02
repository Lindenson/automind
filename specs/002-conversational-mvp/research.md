# Phase 0 Research: AutoMind Conversational MVP

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-11-01

Inputs:
- constitution v1.1.0;
- `docs/vision.md` (incl. §5a);
- the working concept-demo code in `backend/` and `frontend/` (reused);
- the failure analysis of real demo dialogues (Prado 150 and 250, BMW 320d vs Golf R-Line,
  "status").

Format per decision: **Decision / Rationale / Alternatives**. The library versions installed in
the demo are LangGraph 1.2.19, LangChain 1.4.7, langchain-mcp-adapters 0.3.2, mcp 1.30 and
FastAPI 0.162. New dependencies are pinned when added.

---

## R1. Why the demo hub was "deaf" (root causes → design answers)

| Root cause in demo code | Design answer |
|---|---|
| Each turn ran a fresh graph thread (`thread_id = chat:message`); only 8 lines of text history survived | One **persistent graph thread per chat** (`thread_id = chat_id`) with a Postgres checkpointer, plus an authoritative **case file** in the domain DB (R3) |
| Intent schema had only add, remove-by-label and keep | **Case-file delta** extraction (R4) with explicit operations: set persona, usage, budget, priorities; add, replace or remove a car with constraints (used, age, generation) |
| No "ask" path; always researched | **Action policy** (R5): a deterministic rule layer chooses ask / confirm / answer-from-context / correct / research / report |
| Resolver preferred the newest generation; ignored "used, 10 years old" | **Context-aware resolution** (R6): age or year selects the generation, catalog first, generation year-range validation |
| Fixed 3 profiles with fixed weights; "status" unknown | **Criteria dictionary** (R7) with persona default weights and wish→criteria mapping |
| One analyst prompt for everyone | **Persona report agents** (R10) with persona-specific section order, depth and language |
| Maintenance only for one profile, service and fuel only | **TCO engine** (R9) with used-car big-ticket items and a two-part reserve |
| Analyst calls not counted | **Usage callback** on every model instance (R12) |
| Duplicate catalog variants | **Canonical identity and de-duplication** (R6) |

## R2. Orchestration: one persistent thread per chat

- **Decision**: The main graph is compiled with `AsyncPostgresSaver`
  (`langgraph-checkpoint-postgres` 3.x, psycopg 3 pool), with `thread_id = chat_id`.
  - Each user message invokes the graph with the new message.
  - Confirmations (variants, cost) use `interrupt()`. The next client message of type
    `confirm` resumes the graph with `Command(resume=...)`.
  - A free-text message while an interrupt is pending also resumes it. The resume payload is
    the text, which the interpret node handles (it may be a correction instead of a yes).
- **Rationale**: This fixes memory loss at the root (constitution VI: checkpointed, resumable).
  Interrupts are the constitution's mechanism for human approval (ADR-007).
- **Graph state** holds only identifiers and compact turn data: `chat_id`, `case_version`,
  `pending` (question or confirmation), `turn` scratch, `research_job_ids`, and the reply. Large
  data lives in the domain DB (constitution VI).
- **Alternatives**: rebuilding state from DB history per turn (the demo approach; brittle, no
  interrupts); `InMemorySaver` (lost on restart).

## R3. Case file: authoritative, versioned, user-editable

- **Decision**: `CaseFile` is a Pydantic domain model stored as versioned rows
  (`case_files(chat_id, version, data jsonb, changed_by: user|hub, change_log)`).
  - Updates are applied **deterministically** from a validated `CaseDelta` (R4) by
    `domain.casefile.apply(case, delta)`, which returns the new case plus a change log. The
    latest statement wins (FR-003).
  - User edits from the UI (`PATCH /api/chats/{id}/case`) create a version with
    `changed_by=user`.
- **Rationale**: The memory is inspectable, testable and editable (FR-009). Golden dialogues can
  assert exact case states (FR-046).
- **Alternatives**: LangGraph long-term `Store` (deferred: constitution notes it for later; a
  case file per chat is enough for the MVP); free-text memory summaries (not testable).

## R4. Interpretation: LLM proposes a delta, code validates

- **Decision**: The `interpret` node runs the hub model with structured output
  `Interpretation`, which contains:
  - `delta: CaseDelta`, with the operations `set_persona`, `set_profile_facts` (age,
    experience), `set_usage`, `set_budget`, `set_mileage`, `set_priorities` (keys from the
    criteria dictionary plus a strength), `add_car`, `replace_car` (target ref plus new
    constraints), `remove_car`, `set_car_context` (new/used, year or age, mileage) and
    `set_depth`;
  - `request: Literal[...]`: compare / single / follow_up_question / weights_change /
    correction / general_question / confirm_yes / confirm_no / chitchat;
  - `language`.

  Car references must use the case's car keys (`car#1`, `car#2`), which are given to the model.
  Unknown criteria keys are rejected by the schema, and the wish goes to `unmapped_wishes`
  (FR-028 "not assessable").
- **Prompt**: the full case file (compact JSON), any pending question or confirmation, the last
  6 turns, and the criteria dictionary keys with one-line definitions. Few-shot examples come
  from the golden dialogues, e.g. "but I asked about used 10 yrs old LC Prado 150 not new" →
  `replace_car(car#2, model="Land Cruiser Prado", generation_hint="150", used=true, age=10)`.
- **Rationale**: The model is good at language, and code is good at state. Typed deltas are
  testable.
- **Alternatives**: letting the LLM rewrite the whole case file (silent drift, untestable).

## R5. Action policy: deterministic rules decide the next step

- **Decision**: The pure function `domain.policy.decide(case, interpretation, cache_state,
  cost_estimate) -> Action` applies these rules in order:
  1. `general_question` / `chitchat` → **ANSWER_GENERAL**.
  2. Missing essentials → **ASK** (≤3 questions, one round, FR-005 and FR-005a). Essentials
     are: any car without resolvable identity; a used car without age or year when the model
     spans more than one generation in plausible years; more than 3 cars; persona unknown
     **and** the request is a recommendation where persona changes weights. Questions come from
     templates and are phrased by the hub model in the user's language.
  3. Cars needing resolution or confirmation (FR-006: ambiguous, used, or not in the catalog) →
     **CONFIRM_VARIANTS** (interrupt).
  4. Required data stale or missing for current criteria, with cost estimate ≥ €0.30 →
     **CONFIRM_COST** (interrupt); otherwise → **RESEARCH**. The hard cap is €1.00 (FR-041).
  5. `weights_change` / `follow_up_question` with data present → **ANSWER_FROM_CONTEXT** (no
     research, FR-029).
  6. Otherwise → **REPORT**. If the case fingerprint (cars, criteria, weights, persona,
     settings) equals the last reported fingerprint, the action becomes **ANSWER_FROM_CONTEXT**
     with a "what's new" answer (FR-004: never repeat).
- **Rationale**: These are the behaviours the user complained about. They must be guaranteed,
  not left to prompt luck. Each rule maps to one requirement and one unit test.
- **Alternatives**: a pure LLM supervisor choosing tools (the behaviour is not testable and
  failed in the demo).

## R6. Variant resolution with context, catalog first, no duplicates

- **Decision**:
  - **Catalog lookup** uses normalized make/model, a generation hint, powertrain hints and the
    year. A match must have its production years overlapping the requested year or age range.
  - **On a miss**, the resolver (a web reader, no tools) receives the case context ("used,
    ~2015, diesel") plus search snippets. It returns `VariantIdentity` with
    `generation_years_from/to`, `alternatives[]` and `certainty`. Code validates that the
    requested year is within the generation years; otherwise it asks.
  - **De-duplication**: `canonical_key` normalizes aliases (`VW`→`Volkswagen`,
    `Land Rover Prado`→`Toyota Land Cruiser Prado`, generation codes `J150`/`150`,
    `L320`/`Mk1`). Before insert, a fuzzy match (≥92) on the same make, model, generation and
    powertrain merges into the existing variant (FR-024).
  - **Alias table**: `config/aliases.yaml`, extendable.
- **Rationale**: Fixes the 150/250 confusion and the duplicate Range Rover Sport rows.

## R7. Criteria dictionary v1

- **Decision**: `config/criteria.yaml`, versioned (`criteria_version: 1`). Each criterion has:
  key, label, definition, inputs (attributes or derived values), a scale (linear lo/hi or a
  categorical map), a minimum-data rule, and default weights per persona. Keys:

  | Key | Inputs | Scale |
  |---|---|---|
  | `reliability` | issues (recurring count, severity), reliability statistics | lower is better |
  | `ownership_cost` | 5-year TCO per year | lower is better |
  | `purchase_price` | official price (or original price class for used) | lower is better |
  | `practicality` | boot, seats, rear space if sourced | higher is better |
  | `comfort` | review pros/cons tagged "comfort", ride/NVH | review balance |
  | `performance` | simulated 0–100, 400 m, power-to-weight | higher is better |
  | `driving_fun` | power-to-weight, drivetrain, weight, review tags "handling/fun" | composite |
  | `traction_all_weather` | drivetrain, review tags | categorical |
  | `offroad_mountain` | drivetrain, low range, ground clearance, torque-to-weight | composite |
  | `efficiency` | consumption or energy use | lower is better |
  | `safety` | Euro NCAP stars if sourced | categorical |
  | `status` | price class + segment + brand positioning (premium/mainstream/budget, from sources), age-adjusted for used cars (FR-028) | composite |
  | `engineering` | specific output, technology features from sources, data completeness | composite |

  **Persona default weights** (editable):
  - **performance enthusiast**: performance 35, driving_fun 30, traction 15, ownership_cost 10,
    reliability 10;
  - **everyday/family buyer**: reliability 30, ownership_cost 25, practicality 20, comfort 15,
    efficiency 10;
  - **expert**: engineering 35, performance 20, reliability 20, driving_fun 15, efficiency 10;
  - **unknown**: balanced.

  Wishes adjust weights (strength low, medium or high → +10, +20 or +30 points), and the result
  is normalized to 100%. The minimum covered weight to rank a car is 60% (FR-027).
- **Review-tag scoring** (comfort, fun) uses only excerpt-validated review items tagged by the
  extractor. The score is the share of recurring positive vs negative tagged items, and the
  minimum is the review minimum.
- **Rationale**: Deterministic and explainable (constitution III). Weights are visible and
  adjustable (FR-026).

## R8. Case-driven research planner and areas

- **Decision**: The pure function `domain.research_plan.plan(case, cache_state, depth) ->
  ResearchPlan`. It maps criteria and persona sections to **areas**:
  - `specs` (Tier 1, plus Tier 2 for experts);
  - `measured`;
  - `price`;
  - `maintenance`;
  - `reviews` (expert, owner);
  - `reliability` (issues, statistics);
  - `manufacturer`;
  - `used_issues` (only for used cars: generation and age issues, big-ticket items).

  Each area has query templates (EN plus ES; RU sources are not targeted), an extraction schema,
  a validation rule, a minimum evidence rule (FR-019) and a freshness period (FR-021). Gap rounds
  per depth: Quick 0, Standard 1, Deep 2 (FR-020). Gaps are recomputed after each round from the
  selected values and the section minimums.
- **Extraction schemas** (all excerpt-validated, web readers, no tools): `SpecClaims` (from the
  demo), `MaintenanceItems`, `ReviewItems` (polarity, tag, reviewer type), `IssueItems`
  (component, description, age or mileage window, severity hint), `ReliabilityStats` (source,
  metric, value, year), `ManufacturerFacts`, `PriceClaims`.
- **Full text**: Tavily search with `include_raw_content`, plus `extract(advanced)` for
  snippet-only results (demo fix). Direct fetch (pasted URLs, manufacturer pages) goes only
  through `infrastructure/fetch.py`: deny-list check first, robots.txt (cached per host 24 h),
  per-host rate limit (default 1 request / 2 s), timeout 15 s, max 3 MB, HTML/PDF/text only.
- **Validator role** (constitution XI): after excerpt validation, pages whose variant match is
  uncertain (mentions several generations, engines or years; or the page title lacks the
  generation) go to the `validator` role (web reader, no tools). Input: variant identity and the
  claims with excerpts; output per claim: `SAME_VARIANT | OTHER_VARIANT | GENERATION_WIDE |
  UNCLEAR` with a reason. Only `SAME_VARIANT` claims are stored as variant values;
  `GENERATION_WIDE` lowers confidence to LOW (FR-018); the others are rejected and counted.
- **Brand positioning** (status, FR-028): `ManufacturerFacts` with kind `MARKET_POSITION` must
  state premium / mainstream / budget in the excerpt; the code maps it to `brand_positioning`.
  Without such a fact, the status indicator is "insufficient data".
- **Issue severity** (deterministic, `domain/reliability.py`, config `config/severity.yaml`):
  HIGH = safety or engine/gearbox/battery failure, or repair > €1,500 if a cost is quoted;
  MEDIUM = component failure requiring a workshop (e.g. turbo, DPF, injectors, suspension);
  LOW = trim, electronics nuisance, noise. Keyword lists are versioned in config.
- **Freshness per area** (FR-021): specs, measured, engineering, practicality 365 d;
  maintenance 365; reliability, used_issues, reviews 180; price 30; manufacturer 30.
- **Early warnings** (edge cases): car older than 25 years → notice "sources are scarce, sections
  may be insufficient"; variant not sold in Spain (no ES price/market source) → notice with the
  market difference. Both are deterministic rules in `domain/research_plan.py`.

## R9. TCO engine (deterministic)

- **Decision**: The pure function `domain.tco.compute(car, case, rates) -> TcoEstimate`. Items:
  - **maintenance**: from the sourced schedule (interval and items), with cost per published menu
    or labour hours × rate (assumption);
  - **energy**: consumption × annual km × price;
  - **tyres**: tyre size class × life km;
  - **road tax (IVTM)**: by fiscal horsepower if a rate is found, otherwise "not included";
  - **used cars**: (a) sourced big-ticket items whose age or mileage window falls in the next 5
    years, and (b) a base reserve from `config/rates.yaml` (age band × class table). They are
    shown separately (FR-035).

  Each item has `basis: SOURCED | ASSUMPTION` and inputs. The output is annual and 5-year
  totals.
- **Default base reserve table** (€ per year, assumption, editable):

  | Age band | small | compact | mid/large | premium/SUV/4x4 |
  |---|---|---|---|---|
  | 0–4 years | 100 | 150 | 200 | 300 |
  | 5–9 years | 300 | 400 | 550 | 800 |
  | 10–14 years | 500 | 650 | 900 | 1300 |
  | 15+ years | 700 | 900 | 1200 | 1800 |

## R10. Agents: hub, persona reporters, explainers

- **Decision**: These are the LLM roles, each with its own prompt file in
  `orchestration/prompts/`, versioned:

  | Role | Kind | Tools |
  |---|---|---|
  | `interpreter` (hub) | analyst | none (structured output) |
  | `asker` (hub) | analyst | none; phrases the template questions in the user's language |
  | `resolver` | web reader | none |
  | `extractor_*` (per area) | web reader | none |
  | `validator` | web reader | none (variant-match judgement for ambiguous pages only) |
  | `reporter_{expert,performance,buyer,balanced}` | analyst | scoped MCP tools |
  | `answerer` (follow-ups, from context) | analyst | read-only MCP tools |
  | `general` | analyst | none; general knowledge, labelled |

  **Persona reporters** share one factory. They differ in prompt, section order, allowed tools
  and word budget.
  - **expert**: engineering, manufacturer, specs, metrics, reliability, TCO.
  - **performance**: race, metrics, specs, driving_fun, reliability, TCO.
  - **buyer**: verdict, criteria scores, reliability, TCO, practicality, reviews, specs.
- **MCP scoping**: a reporter gets read and compute tools only; no tool fetches web content
  (constitution VIII).
- **Rationale**: This gives constitution VI specialization without a zoo of agents. The
  deterministic block composition decides **what is shown**, and the agents write
  **explanations**.

## R11. Numbers guard (kept from the demo)

- **Decision**: The demo `check_numbers` is kept, with a numeric tolerance of 0.5% / ±0.05. The
  allowed set = numbers in the blocks + tool outputs + the case file (budget, age, mileage).
  Removed sentences are counted in a notice (FR-031).

## R12. Usage and cost accounting, estimation, caps

- **Decision**:
  - A `UsageCallbackHandler` (LangChain callbacks) is attached to **every** chat model created by
    the gateway, including those inside `create_agent`. It records `llm_calls` with role, model,
    tokens and cost from `config/prices.yaml`. Tavily calls are recorded as `search_calls`
    (credits → €).
  - **Estimation**: `domain.cost.estimate(plan) = Σ areas × cars × (expected_calls ×
    avg_tokens × price) + search credits`. Averages are learned from `llm_calls` history per
    area, with fallbacks from config.
  - **Hard cap**: the `TurnBudget` stops new LLM and search calls at €1.00. In-flight calls
    complete, and the turn completes with the data it has (FR-041).

## R13. Transport and protocol v2

- **Decision**: The demo WebSocket protocol is extended (`contracts/chat-protocol.md`).
  - New server messages: `case_file` (after each change), `confirm_request` (variants or cost,
    with options), `usage`.
  - New client messages: `confirm`, `cancel`.
  - Events are stored in `turn_events` with a seq per chat. On reconnect the client sends
    `last_seq` and missed events are replayed.
  - REST is added for the case file (GET/PATCH), the criteria dictionary (GET) and the chats list
    (GET).
- **Rationale**: These are needed for FR-006, FR-009, FR-041, FR-043 and FR-045. The demo
  transport already works; this is backward-compatible.

## R14. Restart recovery and cancellation

- **Decision**:
  - Research work runs as `research_jobs` rows (car × area × round, status). Workers mark jobs
    done after the validated data is committed.
  - On startup, chats whose last checkpoint is mid-turn (not at END or an interrupt) are resumed
    with `graph.ainvoke(None, thread)`. Research nodes skip jobs already done (FR-044, SC-013).
  - **Cancel**: the turn cancel flag is checked between jobs, and the asyncio task is cancelled.
    Validated data stays (FR-043).

## R15. Frontend evolution (reuse the demo app)

- **Decision**: Keep the Vite/React/TS app and add:
  - a **case file panel** (collapsible sidebar on desktop, sheet on phone; editable fields,
    weight sliders → PATCH);
  - **confirmation cards** (variant options as buttons with a free-text reply option; a cost
    card with estimate and Run/Skip);
  - new blocks: `criteria_scores` (replaces `profile_scores`), `tco`, `reliability`, `reviews`,
    `engineering`, `manufacturer`, `case_summary`;
  - a chat list (history page);
  - a cancel button during research.

  Block order is decided by the backend per persona (FR-030). The frontend renders in the given
  order.

## R16. Persistence and migrations

- **Decision**: Introduce **Alembic** now. The baseline migration covers the demo tables and the
  new ones. The dev DB stays embedded Postgres (pgserver, `scripts/dev.sh`); deployment uses
  Docker Compose (Postgres 16). The checkpointer tables are created by `checkpointer.setup()` and
  excluded from Alembic (ADR-011).

## R17. Testing strategy (what the demo lacked)

- **Decision**:
  1. **Unit** (pure): `casefile.apply`, `policy.decide` (one test per rule), `research_plan`,
     criteria scoring, TCO incl. the reserve table, resolution year-range validation, alias and
     de-duplication, cost estimation, plus the existing demo domain tests.
  2. **Graph mechanics** with a **scripted fake LLM** (returns predefined structured outputs per
     role) and a fixture search provider. They verify interrupts, resume, persistence across
     turns (new graph instance), cancel, restart and usage counting.
  3. **Golden dialogues** (`tests/golden/*.yaml`), FR-046:
     - **replay mode** in CI: recorded LLM outputs (cassettes) with fixtures;
     - **live mode** (`-m live`, opt-in, about €0.50 per full run): real models and search.
       Assertions are on the case file, the action and the variants, not on exact prose.
  4. **Contract**: the WS message schemas are shared and validated on both sides. A frontend
     vitest suite validates recorded backend payloads (as done in the demo).
  5. **Quality gates**: ruff (line length 120), mypy strict for `domain/`, import-linter layer
     contract.
- **Rationale**: The demo's conversation failures were invisible to its tests. Golden dialogues
  make them regressions.

## R18. Code organization and cleanup of the demo

- **Decision**:
  - Split `agents/graph.py` into an `orchestration/` package (state, nodes, graph, prompts as
    files).
  - Move domain rules into `domain/` modules (casefile, policy, criteria, tco, research_plan,
    cost).
  - Remove cross-module private imports and replace the MCP tools global with dependency
    injection.
  - Fix the 28 ruff findings and the 2 complexity hotspots (`_simulate_one`, `_research_round`).
  - Keep the demo's tested domain modules (units, specs, evidence, dragrace, scoring → criteria).
