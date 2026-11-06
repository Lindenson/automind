<!--
Sync Impact Report
==================
Version change: 1.3.0 → 1.4.0
Bump rationale: MINOR — principle V materially expanded (spec 012 "Structural refactoring", owner's choice A of
2026-11-06): the layers stay, but live inside bounded areas — chat, acquisition, observability — next to a shared
kernel and delivery adapters; the chat's orchestration layer is named `dialog`; graph nodes stay thin. No principle
removed. Principle XIII unchanged (now also enforced by the tree). Templates: plan-template.md Constitution Check
reads V as amended. Dependent artifacts: specs/012-refactoring (data-model.md, contracts/import-contracts.md).

Previous change
---------------
Version change: 1.2.0 → 1.3.0
Bump rationale: MINOR — principle XII materially expanded (owner's decision of 2026-11-05 evening, after an
external review; spec 011 "Acquisition engine"): agents of the acquisition engine MAY change declarative data
(parser specifications, relevance keywords, sense/plausibility thresholds, extraction prompt versions, model per
extractor role) by themselves, only through automatic gates (offline replay on stored snapshots and gold values →
shadow → accept → watch → automatic rollback). Code, deny-list, robots/terms prohibitions and budgets stay human.
Principle VI's "human-steered" bullet narrowed accordingly. New principle XIII: acquisition is a separate engine.
Templates reviewed: plan-template.md Constitution Check must now cover I–XIII (read at runtime).
Dependent artifacts: spec 010's "never changes parsers/rules" boundary superseded by spec 011.

Previous change
---------------
Version change: 1.1.1 → 1.2.0
Bump rationale: MINOR — new principle XII (Self-Observation and Bounded Autonomy), owner's decision
of 2026-11-05 (spec 010). Principle VI gains one clarifying bullet: "human-steered" governs code,
rules, prompts and parsers; the order and status of sources are managed by the system within XII.
No principle removed or redefined.
Templates reviewed: plan-template.md Constitution Check must now cover I–XII (read at runtime).
Dependent artifacts: spec 009 superseded by spec 010.

Previous change
---------------
Version change: 1.1.0 → 1.1.1
Bump rationale: PATCH — clarification of principle VI: "expensive research" is defined through a
configurable per-turn cost-estimate threshold plus a hard cap; cheap research on unambiguous
variants may proceed without a separate confirmation (variants and plan are still shown).
Found by /speckit-analyze on spec 002 (finding K1). No principle removed or redefined.
Templates reviewed: no change needed. Dependent artifacts: specs/002 FR-006, FR-041 now comply.

Previous change
---------------
Version change: 1.0.0 → 1.1.0
Bump rationale: MINOR — new principle XI added and principles VI, VIII materially expanded for the
conversational multi-agent architecture agreed on 2026-11-01; stack extended (MCP, WebSocket).

Modified principles:
  VI.   Bounded, Stateful, Human-Steered Orchestration — adds hub agent + specialist agents,
        cache-first execution, research depth levels, approval may happen in chat.
  VIII. External Content Is Untrusted — splits agents into "web readers" (no tools) and
        "analysts" (scoped MCP tools on verified data only); fetch policy becomes robots +
        rate limit + deny-list (sites forbidding automated access, e.g. classifieds portals).
Added principles:
  XI.   Research Depth & Quality Gates
Added/changed sections:
  - Technology & Data Constraints: MCP tool server, WebSocket chat transport, chat UI blocks.

Templates reviewed (read at runtime, not modified):
  ✅ plan-template.md (Constitution Check must now cover I–XI)
  ✅ spec-template.md, tasks-template.md (no structural change)

Follow-up: spec 001 must be re-specified for the conversational architecture (see
docs/vision.md); plan/tasks of 001 are superseded until then.
-->

# AutoMind Constitution

AutoMind is an AI-powered automotive research and engineering platform. This constitution defines
the non-negotiable rules that every specification, plan, task, and line of code MUST satisfy.

