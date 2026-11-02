# Phase 0 Research: Ultimate Car Battle (AutoMind MVP)

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-11-01

Each item: **Decision** / **Rationale** / **Alternatives considered**. Version numbers are the
latest known at planning time and MUST be re-checked against PyPI/npm when the lockfiles are
created.

---

## R1. Orchestration engine and versions

- **Decision**: LangGraph 1.2.x with `langgraph-checkpoint-postgres` 3.x (`AsyncPostgresSaver`).
  Graph state is a `TypedDict` with `Annotated` reducers; domain contracts are Pydantic v2 models.
  Human approval uses `interrupt()` and is resumed with `Command(resume=...)`. Dynamic fan-out
  uses `Send`. Verification and analysis are compiled subgraphs. Every node that calls external
  services has a `RetryPolicy`, and every graph has a `recursion_limit`.
- **Rationale**: Required by the constitution (ADR-002, ADR-006, ADR-007, ADR-011). The 1.x line
  is stable. The Postgres checkpointer gives restart recovery (FR-033) without extra
  infrastructure, and 3.2 adds `prune` to keep checkpoint tables small.
- **Important behavior**: on resume, LangGraph **re-runs the interrupted node from its start**.
  Nodes that call `interrupt()` therefore MUST be side-effect free before the interrupt call
  (approval node only builds and returns the plan payload).
- **Alternatives**: custom state machine plus a job queue (rejected: duplicates checkpointing and
  interrupts); Temporal (rejected: extra service, against YAGNI).

## R2. Background execution, resume, and cancellation

- **Decision**: An in-process `ResearchRunner` inside the FastAPI app runs each research as an
  `asyncio.Task` that executes the graph with `thread_id = research_id`. On startup, the runner
  looks for researches in `RUNNING`, `VERIFYING`, or `ANALYZING` state and continues them from
  their last checkpoint. Researches in `AWAITING_APPROVAL` stay paused until approval.
  Cancellation sets a cancel flag in the DB and cancels the task. Nodes check the flag before
  starting new work, and the research is marked `CANCELLED`. Concurrency is bounded by an
  `asyncio.Semaphore` (graph `max_concurrency` config) and an app-level cap on simultaneously
  running researches (default 2).
- **Rationale**: One local user and a few concurrent researches do not justify Celery, RQ, or
  Redis (constitution X). Checkpoints make the task stateless across restarts. Completed worker
  tasks are not re-run because their results are already written to the checkpoint (SC-011).
- **Alternatives**: Celery/Redis (rejected: new infrastructure); LangGraph Platform/Server
  (rejected: hosted dependency, licence and cost for a local MVP).

## R3. LLM gateway (OpenAI + Anthropic)

- **Decision**: An `LLMGateway` port in the application layer. The infrastructure
  implementation uses LangChain `init_chat_model("<provider>:<model>")` with
  `langchain-anthropic` and `langchain-openai`. Each graph role (`variant_resolver`, `planner`,
  `spec_extractor`, `issue_extractor`, `verifier`, `report_writer`) maps to
  `{provider, model, temperature, max_tokens, timeout}` in `config/models.yaml`, and each role can
  be overridden by environment variable. All calls use structured output (Pydantic schemas). A
  callback records provider, model, role, input and output tokens, latency, and estimated cost
  (from a price table in the same config) into `llm_calls`. A per-research **call budget**
  (FR-036) is enforced by the gateway, which raises `BudgetExceeded` so the graph can finish
  gracefully.
- **Default models**: Anthropic `claude-sonnet-5-5` for extraction and verification and
  `claude-haiku-5-5` for cheap classification. An OpenAI profile is provided with the current
  GPT models, and model IDs come from config only (constitution VII).
- **Rationale**: Keeps provider SDKs out of domain and application code, allows a different
  provider per node, and gives one place for budgets and cost accounting.
- **Alternatives**: LiteLLM proxy (rejected: an extra service); calling the raw SDKs directly
  (rejected: more code for structured output and retries).

## R4. Web search and content retrieval

