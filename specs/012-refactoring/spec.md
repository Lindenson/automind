# Feature Specification: Structural Refactoring — Human-Readable Backend

**Feature Branch**: `012-refactoring`

**Created**: 2026-11-06

**Status**: Draft

**Input**: Owner's review of the backend structure (2026-11-06) plus the refactoring inventory of the same day
(`docs/next-session.md` §2a). Behaviour unchanged; no new features; "first planning with a spec, then a large
refactoring".

> This is an internal-quality feature: its "users" are the people who read and change the code (the owner, a
> developer with a Java background, and coding agents). Code-structure terms (package, module, use case, port,
> DTO) are therefore the subject matter of this spec, not implementation leaks.

## Problem (owner's findings, verified)

1. **Mixed, oversized files.** Domain objects sit in large grab-bag modules: `domain/casefile.py` (804 lines),
   `domain/intake.py` (786 lines, seven unrelated clusters, a constant `_NUM` defined twice). 29 modules exceed
   400 lines; the largest is `application/compose.py` (1228). Nested packages are barely used outside
   `acquisition/`.
2. **Behaviour away from its object.** Pure mappers and factories of domain objects live in use cases, e.g.
   `application/identify.py: fit_of(case) -> intake.Fit` builds a domain value from the case file.
3. **Use cases without visible structure.** `identify.py` (721), `compose.py` (1228), `resolve.py` (642) read as one
   long sequence of helpers; the stages and their order are not visible; `compose.py` mixes report assembly,
   database reads and TCO input building; `acquisition/pipeline/extract.py` mixes extraction logic with its DTOs.
4. **No visible split by purpose.** The top-level tree is cut by technical layer (`domain`, `application`,
   `orchestration`, `infrastructure`, `api`) with the acquisition engine and insight beside them. One cannot see at a
   glance which code serves the person in the chat and which code improves data acquisition (agents, worker,
   registry, reputation, insight).
5. **No documentation of what the logic does.** `__init__.py` files are empty (the largest has a one-line
   docstring); there is no architecture page mapping packages to responsibilities.
6. **Contracts mixed with code.** Types, protocols and DTOs are scattered through modules; public functions are not
   first; packages expose no explicit public API; the engine facade returns untyped values (15 `type: ignore`).
7. **Text constants and regexes inside logic.** 92 compiled regexes in 32 files and phrase/word tables sit between
   business functions; parsing of source answers is spread over `acquisition/parsing`, `acquisition/pipeline`
   (parse, extract), `infrastructure/site_readers` and `domain` helpers, with no single place that shows how a
   source answer becomes a value.

Further inventory findings: ~10 functions with zero callers (`rule_auditor.by_rule`, `gates/evaluate.version_number`,
`pipeline/merge.same_model_generations`, `compose.completeness`, `ports.selected_values`, `casefile._legacy_basis`,
`criteria._normalize`, `identification.all_settled`, `guard.removal_notice`, `registry/api._domain_from_url`) and
one-off data repairs (`application/repair.py`, `backfill.py`); layer leaks (`compose.py`, `resolve.py`, `repair.py`,
`challenge.py`, `backfill.py`, `lineup.py` read the database under legacy import-contract exceptions;
`acquisition/pipeline/relevance.py` imports the chat's application layer and the database; business helpers in
`orchestration/nodes/compute.py`); YAML defaults copied into code in 15+ places with one disagreement
(`locate.py` 8 pages vs `search.yaml` 6); three config reads bypass the cached loader; repository clutter (31
worktrees, 90 local and 75 remote branches all merged, root `sec.md`, closed review documents); `docs/baseline.md`
and `docs/deploy.md` not updated for the acquisition engine.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Find where a concept lives from the tree alone (Priority: P1)

A developer new to the code (Java background) opens the source tree and, without searching, finds the module that
holds a given concept: the case file, the identification ladder, the cost of ownership, a site parser, the
acquisition worker, the registry review agent.

**Why this priority**: every other change costs less once the code can be navigated; it is the owner's main
complaint.

**Independent Test**: give a reader 10 concepts from the glossary (docs/architecture) and the tree only; they
name the right package for each.

**Acceptance Scenarios**:

1. **Given** the top-level source tree, **When** a reader looks at it, **Then** they see two product areas — the
   chat that answers the person and the acquisition engine that collects and improves data — plus a small shared
   kernel and the delivery layer (web API, worker entry points), each named by purpose.