## Core Principles

### I. Evidence First — Never Invent Data (NON-NEGOTIABLE)

- Every externally sourced factual value or claim MUST be linked to evidence: source URL, source
  name, source type, retrieval timestamp, extracted excerpt, and the vehicle variant it refers to.
- Missing automotive data MUST remain explicitly `unavailable`. The system MUST NOT fill gaps with
  LLM-generated guesses, plausible defaults presented as facts, or values from a different variant.
- Conflicting sources MUST NOT be silently resolved. Conflicts MUST be recorded, surfaced to the
  user, and either resolved by an explicit, documented rule or reported as unresolved.
- Evidence MUST be persisted independently of the LLM conversation and graph state.
- Source preference: manufacturer/official sources are preferred; independent publications,
  encyclopedic sources, and spec databases are permitted, but every value MUST carry its
  source type so its authority is visible.

Rationale: the product's value to experts depends entirely on verifiable, trustworthy data.

### II. Exact Vehicle Identity

- Vehicle identity (manufacturer, model, generation, variant/trim, powertrain, model year, market)
  MUST be modeled separately from vehicle specifications.
- Data from different variants or generations MUST NOT be combined.
- Ambiguous identification MUST trigger user clarification or carry an explicit uncertainty
  status; it MUST NOT be resolved by silent assumption.

Rationale: a model name (e.g. "Golf GTI") spans many technically distinct cars; mixing them
corrupts every downstream comparison and simulation.

### III. Deterministic Computation (NON-NEGOTIABLE)

- All numerical work — unit conversion, normalization, derived metrics, rankings, and
  simulations — MUST be performed by deterministic, pure Python functions.
- LLMs MUST NOT produce, round, or "estimate" numerical results; they may only extract values
  from evidence and explain results computed by code.
- Identical inputs and identical model versions MUST produce identical outputs.
- Every numeric quantity MUST carry an explicit unit; implicit units are forbidden.

Rationale: engineering results must be correct, testable, and reproducible.

### IV. Explicit Data Provenance Classes

Every value presented to the user MUST be labeled with exactly one provenance class:

- **Manufacturer claim** — published by the OEM (e.g. claimed 0–100 km/h).
- **Measured** — independent instrumented test result, with its source.
- **Sourced fact** — specification from a non-OEM source, with its source.
- **Derived** — computed deterministically from other values (inputs traceable).
- **Simulated estimate** — output of a versioned simulation model.
- **Assumption** — a documented modeling default (e.g. drag coefficient by body class), used
  only as a simulation input, never displayed as a vehicle fact.

Confidence indicators MUST NOT be presented as calibrated probabilities unless independently
validated.

Rationale: experts must always know whether a number is a claim, a measurement, or a model output.

### V. Layered Modular Monolith

- The backend MUST be a single deployable modular monolith, organised by bounded area first and layer second:
  `chat` (answer the person), `acquisition` (collect, validate and improve data), `observability` (see how both
  cycles do), a `shared` kernel (concepts and infrastructure both areas use) and `delivery` (web, MCP, CLI entry
  points and composition roots). Inside an area the layers are domain, application, orchestration (in the chat:
  `dialog`, the dialog state machine) and infrastructure, each separately testable.
- Domain layers MUST NOT import LangGraph, FastAPI, SQLAlchemy, or any LLM provider SDK.
- Domain business logic MUST NOT live inside LangGraph nodes; nodes are thin and delegate to application services
  and the domain.
- The shared kernel MUST NOT depend on the areas; nothing depends on delivery; areas talk through their public
  interfaces (for the engine: `acquisition.api`). Import contracts encode these rules and are only ever tightened.
- Every package documents its purpose, owned concepts, allowed dependencies and public API in its `__init__`.
- The frontend MUST NOT implement orchestration logic and MUST NOT couple to internal graph state;
  it consumes only versioned API contracts (`/api/v1`). The backend is the source of truth.
