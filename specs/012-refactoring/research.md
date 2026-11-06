# Research: 012 Structural Refactoring

All decisions below were taken on 2026-11-06 from the spec, its clarifications and measurements on main `31d2170`.

## R1. Top-level layout: product area first, layer second

- **Decision**: `automind/{chat, acquisition, observability, shared, delivery}`; inside each area the layers
  `domain/`, `application/`, `infrastructure/` (+ `chat/dialog/` for the dialog state machine). `insight` becomes
  the area **`observability/`**: it reads the journals of *both* cycles (raw SQL on `turn_outcomes`, `turns`,
  `chat_messages`, `feedback` — `insight/infrastructure/repo.py:61,75,255` — and the engine's journals) and is
  imported by nobody except `delivery` (the worker entry point schedules its loop). Review B2.
- **Rationale**: owner's choice A; matches bounded contexts / Java modules; the two purposes (serve the person,
  improve the data) are visible at the first level.
- **Alternatives**: layers first with feature sub-packages (B) — keeps the split invisible; insight inside
  `acquisition` (first draft) — rejected: the engine would read the chat's tables (violates "engine knows no chat"
  in meaning, invisible to import-linter); splitting insight into chat/ and acquisition/ halves — rejected: one
  analysis loop groups failures of both cycles.

## R2. What goes to `shared/` (the shared kernel)

Measured importers of every `domain/*` module (chat side vs engine side):