2. **Given** any domain concept (aggregate, value object), **When** the reader looks for it, **Then** it is in a
   module named after it, inside a package named after its area, together with its own factories and mappers.
3. **Given** any module, **When** opened, **Then** it holds one cohesive concept and stays within the agreed size
   limit (FR-004).

---

### User Story 2 — Read a use case as a sequence of named stages (Priority: P1)

A developer opens a use case (identify the car, compose the report, resolve a variant, run an acquisition job) and
sees on one screen the stages in order, each a named unit with its own module or class; fallbacks are visible as
interchangeable strategies; data access goes through named ports.

**Why this priority**: the use cases are where behaviour is decided; today they are unreadable.

**Independent Test**: for each refactored use case, its entry point fits on one screen and names every stage; a
reviewer can describe the flow from the entry point without opening the stage modules.

**Acceptance Scenarios**:

1. **Given** the identify use case, **When** opened, **Then** the entry point shows the stages (understand the
   name → catalogue lookup → fallbacks in order → year/generation ladder → result) and each stage is a separate unit.
2. **Given** the report composition, **When** opened, **Then** loading the car, computing facts, building each report
   block and persisting computations are separate units, and loading/persisting go through ports, not direct
   database access.
3. **Given** the extraction step of the acquisition pipeline, **When** opened, **Then** its DTOs live in a contracts
   module and the logic module contains only logic.

---

### User Story 3 — See every package's purpose and public API (Priority: P2)

A developer opens a package's `__init__.py` and reads what the package does, what it owns, what it must not
depend on, and its public API (an explicit export list). Inside each module, contracts (types, protocols, DTOs) come
first, public functions next, private helpers last.

**Why this priority**: documentation and visible contracts make the structure from US1/US2 durable.

**Independent Test**: an automated check lists packages without a docstring or without an explicit export list,
and modules where a private helper precedes a public function; the list is empty.

**Acceptance Scenarios**:

1. **Given** any package, **When** its `__init__.py` is opened, **Then** it has a docstring (purpose,
   responsibilities, dependencies allowed, public API) and an explicit export list.
2. **Given** another package imports from it, **When** import contracts run, **Then** only the exported API is used
   across product-area boundaries.
3. **Given** the acquisition facade, **When** type-checked, **Then** its functions return declared types with no
   `type: ignore`.

---

### User Story 4 — Find all parsing knowledge and text patterns in one place (Priority: P2)

A developer who must fix how a source answer is understood (a spec table, a unit, a Chinese CLTC figure, a phrase
of the person) finds the patterns, vocabularies and parser definitions in named, documented modules, separate from
the logic that uses them; the path "source answer → parsed value → validated claim" is documented in one place.

**Why this priority**: regexes and phrase tables scattered through logic are the second-biggest readability cost.

**Independent Test**: a reader asked "where is the pattern for X" finds it via the documented parsing map in under
two minutes; no business-logic module defines a compiled pattern or a word table inline.

**Acceptance Scenarios**:

1. **Given** a business-logic module, **When** opened, **Then** it contains no inline regex definitions or
   vocabulary tables; it imports named patterns from a patterns/vocabulary module of its area.
2. **Given** the acquisition engine, **When** a reader opens its parsing package, **Then** site readers,
   declarative parsers, extraction schemas and the interpreter are together, and its docstring shows the flow.

---

### User Story 5 — One source of truth, no dead code, clean repository (Priority: P3)

Configuration defaults exist only in YAML; code reads them through one loader. Functions without callers and
completed one-off repairs are gone. The repository has no stale worktrees, merged branches or closed review
documents at its root; deployment and baseline documents describe the current system.

**Why this priority**: low risk, quick wins that shrink the surface before the large moves.

**Independent Test**: dead-code scan reports no function without callers (excluding framework entry points);
no code literal repeats a YAML default; `git worktree list` shows only the main tree.

**Acceptance Scenarios**:

1. **Given** a YAML default, **When** the code needs it, **Then** it reads it via the single loader; removing the
   code fallback does not change behaviour (the `locate.py` 8-vs-6 mismatch resolves to the YAML value, which is
   what runs today when the YAML key is present).
2. **Given** the repository root, **When** listed, **Then** only active project files remain; history is in
   `docs/history/`.

---

### Edge Cases