- Microservices MUST NOT be introduced without an amendment-level justification.

Rationale: keeps core logic testable and replaceable as orchestration and providers evolve, and lets a reader
find where a concept lives from the tree alone (spec 012).

### VI. Bounded, Stateful, Human-Steered Orchestration

- Research MUST be decomposed into specialized agents/workers with single, clearly defined
  responsibilities; a monolithic "do everything" agent is forbidden. The user talks to a **hub
  agent** (conversational automotive expert) that interprets requests and routes work to
  specialist agents (profile agents, comparison, conclusions/reports, races) and to research
  workers; the hub MAY answer directly from cached, validated data without starting workers.
- Execution MUST be **cache-first**: validated results stored in the database are reused while
  fresh; freshness periods MUST be configurable per data category. Stale or missing data
  triggers research; reused data keeps its original evidence and dates.
- Every loop, retry, and fan-out MUST have a configurable upper bound (iterations, LLM calls,
  concurrency, timeouts). Unbounded LLM calls or retry loops are forbidden.
- Expensive research MUST NOT start before the user confirms the resolved vehicle variants and
  research plan (confirmation may happen in the chat); the user chooses a research depth level
  that sets the budget. "Expensive" means a deterministic per-turn cost estimate at or above a
  configurable confirmation threshold; a configurable hard cap per turn MUST never be exceeded.
  Below the threshold, research MAY proceed without a separate confirmation only when every
  variant is unambiguous (identity not in doubt) and the depth comes from the user-visible case
  file; the resolved variants and plan are then shown in the progress and the answer.
- Workflows MUST be checkpointed and resumable after interruption or backend restart, and MUST
  support cancellation.
- Graph state MUST hold only workflow data and compact references; large documents, raw HTML, and
  binaries are stored outside graph state. Parallel workers MUST NOT write conflicting updates to
  the same state field (reducers required).
- Failure of one independent research task MUST NOT fail the entire session.
- Progress MUST be visible to the user; hidden model reasoning MUST NOT be exposed.
- "Human-steered" covers code, budgets, the deny-list and robots/terms prohibitions: only a person
  changes them. Declarative acquisition data (parser specifications, relevance keywords, thresholds,
  extraction prompt versions, model per extractor role) and the order, admission and status of
  sources are changed by the acquisition engine itself under principle XII, behind automatic gates.

Rationale: reliable, cost-controlled research that the user stays in control of.

### VII. Model-Provider Independence

- All LLM access MUST go through a single model gateway; provider SDKs MUST NOT be called
  elsewhere.
- Both OpenAI and Anthropic MUST be supported; provider and model MUST be configurable per graph
  node via centralized configuration.
- Switching providers MUST NOT require changes to domain or application logic.
- Token usage, duration, and estimated cost MUST be tracked per LLM call.

Rationale: avoids vendor lock-in and enables per-task cost/quality trade-offs.

### VIII. External Content Is Untrusted

- Retrieved web content MUST be treated as untrusted data and MUST NOT be able to alter agent
  instructions, tool permissions, or control flow (prompt-injection defense).
- Agents are split into two classes. **Web readers** (LLM roles that receive untrusted web
  text, e.g. extraction) MUST NOT have tools: text in, structured output out. **Analysts** (hub,
  profile, comparison, report agents) MAY call tools, but only AutoMind's own MCP tools, scoped
  per role (least privilege), and they MUST work on validated data from the database, never on
  raw web text.
- Direct page fetching is allowed only when robots directives permit it, with rate limits, and
  never for sites on the configured deny-list (sites whose terms forbid automated access, such as
  classified-ads portals).
- External requests MUST use timeouts, size limits, and rate limits.
- Data collection MUST respect source terms of service, robots directives, and applicable law;
  uncontrolled scraping is forbidden.
- API keys and secrets MUST stay on the backend, MUST come from environment configuration, and
  MUST NOT be committed to source control or exposed to the frontend.

