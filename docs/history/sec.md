AutoMind — Project Foundation Specification

Version: 1.0
Status: Initial Draft
Project Type: AI-powered Automotive Research & Engineering Platform
Implementation Level: Advanced
Primary Language: Python
Frontend: React + TypeScript
AI Providers: OpenAI and Anthropic
Orchestration: LangGraph
Initial Market: Spain (ES), extensible to other markets

⸻

1. Product Vision

1.1. Product Overview

AutoMind is an AI-powered automotive research and engineering platform designed to autonomously investigate, compare, analyze, and simulate real-world vehicles.

The system combines multi-agent AI research, external automotive data sources, deterministic engineering calculations, and interactive visualizations.

Users can investigate individual vehicles or compare multiple models based on technical specifications, market prices, owner reviews, reliability indicators, and performance characteristics.

AutoMind must go beyond conventional LLM-based question answering.

It must operate as a stateful research system capable of:

* Decomposing complex research requests into independent tasks.
* Performing parallel research using specialized AI agents.
* Retrieving information from external sources.
* Normalizing data across vehicle generations and variants.
* Identifying conflicting or incomplete information.
* Repeating targeted research when necessary.
* Performing deterministic engineering calculations.
* Running vehicle performance simulations.
* Producing evidence-based reports and interactive visualizations.
* Maintaining research history and resumable workflows.

1.2. Product Vision Statement

Build an extensible automotive intelligence platform that combines AI research agents and engineering models to make automotive information accessible, verifiable, and interactive.

1.3. Core Product Principles

1. Evidence before conclusions.
2. Deterministic calculations instead of LLM-generated numerical guesses.
3. Explicit separation between facts, estimates, and manufacturer claims.
4. Specialized agents with clearly defined responsibilities.
5. Stateful and resumable research workflows.
6. Human control over important research decisions.
7. Modular architecture and extensibility.
8. Model-provider independence.
9. Interactive and visually engaging user experience.
10. Reproducibility and testability.

⸻

2. Target Users and Personas

2.1. Automotive Enthusiast

Wants to explore cars, compare technical characteristics, understand performance, discover interesting models, and investigate automotive technologies.

Typical questions:

* Which car is faster?
* How do two generations of the same model differ?
* Which engine is more reliable?
* What is the best car within a given budget?
* How does drivetrain affect acceleration?

2.2. Automotive Researcher

Wants detailed and reliable information about vehicle specifications, market prices, technical characteristics, and owner experiences.

Needs:

* Source attribution.
* Data quality assessment.
* Conflict detection.
* Historical research.
* Structured reports.

2.3. Engineering Enthusiast

Wants to understand vehicle physics and investigate hypothetical engineering scenarios.

Needs:

* Performance calculations.
* Acceleration simulation.
* Power-to-weight analysis.
* Drivetrain comparisons.
* Interactive experiments.

2.4. Family Learning / Collaborative User

The platform should also support collaborative exploration and learning.

A younger participant should be able to:

* Select vehicles.
* Propose research questions.
* Form hypotheses.
* Predict simulation results.
* Compare predictions with calculated outcomes.
* Explore engineering concepts through interactive experiments.

The interface should be intuitive and visually engaging without compromising technical accuracy.

⸻

3. Product Scope

3.1. Initial MVP — Ultimate Car Battle

The first milestone is a complete automotive comparison workflow.

A user selects three vehicles and starts a research session.

The system:

1. Resolves exact vehicle generations and variants.
2. Creates a research plan.
3. Requests human approval.
4. Performs parallel research.
5. Collects technical specifications.
6. Collects available market information.
7. Collects automotive reviews.
8. Verifies collected information.
9. Identifies missing or conflicting data.
10. Normalizes vehicle specifications.
11. Calculates derived performance indicators.
12. Runs a drag race simulation.
13. Generates a structured comparison report.
14. Displays results through an interactive React interface.

The MVP must work with real external information and clearly identify unavailable or uncertain data.

Local fixture providers may be used for testing.

3.2. Future Product Capabilities

The following features are explicitly outside the initial MVP but must not be architecturally blocked:

* Car Hunter — vehicle discovery based on budget and requirements.
* Market Intelligence — used-car market analytics.
* Reliability Research — recurring mechanical problems and reliability analysis.
* Track Battle — circuit-oriented performance comparison.
* Engine Detective — engine architecture and technical research.
* What If Garage — hypothetical vehicle modifications.
* Car Championship — multi-discipline vehicle competitions.
* Advanced vehicle physics.
* Electric and hybrid powertrain simulations.
* Vehicle ownership cost analysis.
* Three-dimensional visualization.
* AI-generated automotive illustrations.
* Multi-user collaboration.
* Long-term automotive knowledge base.