- **Tests patch internal names** (e.g. `compose.load_car`): moving a function breaks the patch target. Tests are
  updated to the new location in the same step; a temporary re-export is allowed only within one step and removed
  by the end of the feature.
- **Database models and migrations**: splitting the ORM models module must not change table metadata; the
  migration tool must produce an empty autogenerated diff after the split.
- **Serialized state**: checkpointed chat state, stored JSON and queued worker tasks may contain module or class
  paths (pickled or type-tagged data); moves must keep them loadable, or the step lists and tests the migration.
- **Prompts and config paths**: files located relative to a module's path (prompts, YAML) must still resolve.
- **Dead-code false positives**: framework-registered functions (web routes, MCP tools, LangGraph/LLM callbacks,
  worker handlers) are not dead even with zero direct callers.
- **Cross-area shared concepts**: a concept used by both the chat and the engine (vehicle identity, units,
  powertrain, evidence) belongs to the shared kernel, not duplicated.
- **Goldens and evaluation sets** reference module paths or fixtures: they are moved with the code and must keep
  passing unchanged in their expected outputs.
- **Parallel work**: no feature work runs during the refactoring (owner's decision), so long-lived merge conflicts
  are not expected.

## Requirements *(mandatory)*

### Functional Requirements

**Behaviour preservation**

- **FR-001**: Every step MUST leave observable behaviour unchanged: the full test suite, golden tests and
  `scripts/check.sh` pass after every step; expected outputs of goldens are not edited.
- **FR-002**: The refactoring MUST be delivered as a sequence of steps, one pull request each, merged to main after
  green checks; each step is small enough to review (a move-only step may be large but contains no logic change).
- **FR-003**: Database schema MUST NOT change; if a step needs a schema change it stops and asks the owner (with a
  migration and a backup for anything destructive).

**Structure (owner points 1, 4)**

- **FR-004**: No source module MAY exceed **400 lines** (excluding generated or pure-data modules such as
  vocabulary tables, which are listed explicitly); a check enforces it.
- **FR-005**: The top-level source tree MUST be organised by product area first, then by layer:
  `chat/` (domain, application, orchestration of the conversation), `acquisition/` (pipeline, parsing, agents,
  worker, registry, reputation, insight, gold, snapshots, its own domain and infrastructure), `shared/` (concepts and
  infrastructure both areas use: vehicle identity, units, evidence, config loading, database session and models)
  and `delivery/` (web API, WebSocket, worker and CLI entry points). Owner's choice A, 2026-11-06.
- **FR-006**: Each aggregate or cohesive domain concept MUST live in its own module named after it; large concepts
  become packages (e.g. the case file: model, delta application, weights).
- **FR-007**: Factories, mappers and derived values of a domain object MUST live with that object (e.g. the
  person's fit derived from a case file is a factory of the fit value or a method of the case file), not in a use
  case.

**Use cases (owner point 3)**

- **FR-008**: Each use case MUST have an entry point that reads as an ordered sequence of named stages and fits on
  one screen (≤ 60 lines); each stage is a separate unit; alternative behaviours (fallbacks, per-market or
  per-source variants) are separate strategy units selected in one visible place.
- **FR-009**: Use cases in the chat area MUST access persistence only through ports; the legacy import-contract
  exceptions for `compose`, `resolve`, `repair`, `challenge`, `backfill` and `lineup` are removed.
- **FR-010**: Orchestration (graph nodes) MUST contain only flow control and delegation; business helpers now in
  graph nodes move to the application or domain layer.

**Contracts and documentation (owner points 5, 6)**

- **FR-011**: Every package MUST have an `__init__.py` docstring stating purpose, owned concepts, allowed
  dependencies and public API, and an explicit export list (`__all__`).
- **FR-012**: Inside every module the order MUST be: module docstring, imports, contracts (types, protocols, DTOs,
  constants of the contract), public functions/classes, private helpers. DTOs shared by several modules live in a
  dedicated contracts module of their package.
- **FR-013**: Cross-area imports MUST use only the exported public API of the target package; import contracts
  encode the product areas, the layers inside each, and the shared kernel; existing contracts are only tightened.
- **FR-014**: The acquisition facade MUST return declared types; no `type: ignore` remains in it.
- **FR-015**: A `docs/architecture.md` page MUST map product areas and packages to responsibilities, show the
  main data flows (chat turn; acquisition job; background worker loop) and contain a glossary of domain concepts
  with their module.

**Text, patterns, parsing (owner point 7)**

- **FR-016**: Compiled patterns and word/phrase tables MUST be defined in named, documented patterns/vocabulary
  modules of their area, not inside business-logic modules; each pattern has a name and a one-line comment with an
  example it matches.
- **FR-017**: All knowledge of how source answers are parsed (site readers, declarative parsers, extraction
  schemas, interpreter, unit and cycle normalisation) MUST be in one parsing package of the acquisition engine, with a
  docstring describing the path "fetched page → parsed fields → claims → validated values".

**Cleanup (inventory findings)**

- **FR-018**: Functions without callers MUST be removed (framework entry points excepted); completed one-off
  repair scripts are removed (their history stays in git).
- **FR-019**: Configuration defaults MUST exist only in YAML and be read through the single cached loader; the three
  direct reads that bypass it are routed through it; keys no code reads are removed.
- **FR-020**: The repository MUST be cleaned: stale worktrees and merged branches removed (remote branches only
  with the owner's yes), `sec.md` and closed review/audit documents moved to `docs/history/`, `docs/baseline.md` and
  `docs/deploy.md` updated for the acquisition engine.
- **FR-021**: Tests MUST mirror the new source tree (same package structure under `tests/unit` etc.) so a module's
  tests are found by path.

**Out of scope**

- **FR-022**: Performance optimisation, new features, the EREV-as-PHEV identity representation, the frontend, and
  normalising the 843 `# fmt: skip` markers are out of scope unless the owner adds them.

### Key Entities

- **Product area**: a top-level part of the system with one purpose — Chat (answer the person), Acquisition engine
  (collect, validate and improve data, including its agents, worker, registry, reputation and insight), Shared
  kernel (concepts both use), Delivery (web API, worker and CLI entry points).
- **Package**: a folder with a documented purpose and explicit public API; belongs to exactly one product area and
  one layer.
- **Use case**: an application-layer entry point with named stages; depends on domain and ports only.
- **Port / adapter**: an interface the application declares for persistence or external services, and its
  infrastructure implementation.
- **Contracts module**: the place where a package keeps its DTOs, protocols and shared types.
- **Patterns / vocabulary module**: named regexes and word tables of an area, documented with examples.
- **Refactoring step**: one reviewable, behaviour-preserving pull request with green checks.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reader with only the tree and `docs/architecture.md` places 10 of 10 sample concepts in the right
  package (owner's acceptance walk-through).
- **SC-002**: 0 source modules above 400 lines outside the explicit data-module allow-list (today: 29 above 400).
- **SC-003**: 100% of packages have a purpose docstring and an explicit export list (today: ~0%).
- **SC-004**: Every use case entry point fits on one screen (≤ 60 lines) and names its stages; owner confirms
  readability on identify, compose and the acquisition job.
- **SC-005**: 0 legacy import-contract exceptions for the chat's persistence access (today: 6); 0 `type: ignore` in
  the acquisition facade (today: 15); the number of import contracts grows, none is weakened.
- **SC-006**: 0 compiled patterns or vocabulary tables inside business-logic modules (today: 92 patterns in 32
  files).
- **SC-007**: 0 behaviour regressions: the test suite (1445 backend + 161 frontend), goldens and a live replay of
  one owner chat give the same results before and after.
- **SC-008**: 0 functions without callers; 0 YAML defaults repeated in code; 1 worktree; no merged branches left.

## Assumptions

- No feature work happens until the refactoring is done (owner, 2026-11-06), so large moves will not conflict.
- Behaviour is defined by the existing test suite, goldens and a live replay; where a test asserts on an internal
  name only, updating that name is not a behaviour change.
- The 400-line limit and the 60-line use-case entry point are defaults chosen from common practice; data-only
  modules (vocabularies, seed tables) may be larger and are listed explicitly.
- Code, comments and docs stay in English; the owner is answered in Russian.
- The web API (`/api/v1`), WebSocket protocol, database schema, YAML config format and stored data are external
  contracts and stay unchanged.
- Recommended practice applied: package-by-feature inside product areas, ports and adapters, one concept per
  module, explicit public APIs, contracts before code, named patterns — the Python counterpart of the owner's Java
  conventions (package = folder with `__init__` as its API; `Protocol` ≈ interface; DTO models ≈ records).