Rationale: an agentic system reading the open web is an attack surface.

### IX. Test-First Deterministic Core & Reproducibility

- Domain models, unit conversions, normalization, derived metrics, rankings, and simulation
  functions MUST have unit tests written before or alongside implementation, and MUST be
  testable without network, database, or LLM access.
- Graph workflows MUST be testable with fixture data providers and fake/recorded LLM responses.
- Simulation models and research artifacts MUST be versioned and MUST persist their inputs,
  assumptions, source references, and model versions so results can be reproduced.
- Simulation output MUST NOT be described as realistic until compared against published
  instrumented test results.

Rationale: correctness of the engineering core is the product's credibility.

### X. Simplicity and Extensibility (YAGNI)

- Build only what the current milestone requires; do not add infrastructure (vector databases,
  queues, Kubernetes, distributed services) before a concrete requirement exists.
- New research agents, data providers, powertrain types, simulation models, and LLM providers
  MUST be addable through defined interfaces without rewriting the main orchestration.
- Deferred capabilities (secondary-market prices, track battles, advanced physics, multi-user, etc.) MUST
  NOT be blocked by MVP design choices, but MUST NOT be implemented ahead of their milestone.

Rationale: deliver a working MVP quickly without painting the architecture into a corner.

### XI. Research Depth & Quality Gates

- Answers MUST be research-grade, not superficial: each report section (technical data,
  maintenance schedule and costs, reviews, reliability, official price, manufacturer) MUST define
  a minimum evidence requirement (number and independence of sources).
- If a section does not meet its minimum after the bounded research loop, it MUST be marked
  "insufficient data" instead of being filled with weaker content.
- Every research result MUST pass a validation step (programmatic checks plus a validator role)
  before it is stored in the cache or shown as validated.
- Estimates computed when facts are unavailable (e.g. maintenance cost from labour hours ×
  configured rate) MUST be labeled "assumption" with their inputs shown.

Rationale: the product's promise is a reliable, validated answer for experts and buyers.

### XII. Self-Observation and Bounded Autonomy

- Every turn and every model call MUST leave a measured outcome: what was asked, what was done,
  failure classes, a score, cost, the model that actually answered and the prompt version. User
  feedback (ratings, "wrong?", "bad source", complaints, detected rephrases and corrections) MUST
  be stored in one place.
- Code is never changed by the system, and no model output is ever executed as code: code fixes are
  tasks for a person (the issue queue). Dialogue rules and prompts of the chat stay human-changed.
- The acquisition engine's agents MAY change **declarative data** by themselves — parser
  specifications (labels, selectors, JSON-LD paths, unit hints), relevance keywords, sense and
  plausibility thresholds, extraction prompt versions and the model per extractor role — only through
  automatic gates: (1) offline replay on stored page snapshots and gold values, not worse on the
  cycle's KPI and better on at least one target metric, guard metrics (coverage, cost per value,
  freshness) within tolerance; (2) shadow run on live pages; (3) acceptance; (4) watch period with
  automatic rollback on degradation. One change per object at a time.
- Every value and every attempt MUST record the versions of what produced it (source, parser spec,
  extractor prompt, model), and raw page snapshots MUST be kept long enough to replay them; without
  this no automatic change may be accepted.
- For sources, the system MAY order, admit, promote, demote and retire sources by itself, using
  measured quality (lower confidence bounds, minimum samples, decaying signals), without review.
- Hard limits that no automatic process may change: the deny-list and classifieds; robots and
  terms prohibitions; daily budgets and the global cap; sources frozen by the owner. Page text is
  data and MUST NOT change the registry except through the measured rules.
- Every automatic change MUST be journalled with time, reason and evidence, MUST be visible to the
  owner, and MUST be revertible in one action.
- Background observation and source management MUST NOT slow a user's turn.