⸻

4. Functional Requirements

Requirements are assigned stable identifiers for traceability.

FR-001: Research Creation

The system shall allow users to create automotive research sessions.

A research request must support:

* Natural-language query.
* One or more vehicles.
* Vehicle model year.
* Market selection.
* Research categories.
* Research configuration.

The initial MVP shall support three vehicles, with an architecture that permits a configurable number of vehicles.

FR-002: Vehicle Identification

The system shall identify exact vehicle variants.

Vehicle identity must distinguish:

* Manufacturer.
* Model.
* Generation.
* Trim.
* Model year.
* Market.

The system must not silently combine data from different vehicle variants.

Ambiguous identification must trigger clarification or an explicit uncertainty status.

FR-003: Research Planning

The system shall generate an execution plan before launching expensive research operations.

The plan must contain:

* Selected vehicles.
* Research categories.
* Planned tasks.
* Selected data sources.
* Estimated task count.
* Identified ambiguities.

The user must be able to approve or reject the plan.

FR-004: Parallel Research

The system shall support independent parallel research tasks.

Initial research categories:

* Technical specifications.
* Market information.
* Automotive reviews.

Research tasks shall be dynamically generated based on the selected vehicles and research requirements.

LangGraph Send API shall be used for dynamic fan-out.

Results shall be aggregated through appropriately defined reducers.

FR-005: Technical Research

The system shall collect available vehicle specifications, including:

* Engine type.
* Engine displacement.
* Fuel type.
* Power.
* Torque.
* Vehicle weight.
* Drivetrain.
* Transmission.
* Acceleration.
* Maximum speed.
* Fuel consumption.
* Dimensions when available.

Each value must retain its source attribution.

Missing values must remain explicitly unavailable.

FR-006: Market Research

The system shall support research of automotive market information.

Initial market: Spain.

Information may include:

* New vehicle prices.
* Used vehicle prices.
* Model year.
* Mileage.
* Equipment.
* Geographic location.
* Listing source.

Market statistics must distinguish asking prices from confirmed transaction prices.

FR-007: Review Analysis

The system shall collect and analyze available automotive reviews.

It should identify:

* Positive characteristics.
* Negative characteristics.
* Recurring owner complaints.
* Common mechanical problems.
* Maintenance concerns.
* Subjective opinions.

The system must distinguish isolated opinions from recurring patterns.

FR-008: Evidence Management

Every externally sourced factual claim must be associated with evidence.

Evidence should include:

* Source URL.
* Source name.
* Source type.
* Retrieval timestamp.
* Relevant extracted content.
* Related vehicle variant.
* Associated claims.

Evidence must be preserved independently from the LLM conversation.

FR-009: Verification

The system shall verify collected information.

Verification must detect:

* Vehicle variant mismatches.
* Conflicting specifications.
* Missing evidence.
* Unsupported claims.
* Incompatible units.
* Inconsistent model years.

Verification shall support targeted research retries.

Retry loops must have configurable iteration limits.

Unresolved conflicts must be reported instead of silently discarded.

FR-010: Comparison Engine

The system shall compare selected vehicles using normalized specifications.

Derived metrics may include:

* Power-to-weight ratio.
* Acceleration differences.
* Torque-to-weight ratio.
* Maximum speed.
* Fuel consumption.
* Price differences.

All numerical calculations must be performed by deterministic Python functions.

FR-011: Drag Race Simulation

The system shall provide an initial longitudinal acceleration simulation.

The initial model shall consider:

* Vehicle mass.
* Engine power.
* Aerodynamic drag.
* Rolling resistance.
* Drivetrain efficiency.
* Traction limitations.

Simulation results should include:

* Speed over time.
* Distance over time.
* Acceleration over time.
* Estimated 0–100 km/h.
* Estimated 0–200 km/h when supported.
* Estimated 400-meter time.
* Speed at the finish.

The system must distinguish simulated estimates from real-world measured results.

Simulation models must be versioned.

FR-012: Report Generation

The system shall generate structured research reports.

Reports must include:

* Vehicle specifications.
* Comparison tables.
* Performance metrics.
* Simulation results.
* Research findings.
* Evidence references.
* Unresolved conflicts.
* Confidence indicators.

FR-013: Interactive Visualization

The frontend shall display:

* Research progress.
* Individual agent task status.
* Vehicle comparison tables.
* Performance charts.
* Drag race results.
* Evidence references.

FR-014: Stateful Research

Research sessions must support:

* Persistent execution state.
* Checkpointing.
* Interruptions.
* Resumption.
* Cancellation.
* Research history.

LangGraph persistence shall use PostgreSQL.

FR-015: LLM Provider Support

The system shall support both OpenAI and Anthropic.

Provider selection must be configurable independently for different graph nodes.

The system shall provide a unified model gateway.

FR-016: Observability

The system shall support:

* Structured application logs.
* Research execution tracing.
* LLM token usage tracking.
* Execution duration.
* Tool invocation tracking.
* Error reporting.
* Model cost estimation.

LangSmith should be integrated for graph tracing.

⸻

5. Non-Functional Requirements

NFR-001: Modularity

The application must use modular monolithic architecture.

Domain models must not depend on LangGraph, FastAPI, or specific LLM providers.

NFR-002: Extensibility

New research agents, data providers, vehicle types, simulation models, and LLM providers must be addable without rewriting the main orchestration architecture.

NFR-003: Reliability

Temporary provider failures must not automatically fail the entire research session.

Independent research tasks should be recoverable.

NFR-004: Reproducibility

Research artifacts and simulations must preserve relevant inputs, source references, and model versions.

NFR-005: Data Integrity

Vehicle identity, specification values, and evidence relationships must be maintained consistently.

NFR-006: Security

* API keys must remain on the backend.
* Secrets must not be committed to source control.
* External content must be treated as untrusted input.
* Retrieved pages must not be allowed to override system instructions.
* Tool permissions must be restricted by agent role.
* External requests must use appropriate timeouts and resource limits.

NFR-007: Performance

Independent research tasks should execute concurrently.

Concurrency must be configurable.

The application must avoid unbounded LLM calls and uncontrolled retry loops.

NFR-008: Testability

All deterministic domain operations and simulation functions must be independently testable.

Graph execution must support integration and evaluation testing.

NFR-009: User Experience

The application must provide a responsive, understandable, and visually engaging interface.

Research progress must be visible without exposing internal LLM reasoning.

⸻

6. System Architecture

6.1. Architectural Style

Modular monolith with independently testable domain, application, orchestration, and infrastructure layers.

6.2. Backend

* Python 3.12+
* FastAPI
* Pydantic
* LangGraph
* LangChain model integrations
* PostgreSQL
* SQLAlchemy / asyncpg
* Alembic
* LangSmith

6.3. Frontend

* React
* TypeScript
* Vite
* TanStack Query
* Zustand
* React Router
* ECharts
* Tailwind CSS
* Zod

6.4. LLM Providers

* OpenAI API.
* Anthropic API.

Model configuration must be centralized.

Provider-specific integrations must be hidden behind a unified gateway.

6.5. Data Sources

The initial implementation should support:

* Web search providers.
* Official manufacturer information.
* Automotive publications.
* Authorized market data sources.
* Local test fixtures.

Web extraction must respect provider terms, access restrictions, and applicable legal requirements.

6.6. Infrastructure

* Docker Compose.
* PostgreSQL.
* Environment-based configuration.
* Local development support.

The initial implementation should not require Kubernetes or distributed microservices.

⸻

7. LangGraph Architecture

7.1. Main Research Graph

The primary graph must implement the following workflow:

START
→ Parse Request
→ Resolve Vehicle Variants
→ Build Research Plan
→ Human Approval
→ Dynamic Research Fan-Out
→ Research Aggregation
→ Verification
→ Targeted Research Retry (conditional)
→ Data Normalization
→ Performance Analysis
→ Drag Race Simulation
→ Report Generation
→ END

7.2. Research Workers

Initial worker categories:

* Technical Researcher.
* Market Researcher.
* Review Analyst.

A reusable worker implementation should accept task-specific input.

Workers must have bounded tool permissions.

7.3. Verification Graph

A dedicated verification workflow must:

* Extract claims.
* Match vehicle variants.
* Validate evidence.
* Detect conflicts.
* Request additional research.
* Produce a verification report.

7.4. Analysis Graph

The analysis workflow must:

* Normalize data.
* Calculate derived metrics.
* Execute deterministic comparisons.
* Generate rankings.
* Prepare simulation inputs.

7.5. Advanced LangGraph Capabilities

The architecture should explicitly support:

* StateGraph.
* TypedDict state definitions.
* Pydantic domain schemas.
* Reducers.
* Send API.
* Conditional routing.
* Subgraphs.
* Command.
* Interrupts.
* Checkpointing.
* Streaming.
* Retry policies.
* Recursion limits.

Time travel and long-term Store are planned for subsequent milestones.

7.6. State Management

Graph state must contain only workflow-related data and compact references to research artifacts.

Large documents, raw HTML, and images must be stored outside graph state.

Domain persistence and graph checkpointing must have separate responsibilities.

Parallel workers must not perform conflicting updates to shared state fields.

⸻

8. Domain Model

Initial domain entities:

* Vehicle.
* VehicleGeneration.
* VehicleVariant.
* VehicleSpecs.
* Evidence.
* Claim.
* Research.
* ResearchTask.
* ResearchArtifact.
* Comparison.
* Simulation.
* SimulationResult.

Vehicle identity must be separated from vehicle specifications.

Technical attributes must support missing values and source attribution.

Numeric attributes must use explicit units.

8.1. Evidence Model

Every sourced value must preserve:

* Value.
* Unit.
* Source reference.
* Retrieval timestamp.
* Vehicle variant.
* Confidence or evidence quality assessment.

Confidence scores must not be treated as objectively calibrated probabilities unless independently validated.

8.2. Research Lifecycle

Initial lifecycle:

CREATED
→ PLANNING
→ AWAITING_APPROVAL
→ RUNNING
→ VERIFYING
→ ANALYZING
→ COMPLETED

Additional terminal states:

* FAILED.
* CANCELLED.

⸻

9. API Requirements

API version: /api/v1

Initial endpoints:

POST /researches — create research.

POST /researches/{id}/start — start execution.

GET /researches/{id} — retrieve research status.

GET /researches/{id}/events — SSE event stream.

POST /researches/{id}/approval — approve or reject research.

POST /researches/{id}/cancel — cancel research.

GET /researches/{id}/report — retrieve final report.

GET /vehicles/search — search vehicles.

GET /vehicles/{id} — retrieve vehicle details.

POST /comparisons — create comparison.

POST /simulations/drag-race — execute simulation.

GET /simulations/{id} — retrieve simulation results.

API contracts must use explicit Pydantic request and response schemas.

Long-running research execution must not block HTTP request handling.

SSE must support reconnection and event identifiers.

⸻

10. Data Persistence

Initial PostgreSQL entities:

* vehicles
* vehicle_generations
* vehicle_variants
* vehicle_specs
* evidence
* claims
* researches
* research_vehicles
* research_tasks
* research_artifacts
* research_events
* comparisons
* simulations

LangGraph checkpoints must be persisted separately using the supported PostgreSQL checkpointer implementation.

Vector search is not required for the first milestone.

PostgreSQL with pgvector may be introduced later for semantic retrieval over collected documents and reviews.

⸻

11. Frontend Requirements

The initial interface should contain:

Dashboard

* Recent research sessions.
* Research statistics.
* Garage overview.

My Garage

* Vehicle cards.
* Vehicle specifications.
* Vehicle selection.

Research Studio

* Research request creation.
* Vehicle selection.
* Research plan approval.
* Live execution progress.
* Agent task status.

Comparison Lab

* Comparison tables.
* Technical metrics.
* Performance charts.
* Evidence links.

Drag Race Lab

* Vehicle selection.
* Simulation parameters.
* Race animation.
* Speed and acceleration charts.
* Results and rankings.

Research History

* Previous research sessions.
* Completed reports.
* Resumable sessions.

The frontend must not implement orchestration logic.

Backend remains the source of truth for research execution and results.

⸻

12. Testing and Evaluation

12.1. Unit Testing

Test:

* Domain models.
* Vehicle normalization.
* Unit conversions.
* Performance calculations.
* Simulation functions.
* Ranking algorithms.

12.2. Integration Testing

Test:

* LLM providers.
* Data providers.
* PostgreSQL persistence.
* Graph execution.
* API contracts.

12.3. Graph Testing

Required scenarios:

1. Successful research.
2. Ambiguous vehicle identification.
3. Conflicting technical specifications.
4. Missing external source.
5. Failed parallel worker.
6. Verification retry.
7. Human approval and resume.
8. Backend restart and checkpoint recovery.
9. Cancellation.
10. Parallel state aggregation.

12.4. Evaluation

Maintain a controlled dataset of known vehicle specifications and published performance measurements.

Evaluate:

* Vehicle variant identification accuracy.
* Data extraction accuracy.
* Evidence coverage.
* Conflict detection.
* Unit consistency.
* Calculation correctness.
* Simulation calibration.
* LLM cost.
* Execution duration.

Simulation results must be compared with published instrumented tests before being presented as realistic estimates.

⸻

13. Milestone 1 — Ultimate Car Battle

Objective

Deliver a complete end-to-end automotive research and comparison experience for three selected vehicles.

Scope

1. Repository and development environment.
2. Domain models and API schemas.
3. OpenAI and Anthropic integration.
4. LangGraph research workflow.
5. Dynamic parallel research workers.
6. External data providers.
7. Evidence management.
8. Fact checking and targeted retries.
9. Comparison engine.
10. Drag Race Simulator V0.1.
11. React Research Studio.
12. SSE streaming.
13. PostgreSQL persistence.
14. Integration and evaluation tests.

Deliverables

* Working Python backend.
* Working LangGraph graph.
* OpenAI and Anthropic gateway.
* Three parallel research workers.
* Structured vehicle research results.
* Evidence-backed comparison report.
* Deterministic drag race simulation.
* Interactive React interface.
* Persistent research history.
* Docker-based local development environment.
* Automated test suite.

Definition of Done

The milestone is complete when:

1. A user can create a research session with three vehicles.
2. The system resolves their exact variants.
3. A research plan is generated and approved.
4. Research workers execute concurrently.
5. Technical data is collected with source references.
6. Conflicting or missing data is detected.
7. The comparison engine produces normalized results.
8. The simulation produces deterministic results for identical inputs and model versions.
9. React displays the research lifecycle and final report.
10. Research execution can be resumed after interruption or backend restart.
11. All critical workflows pass automated tests.

Estimated Effort

Approximately 45–60 engineering hours, subject to external data provider availability and implementation complexity.

⸻

14. Development Constraints

The following decisions are mandatory for the initial implementation:

1. Do not build a monolithic agent responsible for the entire application.
2. Do not place domain business logic inside LangGraph nodes.
3. Do not use LLMs for deterministic numerical calculations.
4. Do not invent missing automotive specifications.
5. Do not silently resolve conflicting sources.
6. Do not expose LLM API keys to the frontend.
7. Do not use uncontrolled web scraping.
8. Do not create unnecessary microservices.
9. Do not introduce vector databases before a real semantic retrieval requirement exists.
10. Do not expose hidden model reasoning in the user interface.
11. Do not allow untrusted retrieved content to modify agent instructions.
12. Do not couple frontend state to internal LangGraph state structures.

⸻

15. Initial Architecture Decisions (ADR Backlog)

ADR-001: Modular monolithic architecture.

ADR-002: LangGraph as orchestration engine.

ADR-003: TypedDict for graph state and Pydantic for domain contracts.

ADR-004: PostgreSQL as primary database.

ADR-005: Unified OpenAI / Anthropic model gateway.

ADR-006: Dynamic parallel research using Send.

ADR-007: Human-in-the-loop through interrupts.

ADR-008: Deterministic Python simulation engine.

ADR-009: React + FastAPI + SSE.

ADR-010: Evidence-first research architecture.

ADR-011: Separate graph checkpointing from domain persistence.

ADR-012: Versioned research artifacts and simulation models.

⸻

16. Initial Implementation Priorities

Development should follow this sequence:

1. Repository initialization.
2. Domain and contract implementation.
3. Minimal LangGraph StateGraph.
4. Dual LLM Gateway.
5. Vehicle identification.
6. Parallel research workers.
7. Evidence extraction.
8. Verification graph.
9. Comparison engine.
10. Drag Race Simulator.
11. PostgreSQL persistence.
12. FastAPI integration.
13. React frontend.
14. End-to-end testing.

The first technical demonstration should be a working Python workflow that investigates three vehicles in parallel and returns structured, source-attributed results.

Frontend development should follow after the core workflow and data contracts are validated.

⸻

17. Success Criteria

AutoMind succeeds as an initial product when it demonstrates that:

* Multiple AI agents can collaborate through a stateful workflow.
* Research can be performed concurrently.
* External information can be traced to its sources.
* Conflicting data can be detected and handled.
* Engineering calculations remain deterministic and independently testable.
* Research can be interrupted and resumed.
* Different LLM providers can be used without changing domain logic.
* Complex automotive information can be transformed into an engaging interactive experience.

Final Product Goal:

AutoMind should become a practical automotive intelligence and engineering laboratory — a platform where AI research, real-world vehicle data, physics simulations, and interactive exploration work together.