- **Decision**: A `SearchProvider` port with three adapters:
  1. **Tavily** (default): search, plus its extract endpoint for page text. It has an official
     LangChain integration and a free tier of about 1,000 credits a month.
  2. **Brave Search API** (alternative): about $5 per 1,000 requests with monthly free credit. It
     uses an independent index.
  3. **FixtureProvider**: local JSON/HTML fixtures for tests, evaluation, and offline demos.

  Page text comes from the provider's extract endpoint, or from a direct `httpx` fetch **only**
  for domains on an allow-list (manufacturer press and media sites). Direct fetches check
  robots.txt and use a timeout of `min(limits.request_timeout_s, 15 s)`, a 2 MB size limit, and
  per-domain rate limits. Search and extract calls use `limits.request_timeout_s`. Specification
  databases with restrictive terms are used only through search snippets and cited links, never
  scraped (constitution VIII, FR-008).
- **Source typing**: a domain-to-source-type registry (`config/sources.yaml`) classifies sources
  as `manufacturer`, `instrumented_test`, `publication`, `encyclopedia`, or `spec_database`.
  This drives the authority order (FR-017) and confidence (FR-018). Unknown domains default to
  `publication` with a lower rank flag, and the registry can be extended without code changes.
- **Rationale**: Search APIs designed for agents avoid building a crawler. Page text, not the
  search call, is the main token cost, so pages are trimmed to relevant sections before
  extraction.
- **Alternatives**: Exa (good semantic search, a possible later adapter); Serper (cheap Google
  results but no extraction); a custom crawler (rejected: legal and maintenance risk).

## R5. Claim extraction and anti-hallucination guard

- **Decision**: The worker retrieves documents and stores their text as `research_artifacts`
  (content-addressed files under `data/artifacts/`, with metadata in the DB). The extraction LLM
  receives one document at a time, wrapped in clear `<untrusted_document>` delimiters, has **no
  tools**, and must return `ExtractedClaim{attribute, raw_value, raw_unit, excerpt,
  scope}`, where `scope` is VARIANT, GENERATION, or ENGINE. Provenance is then assigned by code,
  not by the LLM: `assign_provenance(source_type, attribute)` (FR-009). A deterministic **excerpt validator** checks that the excerpt appears in the
  stored document text (whitespace-normalized) and that the raw value appears inside the excerpt.
  Claims that fail are dropped and logged as `unsupported` (FR-015).
- **Rationale**: Turns "never invent data" into a mechanical check. The LLM can only pass on
  values that literally appear in the source. This is also the main defence against prompt
  injection: untrusted text can at worst produce rejected claims, never tool calls.
- **Alternatives**: trusting LLM output (rejected: constitution I); regex-only extraction
  (rejected: too brittle across languages and layouts, though regexes are used for unit parsing).

## R6. Vehicle identification and catalog

- **Decision**: Two-stage resolution.
  1. Look up the free text in the **local catalog** (FR-040) using normalized-name fuzzy matching
     (`rapidfuzz`).
  2. On a miss, or if the user asks for a fresh lookup, the `variant_resolver` LLM proposes up to
     5 candidate variants from search results. Each candidate carries its evidence links and an
     ambiguity flag.

  Candidates are deduplicated against the catalog by a canonical key
  `(make, model, generation_code, variant_name, powertrain, model_year_from, market)`. The plan
  presents the top candidate and the alternatives. Catalog entries with data older than
  `CATALOG_FRESHNESS_DAYS` (90) are marked stale.
- **Rationale**: There is no free, authoritative EU variant database. A catalog that grows from
  the user's own approved research gives fast, cheap repeat comparisons and stable variant IDs.
- **Alternatives**: a commercial vehicle database such as JATO or DAT (rejected for the MVP: cost
  and licensing; can be added later as a provider); a hand-curated seed catalog (only the
  evaluation reference set, R12, is curated).

## R7. Units and normalization

- **Decision**: An in-house `domain.units` module with explicit `Quantity(value: Decimal, unit:
  Unit)` and conversion tables: kW, hp (mechanical), PS (metric), and bhp treated as hp; N·m and
  lb·ft; kg and lb; km/h and mph; mm and in; L and cc; kWh. Canonical storage is SI (kW, N·m,
  kg, m, s); the display layer shows both kW and hp. Weight definitions are an enum:
  `EU_WITH_DRIVER_75KG`, `DIN_WITHOUT_DRIVER`, `UNKNOWN`. When comparing weights, DIN values are
  converted to EU by adding 75 kg, and the conversion is labeled "derived". Ambiguous "hp" from
  European sources is flagged as a unit issue when it differs from the PS value by the PS/hp
  ratio.
- **Rationale**: A small, fully tested table (constitution III, IX) avoids a heavy dependency.
  `Decimal` avoids float drift in stored values. Simulation converts to float internally, with a
  fixed step so results stay deterministic.
