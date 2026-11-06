# Research: 012 Structural Refactoring

All decisions below were taken on 2026-11-06 from the spec, its clarifications and measurements on main `31d2170`.

## R1. Top-level layout: product area first, layer second

- **Decision**: `automind/{chat, acquisition, shared, delivery}`; inside each area the layers `domain/`,
  `application/`, `infrastructure/` (+ `chat/dialog/` for the dialog state machine). `insight` moves under
  `acquisition/insight/` (it observes the engine's journals and is run by the acquisition worker).
- **Rationale**: owner's choice A; matches bounded contexts / Java modules; the two purposes (serve the person,
  improve the data) are visible at the first level.
- **Alternatives**: layers first with feature sub-packages (B) — keeps the split invisible; insight as a third area
  (C) — it has no user and is driven by the worker, so it belongs to the engine.

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
  5. graph nodes ≤ 30 lines, use case `run()` ≤ 30, service `run()` ≤ 60.
  A baseline file lists today's violations; the check fails on any new violation and on a baseline entry that is
  fixed but not removed (ratchet). The feature is done when the baseline is empty.
- **Import contracts** (`backend/.importlinter`): rewritten to the new paths in the move step without loosening;
  then tightened per area (see contracts/import-contracts.md).

## R7. Text constants, phrases, regexes

- **Decision**: per area a `vocabulary/` package — `chat/domain/vocabulary/{patterns.py, words_ru.py,
  words_es.py, words_en.py, …}` and `chat/dialog/phrases/` (reply phrases per language, now `orchestration/phrases.py`
  597 lines and parts of `report_text.py`); `acquisition/parsing/patterns.py` for source-answer patterns. Each
  pattern: `NAME = re.compile(...)  # matches "1–2 тыс км в месяц"`.
- **Rationale**: logic modules read as logic; the vocabulary is reviewable in one place.

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