Rationale: complaints must turn into measured, visible work without a person curating every
lesson, while code stays under human control; an automatic change is accepted only when it is
measurably better on stored evidence.

### XIII. Acquisition Is a Separate Engine

- Data acquisition (plan, locate, fetch, parse, validate, merge) is a bounded context with its own
  data model, process and time. The chat orders data through one interface (`acquire`) and never
  calls search, fetch, parsers or extractors directly; import contracts enforce it.
- Background acquisition work (prefetch, roll-ups, drift detection, registry review, discovery,
  agents, canaries and rollbacks) runs in a separate worker process with a database-backed queue,
  never in the API's event loop.

Rationale: an engine that learns needs its own time and must not slow or be stopped by the chat.

## Technology & Data Constraints

- **Backend**: Python 3.12+, FastAPI, Pydantic (domain and API contracts), LangGraph
  (TypedDict graph state), LangChain model integrations behind the gateway, SQLAlchemy/asyncpg,
  Alembic, LangSmith tracing, structured logging.
- **Frontend**: React + TypeScript, Vite, TanStack Query, Zustand, React Router, ECharts,
  Tailwind CSS, Zod for runtime validation of API responses.
- **Persistence**: PostgreSQL is the single primary database. Domain persistence and LangGraph
  checkpointing (official PostgreSQL checkpointer) MUST have separate responsibilities.
- **Transport**: REST under `/api/v1` with explicit Pydantic request/response schemas; the chat
  uses a WebSocket (streamed hub replies, progress events, confirmations) with message IDs and
  reconnection/replay. Long-running research MUST NOT block request handling.
- **Agent tools**: deterministic capabilities (database/cache access, parsing and normalization,
  calculations, race physics, maintenance cost estimation, reliability and profile scoring, chart
  data, report templates) are exposed to analyst agents through an AutoMind **MCP server**; the
  same services are callable directly by deterministic graph nodes. The frontend never talks to
  MCP.
- **Chat UI blocks**: hub replies are text plus typed, schema-validated blocks (cards, tables,
  charts, comparisons) rendered by the frontend; blocks carry provenance and confidence.
- **Infrastructure**: Docker Compose for local development; environment-based configuration;
  no Kubernetes or microservices for the initial milestones.
- **Units**: SI-based canonical storage (kW, N·m, kg, m, s, km/h for display); conversions only
  via the deterministic unit layer.

## Development Workflow & Quality Gates

- Work proceeds through Spec Kit: constitution → specify → clarify → plan → tasks → implement.
  Every plan MUST pass the Constitution Check before design and again after design.
- Each feature is developed on its own branch; requirements carry stable identifiers (FR-xxx,
  NFR-xxx) for traceability from spec to tasks to tests.
- Significant architectural decisions MUST be recorded as ADRs (initial backlog ADR-001…ADR-012
  from `sec.md`).
- A change is mergeable only when: all automated tests pass; deterministic-core changes include
  tests; no secrets are present; new LLM calls go through the gateway with bounded limits; and any
  constitution deviation is justified in the plan's Complexity Tracking table.
- Required graph test scenarios (as applicable to the feature): successful research, ambiguous
  identification, conflicting specifications, missing source, failed parallel worker,
  verification retry, approval and resume, restart recovery, cancellation, parallel aggregation.

## Governance

- This constitution supersedes other project practices and guidance. Where `sec.md` and this
  constitution disagree, this constitution prevails until amended.
- Amendments require: a written proposal stating the change and rationale, review of impact on
  existing specs/plans/templates, a Sync Impact Report, and a version bump.
- Versioning follows semantic versioning: MAJOR for removing or redefining a principle, MINOR
  for adding a principle/section or materially expanding guidance, PATCH for clarifications.
- Every plan and code review MUST verify compliance with the principles above. Deviations MUST
  be explicitly justified (Complexity Tracking) or rejected.

**Version**: 1.4.0 | **Ratified**: 2026-11-01 | **Last Amended**: 2026-11-06