- **Alternatives**: `pint` (rejected: large and its behavior is not fully controlled for unit
  aliases; may be revisited).

## R8. Conflict tolerance, resolution, and confidence

- **Decision**: Pure domain functions:
  - `detect_conflicts(claims, tolerances)`: relative tolerance of ±2% for power and torque, ±3% for
    mass and dimensions, ±0.2 s for 0–100 km/h claims, exact match for categorical values.
  - `resolve(conflict)`: applies the FR-017 rule (authority order, then majority of at least two
    independent same-rank sources, otherwise unresolved). "Independent" means a different
    registrable domain.
  - `confidence(value)`: applies the FR-018 rule (High / Medium / Low) and returns the rule ID.
    "Agree" means within the same tolerance used for conflicts, from different registrable
    domains. "Weak or indirect" means `evidence.snippet_only` or `claim.scope` is GENERATION or
    ENGINE.

  All three versions are stamped on results (`rules_version = "1.0"`).
- **Rationale**: Deterministic, explainable, and directly testable against the spec's acceptance
  scenarios.
- **Alternatives**: an LLM judging conflicts (rejected: constitution III).

## R9. Drag race simulation model v0.1

- **Decision**: `domain.simulation.dragrace.v0_1`, a pure function
  `simulate(vehicle_inputs, race_settings, assumptions) -> RaceResult`.
  - **Integration**: fixed step dt = 0.005 s, semi-implicit Euler, stopping at 400 m (60 s safety
    cap). It records samples every 0.05 s and finds the times for 100 and 200 km/h by linear
    interpolation. Output is rounded to 0.01 s and 0.1 km/h.
  - **Forces**: `F_net = min(F_power, F_traction) − F_aero − F_roll`, and `a = F_net / m_eff`.
    - `m_eff = m × (1 + rotational_inertia_factor)`, using 0.05 for EVs and 0.08 for ICE.
    - `m = curb_mass_EU + extra_load + 0` (the EU curb mass already includes a 75 kg driver).
    - `F_aero = ½ ρ Cd A v²`, where ρ comes from the ideal gas law using temperature and
      altitude (ISA lapse rate).
    - `F_roll = Crr × m × g`, with Crr = 0.012 on a dry surface and 0.014 on a wet one.
    - `F_traction = μ × m × g × driven_axle_load_fraction`, with μ = 1.0 dry and 0.7 wet.
      Static axle fractions come from weight distribution, or class defaults: FWD 0.60 front and
      RWD 0.47 rear (plus 0.05 dynamic transfer bonus for RWD, −0.05 for FWD); AWD 1.0.
  - **ICE**: `F_power = η × P_max × k_ice / max(v, v_min)`. Here η = 0.85 drivetrain efficiency,
    and `k_ice = 0.80` for manuals or 0.85 for automatics and DCTs. `k_ice` is the average
    fraction of peak power available across the gear spread, including shift losses. `v_min` is
    2 m/s, which avoids the singularity; at low speed the force is bounded by traction.
  - **EV**: `F_power = min(F_max, η × P_max / v)`, where η = 0.90 and
    `F_max = η × P_max / v_base`. `v_base` defaults to 0.35 × top speed (assumption) unless motor
    data provides it.
  - **HEV/PHEV**: the combined system power is used with the ICE formula, and the result is
    flagged "combined system power simplification".
  - **Assumption defaults** come from `domain.simulation.assumptions` by body class (Cd, frontal
    area A): hatchback 0.31 and 2.2 m²; sedan 0.28 and 2.2 m²; SUV 0.34 and 2.6 m²; coupe 0.30
    and 2.0 m²; wagon 0.30 and 2.25 m². Every default used is listed in the result with the label
    "assumption" (FR-027).
  - **Calibration**: `tests/eval/test_dragrace_calibration.py` compares simulated 0–100 km/h with
    measured values from the reference set. SC-009 needs at least 80% of vehicles within ±15%.
    `k_ice` and `v_base` may be tuned only by releasing a new model version (v0.1.x).
- **Rationale**: This is the simplest physically meaningful model that needs only Tier 1 data,
  covers ICE, EV, and hybrids, and is fully deterministic.
- **Alternatives**: a gear-by-gear model with a torque curve (deferred to v0.2, since it needs
  Tier 2 data); an LLM estimate (forbidden).

## R10. Live progress (SSE)