| Module | chat | engine | Target |
|---|---|---|---|
| identity (aliases, canonical keys, generations) | 14 | 1 | `shared/vehicle/identity` |
| specs (attribute registry) | 3 | 9 | `shared/vehicle/specs` |
| units | 2 | 2 | `shared/vehicle/units` |
| evidence (source typing, provenance, confidence) | 8 | 16 | `shared/evidence/` |
| sense (value meaning) | 6 | 5 | `shared/evidence/sense` |
| research_plan (what to order per area) | 3 | 6 | `shared/research_order/plan` (the order format both speak) |
| intake `EUROPE`/`ANYWHERE`/`european` | — | 2 | `shared/vehicle/markets` |
| sense_ev, plausibility, relevance, search_plan | 0–1 | 2–4 | `acquisition/domain/…` (chat's single use of search_plan goes through `acquisition.api`) |
| everything else (casefile, intake, policy, tco, energy, criteria, …) | ≥1 | 0 | `chat/domain/…` |

Infrastructure used by both: config loader + overrides, DB session/base/migrations, LLM gateway, usage callback,
event bus → `shared/infrastructure/`. ORM models are split per area (`chat/infrastructure/persistence/models`,
`acquisition/infrastructure/persistence/models`) with one `shared/infrastructure/db/base.py` (`Base`, metadata),
re-collected for Alembic.

- **Rule**: `shared` imports nothing from `chat`, `acquisition` or `delivery`. A concept enters `shared` only when
  both areas use it; otherwise it lives in its area.

## R3. Shapes of use case, service, stage, strategy (clarification Q1)

- **Use case** (`chat/application/usecases/`): class, one per user action — `SendMessage`, `ConfirmAnswer`,
  `FindMore`, `EditCar`, `Rescore`, `OpenChat`, `DeleteChats`, `ChallengeValue`. Constructor takes ports; `run()` is
  ≤ 30 lines; it starts or resumes a turn of the dialog machine, or calls one service.
- **Service** (`*/application/services/<name>/`): package per engine of logic. `service.py` holds the class
  (ports in `__init__`, `run()` ≤ 60 lines listing named stages); `stages/*.py` pure functions, one stage per
  module; `strategies/*.py` alternatives behind a `Protocol` in `contracts.py`.
- **Rationale**: Java-familiar entry points with visible dependencies; stateless stages stay short as functions.
- **Alternatives**: everything classes (boilerplate for stateless stages); everything functions (dependencies hidden
  in arguments, no visible entry object).

## R4. The dialog state machine (clarification Q2)

- **Decision**: LangGraph stays the runtime (interrupt + Postgres checkpointer, `Send` fan-out, retry policies,
  node tracing). `chat/dialog/` makes the machine explicit:
  - `phases.py` — `Phase` enum: UNDERSTAND, DECIDE, ASKING, CONFIRMING, RESEARCHING, ANSWERING, DONE; the
    `ConfirmKind` enum: INTAKE, VARIANTS, COST, FEASIBILITY, LIMIT.
  - `state.py` — `TurnState` stays a `TypedDict` (LangGraph requirement, checkpoint format unchanged) but every
    key is typed with named DTOs (`Decision`, `ConfirmPayload`, `ResearchProgress`) from `dialog/contracts.py`;
    per-turn reset defined next to it.
  - `policy/` — Chain of Responsibility: `contracts.py` (`Rule` Protocol: `apply(ctx) -> Action | None`),
    `rules/*.py` one rule per module, `chain.py` the ordered list + `decide()`; `Policy` Protocol so another
    implementation (e.g. "LLM proposes → code gates") can be plugged in later.
  - `intake_steps.py` — the intake step sub-machine (`next_step`).
  - `confirmation.py` — the confirmation pattern once: `Confirmation` (prepare, apply, routes) + `add_confirmation(
    graph, kind, spec)` wiring prepare → wait(interrupt) → apply; five configurations.
  - `graph.py` — the transitions table (≤ 80 lines).
  - `nodes/*.py` — thin adapters (≤ 30 lines each): read state → call a service → write state.
  - `runner.py` — the turn runner (start/resume/busy/supersede), used by the use cases.
- **State holds plain data only (review B3)**: nested values in `TurnState` are `TypedDict`s (plain `dict` at
  runtime) — never Pydantic/dataclass objects, because LangGraph's serializer stores class objects with their module
  path and a later module move would break resuming a pending interrupt; DTOs used by the code convert with
  `to_state()` / `from_state()` at the node boundary. `scripts/check_checkpoints.py` (repeatable, replaces the
  one-off measurement) loads a dump of the live checkpoints into the new graph, asserts 0 blobs contain
  `automind.`, and resumes one pending interrupt of every `ConfirmKind`; it gates S3a, S6 and S15.
- **Policy seam limited (review I10)**: one `Policy` Protocol, one implementation; no factory, registry or config
  switch until the experiment itself. Rules are grouped by phase (`rules/early.py`, `rules/intake.py`,
  `rules/confirm.py`, `rules/research.py`, `rules/answer.py`), the order is one list in `chain.py` (review I3) —
  not one 10-line file per rule.
- **Checkpoint compatibility**: measured on the live DB: 0 of 358 checkpoint blobs contain `automind.` module paths
  (state is plain dicts) → module moves are safe; node names stay identical (pending interrupts resume by node
  name), so renaming node *functions* is safe, renaming graph *node ids* is not (forbidden in this feature).

## R5. Moving code safely: codemod, not hand edits

- **Decision**: `scripts/refactor/move.py MAP.yaml` rewrites `import`/`from` statements and string module paths
  (`mock.patch("automind.x.y")`, `importlib`, `_engine("acquisition.read")`, docker/compose `python -m` commands,
  Alembic `env.py`, docs) for a mapping old → new module; then `ruff --fix` for import order; then the full gate.
  Each move PR contains the mapping file and no hand logic changes.
- **Alternatives**: rope (does not rewrite string paths in patches/configs); IDE refactoring (not reproducible).
- **Rule**: no long-lived compatibility shims; a re-export left for a later step in the same feature is listed in
  `specs/012-refactoring/shims.md` and removed before the last step.

## R6. Enforcing the structure automatically (ratchet)

- **Decision**: `scripts/check_structure.py` (runs in `check.sh`):
  1. module size ≤ 400 lines (allow-list for data modules: vocabulary tables, seed tables);
  2. every package `__init__.py` has a docstring and `__all__`;
  3. top-level order: no public `def`/`class` after the first private one;
  4. no `re.compile` / inline word tables outside `patterns.py` / `vocabulary/` modules;
  5. graph nodes ≤ 30 lines, use case `run()` ≤ 30, service `run()` ≤ 60;
  6. no raw SQL naming a table of another area (table → area list in `scripts/table_owners.yaml`; SQL strings are
     scanned for table names) — review B2.
  Rule 4 (review I2): no `re.compile` / regex literal **inside a function**, no word/phrase tables inside logic
  modules; a technical regex used once stays in its module as a named constant in the contracts section with an
  example comment.
  Justified exceptions live in `scripts/structure_exceptions.txt` (path, limit, one-line reason), separate from the
  baseline (review I3). Splitting a module by line count instead of by concept is a review error, not a fix.
  A baseline file lists today's violations; the check fails on any new violation and on a baseline entry that is
  fixed but not removed (ratchet). The feature is done when the baseline is empty.
- **Import contracts** (`backend/.importlinter`): rewritten to the new paths in the move step without loosening;
  then tightened per area (see contracts/import-contracts.md).

## R7. Text constants, phrases, regexes (revised after review I2)

- **Decision**: vocabulary by concept, not one dump: `chat/domain/vocabulary/{distance.py, charging.py,
  gearbox.py, condition.py, region.py, brands.py, …}` hold word tables, language patterns and anything used by two
  or more modules; reply phrases per language in `chat/dialog/phrases/<lang>.py` (now `orchestration/phrases.py`
  597 lines and parts of `report_text.py`); source-answer patterns by concept in `acquisition/parsing/normalise/`.
  A technical regex used in one place stays there as a named module constant with an example comment.
- **Rationale**: logic reads as logic, while a pattern stays near its single user; a multi-hundred-line
  `patterns.py` would be the same dump the owner complained about.

## R8. One discoverable parsing package

- **Decision**: `acquisition/parsing/` holds the whole path "fetched page → parsed fields → claims → validated
  values": `readers/` (declarative parser specs: spec, interpreter, registry, store, fingerprint, legacy v1,
  migrate), `extraction/` (LLM web readers: `contracts.py` schemas/DTOs separate from `extract.py` logic),
  `normalise/` (units, test cycles, Chinese units, CLTC), `patterns.py`; its `__init__` docstring draws the flow.
  `infrastructure/site_readers` (now empty) is removed.

