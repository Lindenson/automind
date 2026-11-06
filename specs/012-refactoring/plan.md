# Implementation Plan: Structural Refactoring — Human-Readable Backend

**Branch**: `012-refactoring` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/012-refactoring/spec.md` (with clarifications of 2026-11-06)

## Summary

Turn the backend (44.9k lines, 29 modules over 400 lines, logic in graph nodes, layer leaks, regexes inside logic)
into a tree a Java developer reads at a glance: four top-level areas (`chat`, `acquisition`, `shared`,
`delivery`), layers inside each, an explicit dialog state machine (`chat/dialog`), use cases as classes per user
action, services with named stages and strategy fallbacks, one parsing package, vocabulary modules, documented
package APIs. Behaviour is unchanged; every step is one green PR. A structure checker with a shrinking baseline
(ratchet) enforces the result. Owner's bar: maximal clarity, zero spaghetti, recognisable patterns.

## Technical Context

**Language/Version**: Python 3.13 (backend); TypeScript frontend untouched

**Primary Dependencies**: FastAPI, LangGraph (runtime of the dialog machine: interrupt, checkpointer, Send),
LangChain model wrappers, SQLAlchemy 2 async + Alembic, Pydantic 2, import-linter, ruff, mypy, pytest

**Storage**: PostgreSQL (unchanged schema; LangGraph checkpoints — verified free of module paths: 0/358 blobs)

**Testing**: `scripts/check.sh` (ruff, format, mypy on domain → extended per area, lint-imports, pytest 1445 backend
+ 161 frontend), goldens `tests/golden`, eval `tests/eval`, graph tests, live replay of chat ccd5f7d8

**Target Platform**: Linux server, docker compose (app, worker, postgres, monitoring)

**Project Type**: web service (modular monolith) + background worker

**Performance Goals**: none new; no measurable change in turn latency (refactoring only)

**Constraints**: behaviour unchanged; no schema change; graph node ids unchanged (pending interrupts resume by node
id); external contracts unchanged (`/api/v1`, WebSocket v2, YAML formats, worker task kinds, `python -m` commands
updated together with compose files); import contracts never loosened

**Scale/Scope**: ~240 source modules, ~22k test lines move; ~15 PRs

## Constitution Check

| Principle | Status |
|---|---|
| I Evidence first, II Exact identity, III Deterministic computation | Unaffected — no logic change; goldens guard it |
| IV Provenance classes | Unaffected |
| **V Layered modular monolith** | **Amendment (MINOR)** — layers stay, now per area: `domain / application / dialog (orchestration) / infrastructure` inside `chat` and `acquisition`, plus `shared` kernel and `delivery` adapters. "Business logic MUST NOT live inside graph nodes" becomes enforced (nodes ≤ 30 lines). Done in step S3 |
| VI Bounded, human-steered orchestration | Strengthened — machine made explicit; LLM still never chooses the action (policy behind a Protocol only prepares a later experiment) |
| VII Model-provider independence | Unaffected (LLM gateway moves to `shared/infrastructure/llm`) |
| VIII External content untrusted | Unaffected (parsing package consolidated, same rules) |
| IX Test-first, reproducibility | Tests move with code; counts never drop; goldens unedited |
| X Simplicity / YAGNI | Watch-point: no speculative abstractions — a Protocol only where ≥ 2 implementations exist today (fallback strategies, policy rules, confirmations, search providers) or the clarified policy seam |
| XII Bounded autonomy | Unaffected; code/budgets still human-only |
| XIII Acquisition is a separate engine | Strengthened — new contract `engine-knows-no-chat`, chat keeps only `acquisition.api` |

Gate: PASS (one planned MINOR amendment, recorded below). Re-check after design: PASS.

## Project Structure

### Documentation (this feature)

```text
specs/012-refactoring/
├── spec.md, plan.md, research.md, data-model.md (target tree + module map), quickstart.md (validation per step)
├── contracts/ import-contracts.md, code-shape.md
├── moves/                # per-step old→new module maps for the codemod (created by the tasks)
├── shims.md              # temporary re-exports, must be empty at the end
└── tasks.md              # /speckit-tasks
```

### Source Code

Target tree and the full old → new map: [data-model.md](data-model.md). Summary:

```text
backend/src/automind/
├── shared/       vehicle (identity, specs, units, markets), evidence (provenance, sense), research_order,
│                 infrastructure (config, db base/session, llm gateway, events)
├── chat/         domain (case, intake, understanding, identification, assessment, cost, verdict, vocabulary)
│                 dialog (phases, state, policy/rules, intake_steps, confirmation, graph, nodes, runner, phrases)
│                 application (usecases/, services/{interpretation, identification, research, feasibility,
│                 report, usage}, ports) · infrastructure (persistence, repositories, checkpoint)
├── acquisition/  api (typed facade) · domain · pipeline (staged) · parsing (readers, extraction, normalise,
│                 patterns) · identity_readers · gold · snapshots · gates · reputation · drift · replay ·
│                 registry · agents/<one package each> · insight · worker · admin · infrastructure
└── delivery/     web (app = composition root, rest, ws, admin, metrics, access) · mcp · cli
backend/tests/    mirrors the source tree (unit/<area>/…, graph, golden, eval, integration unchanged in kind)
scripts/          check_structure.py, structure_baseline.txt, refactor/move.py
docs/architecture.md
```

**Structure Decision**: product area first, layer second (owner's choice A); see research R1–R4.

## Steps (one PR each, merged to main after the gate in quickstart.md)

| Step | Content | Kind | Size |
|---|---|---|---|
| **S0** | Hygiene: remove 31 worktrees, merged local branches (remote — ask owner); `sec.md` + closed `review-*`, `ux-audit-*`, `sources-revision-*` → `docs/history/` | repo | S |
| **S1** | Tooling: `scripts/check_structure.py` + baseline (ratchet) in `check.sh`; `scripts/refactor/move.py` codemod with tests; mypy run extended to report mode for all of `src` | tooling | M |
| **S2** | Shrink: dead code (FR-018), YAML single source + 3 direct reads via loader (FR-019; `locate.py` default → YAML), duplicate `_NUM`, typed `acquisition/api.py` facade (FR-014) | cleanup | M |
| **S3** | **The tree move** (move-only, codemod): create `shared/ chat/ acquisition/ delivery/`, move every module to its area *as a whole file* per data-model, move tests to mirror, retarget `.importlinter` (same strength), update compose/Dockerfile `python -m`, Alembic env, docs links; constitution V amendment; package `__init__` docstrings for every new package (purpose + `__all__`) | move | L |
| **S4** | `shared` kernel split: evidence (provenance/confidence/conflicts), specs package; contract `shared-is-kernel` | split | M |
| **S5** | `chat/domain`: casefile → `case/` package, `Fit.from_case`; intake → `intake/` + `understanding/` + `dialog/intake_steps`; tco, energy, ladder packages; all chat regexes/word tables → `vocabulary/`; mappers next to their objects | split | L |
| **S6** | `chat/dialog`: phases + typed state DTOs, policy as rule chain behind `Policy` Protocol, confirmation pattern once, graph as transitions table (node ids unchanged), runner; nodes still call existing application functions | restructure | L |
| **S7** | Services I — `identification` (identify, resolve, lineup, versions, makes, candidates): service + stages + fallback strategies; DB reads → `variant_repository` behind ports; drop resolve/lineup ignore_imports | restructure | L |
| **S8** | Services II — `report` (compose, nodes/compute, electric block, car view, intake card): facts/, blocks/, tco_inputs; `load_car`/`tco_car`/`persist_computations` → `car_repository` behind ports; drop compose ignore_imports | restructure | L |
| **S9** | Services III — `interpretation`, `research`, `feasibility`, `usage`; nodes reduced to ≤ 30-line adapters; `challenge` → use case + port (drop its ignore_imports); `chat.dialog`/`chat.application` purity contracts on | restructure | L |
| **S10** | Use cases: `SendMessage`, `ConfirmAnswer`, `FindMore`, `EditCar`, `Rescore`, `OpenChat`, `DeleteChats`, `ChallengeValue`; `delivery/web/ws.py` and `rest.py` call use cases only; layers contract for `chat` | restructure | M |
| **S11** | Acquisition I: pipeline as staged `job.run()` + `contracts.py`; one `parsing/` package (readers, extraction contracts vs logic, normalise, patterns) with flow docstring; `identity_readers/`; contract `engine-knows-no-chat` (fix `pipeline/relevance.py`) | restructure | L |
| **S12** | Acquisition II: `admin/` package; `agents/<name>/` packages; `insight/` tidy; persistence models/repos split per area (`alembic check` empty); worker/registry/gates docs | split | L |
| **S13** | Order & API pass: public-before-private in every module, `__all__` exact, cross-package private imports removed; mypy strict for the whole `src` (or a listed remainder) | polish | M |
| **S14** | Docs: `docs/architecture.md` (areas, packages, flows: chat turn, acquisition job, worker loop; glossary concept → module), `baseline.md`, `deploy.md`, README links; `shims.md` empty; structure baseline empty | docs | M |
| **S15** | Acceptance: live replay of chat ccd5f7d8 shown to the owner; readability walk-through (quickstart §5); handoff | verify | S |

Order rationale: cheap shrinking first; one move-only step so later diffs land in final packages; inside-out per area
(domain → dialog → services → use cases); engine after chat (it is already the better-structured half); docs last
but package docstrings written at creation time.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tests patch old string paths (`mock.patch("automind.application.compose.load_car")`) | codemod rewrites string paths; S3 is gated by the full suite |
| Pending interrupts after deploy | node ids frozen; measured checkpoint blobs carry no module paths |
| Alembic sees model moves as drops | one `Base`/metadata; `alembic check` in the gate for S3/S12 |
| Worker task kinds/handlers renamed | task kinds are strings in `HANDLERS`; kept identical |
| Big-bang PR S3 hard to review | move-only, generated from `moves/S3.yaml`; reviewer reads the map, not the diff |
| Behaviour drift hidden in a "restructure" step | goldens unedited; graph tests; live replay after S6 and S15 |
| Over-abstraction (YAGNI) | Protocol only with ≥ 2 implementations or the clarified policy seam; structure checker forbids `utils/helpers/common` |

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| `Policy` Protocol with one implementation today | owner's clarification: the LLM-planner experiment after the quality measurement must plug in without rewriting the graph | a plain function would make the experiment a rewrite of the dialog package |
| Constitution V MINOR amendment | layers move inside areas; `orchestration` named `dialog` in the chat | keeping top-level layers contradicts the owner's choice A |