- **Decision**: Graph nodes and the runner emit domain events (`research.state_changed`,
  `task.updated`, `plan.ready`, `conflict.detected`, `report.ready`, `usage.updated`,
  `research.failed`). Each event is written to `research_events` with a per-research
  monotonically increasing `seq`, then pushed to an in-memory pub/sub. The SSE endpoint (via
  `sse-starlette`) sends `id: <seq>`, and on reconnect it replays events with
  `seq > Last-Event-ID` from the DB before switching to live events. A heartbeat is sent every
  15 s. Event payloads are API DTOs, never graph state (constitution V).
- **Rationale**: Meets SC-010 (visible within 5 s) and allows reconnection without missing state
  (Story 4, scenario 2).
- **Alternatives**: WebSockets (unnecessary; the stream is one-way); polling (worse UX, though
  the UI falls back to `GET /researches/{id}` after reconnect failures).

## R11. Persistence

- **Decision**: PostgreSQL 16 in Docker Compose. Domain tables use SQLAlchemy 2.x (async) with
  `asyncpg`, and migrations use Alembic. The LangGraph checkpointer uses its own `psycopg` 3
  connection pool and tables, created by `checkpointer.setup()` and never touched by Alembic
  (ADR-011). Large document text is stored on the filesystem (`data/artifacts/<sha256>.txt`),
  referenced from the DB; graph state stores only IDs (constitution VI).
- **Rationale**: Matches the constitution's stack. The two drivers are an accepted consequence of
  the official checkpointer depending on psycopg.
- **Alternatives**: SQLite (rejected: the constitution requires PostgreSQL, and the official
  checkpointer for production use is Postgres); storing text in DB `bytea` (possible later; files
  are simpler for inspection).

## R12. Testing and evaluation strategy

- **Decision**:
  - **Unit** (`pytest`, `hypothesis`): units, normalization, conflicts, resolution, confidence,
    derived metrics, rankings, simulation (property tests: more power gives a time that is never
    slower; same inputs give identical output; wet is never faster than dry).
  - **Graph** (`pytest-asyncio`, FixtureProvider, fake LLM with recorded structured outputs,
    `MemorySaver` and Postgres saver): the 10 required scenarios from the constitution.
  - **Integration** (Postgres from docker compose, `respx` for HTTP): repositories, the SSE
    replay, and the provider adapters, using recorded responses.
  - **Contract**: generate OpenAPI from FastAPI and diff it against
    `contracts/openapi.yaml`; the frontend Zod schemas are tested against example payloads.
  - **Evaluation** (`tests/eval`, opt-in, real providers): a reference set of at least 20
    vehicles in `eval/reference_vehicles.yaml` (combustion, EV, hybrid) with known Tier 1 specs
    and published instrumented 0–100 and 400 m figures. It measures SC-004, SC-005, SC-006, and
    SC-009, plus cost and duration.
  - **Frontend**: `vitest` with Testing Library for components, and one Playwright smoke test
    against a backend in fixture mode.
- **Rationale**: Constitution IX; makes the success criteria measurable.

## R13. Frontend

- **Decision**: Vite with React and TypeScript (strict mode), TanStack Query for server state,
  Zustand for UI-only state (current step, race settings draft), React Router, ECharts (through
  `echarts-for-react`) for speed, distance, and acceleration charts, Tailwind CSS, and Zod for
  validating every API response. The race animation uses a simple canvas or SVG and replays the
  stored time series (no physics in the browser). There are five pages: New Research, Research
  (plan approval, progress, results tabs), Drag Race, History, and Catalog (read-only list,
  minimal "My Garage").
- **Rationale**: This is the constitution's stack. The frontend renders backend data only
  (constitution V).

## R14. Observability and security

- **Decision**: `structlog` JSON logs with `research_id` and `task_id` context; LangSmith tracing
  turned on by `LANGSMITH_TRACING=true`; an `llm_calls` table for token and cost accounting;
  and a `/api/v1/health` endpoint. Secrets come only from `.env`, which is git-ignored, and
  `.env.example` is committed. Without login, CORS is restricted to the Vite origin and the API
  binds to `127.0.0.1` by default. No AI role has tools: search, extract, and fetch are plain code paths
  in `ResearchService`, and every AI role (resolver, planner, extractors, verifier, report writer)
  only receives text and returns structured output. Web text is always wrapped in
  `<untrusted_document>` delimiters (least privilege, constitution VIII).
- **Rationale**: Constitution VII and VIII; FR-037.