## R9. Order of work

Cheap, low-risk shrinking first; then the one large move-only step that creates the tree (so every later diff is
inside its final package); then per-area restructuring from the inside out (domain → dialog/services → use cases);
docs and the ratchet's empty baseline last. Detailed in plan.md "Steps".

## R10. Constitution

Principle V names the layers "domain, application, orchestration, and infrastructure". The new tree keeps these
layers inside each area and renames the chat's orchestration layer to `dialog`. → MINOR amendment of V (wording:
"layers per bounded context: domain, application, dialog/orchestration, infrastructure; a shared kernel; delivery
adapters"), done in the step that creates the tree. Principle XIII (acquisition as a separate engine, one interface)
is unchanged and becomes enforced more strictly.

## R11. Behaviour preservation harness (review B4)

Merges go to main without human review (owner's standing instruction), so automation is the only guard.
- **Coverage**: add `pytest-cov`; record branch coverage of `compose`, `identify`, `resolve`, `nodes/compute`,
  `interpret`, `policy`, `nodes/understand`, `nodes/confirm`, `pipeline/job` in `coverage-before.txt` (S1). A
  *restructure* step (S5–S12) starts only when branch coverage of its modules is ≥ 80 %; below that,
  characterisation tests are written first (in the same or a preceding PR, against unchanged code).
- **Before/after diff**: `scripts/refactor/diff_behaviour.py` replays the 21 goldens and 10–20 recorded real chats
  (LLM and search cassettes) on the base commit and on the step's head, normalises times and ids, and compares
  report JSON and the WebSocket event stream byte for byte. Gate of every step S3a–S13. The live replay stays as an
  extra check.
- **Metrics before** (review I9): `metrics-before.md` generated by `scripts/refactor/metrics.py` (lines, modules >
  400, `type: ignore`, `ignore_imports`, regexes outside vocabulary, contracts, coverage). SCs are checked against
  this file, not the numbers in the spec text (the spec's "29 modules > 400" vs the reviewer's 30 is settled by
  the script).

## R12. The engine's budget without the chat (review B5)

- **Decision**: `acquisition/api.py` declares `Budget(Protocol)`: `charge(eur: float) -> None` (raises
  `BudgetExhausted` from the api module), `exhausted() -> bool`. `acquire(..., budget=...)` takes it; the chat passes
  its turn budget (adapter over `chat.application.services.usage`), the worker its daily engine budget.
  `pipeline/relevance.py` stops importing `application.ports`/`application.usage`; `Page` moves to
  `acquisition/pipeline/contracts.py`. Done in S2 with the typed facade.

## R13. Who owns which tables (review B1, I4)

| Tables | Owner | Others read via |
|---|---|---|
| `vehicle_variants`, `brand_lineups`, model versions, `documents`, `evidence`, `claims`, `spec_values`, `research_runs`, `issues`, `maintenance_items`, gold, snapshots, `acq_*`, registry | acquisition | chat: `acquisition.api` read model `car_data(variant_id) -> CarData` (values, claims with evidence, runs, issues) and catalogue calls (`find_variants`, `upsert_variant`, `get_variant`) |
| `chats`, `case_files`, `turns`, `chat_messages`, `events`, `jobs` (chat side), usage, `feasibility`, checkpoints | chat | observability: SQL read (allowed for this area only, listed in `table_owners.yaml`) |
| `turn_outcomes`, `feedback`, issue table of insight | observability (written by chat through its port) | — |

- `chat.application.ports.CarRepository` / `VariantCatalogue` are adapters over `acquisition.api`, not over ORM.
  The read model and catalogue calls are added in S2 (typed facade), used in S7/S8.
- **Alembic**: one `Base`/metadata in `shared/infrastructure/db/base.py`; the collector that imports all model
  modules lives in `backend/alembic/env.py` (outside the package), never in `shared` (kernel imports nothing).
  Cross-area `relationship()`/`ForeignKey` by table-name strings only, no class imports.

## R14. Stable CLI (review I6)

`python -m automind.cli <command>` (`delivery/cli/__main__.py`) is an external contract independent of the tree:
`worker`, `replay`, `baseline open|close`, `migrate`, `fit-physics`. Old `python -m automind.acquisition.…` paths keep
working until S3a and are then replaced in compose files, `scripts/`, `docs/next-session.md` §3.1 (the owner's
2026-11-12 command becomes `python -m automind.cli baseline close --name pre-autonomy`) in the same PR.

## R15. Deploy and rollback (review I5, I7)

- **Deploy policy**: merges to main continue; **no deploy until the pre-autonomy baseline is closed
  (2026-11-12)**; afterwards deploy only checkpoint steps S3a, S6, S9, S12, S15, each noted in the baseline/changes
  journal.
- **Rollback**: `git revert` of the step + `scripts/deploy.sh up`; checkpoint compatibility both ways is guaranteed
  by R4 (plain-dict state, frozen node ids) and checked by `check_checkpoints.py` on the reverted build; worker task
  kinds are strings and stay identical; no schema change exists to roll back.

## R16. Typing scope (review I8)

mypy strict for `shared`, every `domain`, `acquisition/api.py`, `chat/application`, `chat/dialog`; the rest in report
mode with a ratchet. "Strict for the whole src" is out of scope.
