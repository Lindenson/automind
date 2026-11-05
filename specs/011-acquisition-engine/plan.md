# Implementation Plan: Acquisition Engine — a Self-Improving Data Engine Separated from the Chat

**Branch**: `011-acquisition-engine` | **Date**: 2026-11-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/011-acquisition-engine/spec.md`; external review
`docs/review-2026-11-05-acquisition.md`; constitution 1.3.0 (XII amended, XIII new).

## Summary

Turn acquisition into an engine that can prove its own improvements, then let it improve itself behind gates.
Six stages, each shippable alone and changing no user-visible answer until its own acceptance:

1. **Measurability (US1)**: raw page snapshots (zstd in Postgres, content-addressed, retention classes); producer,
   producer version, model and snapshot on every claim and attempt; gold values from EEA CO2, EEA OBFCM, RDW, the
   reference set and confirmed challenges; an offline `replay` command.
2. **Separation + worker (US2)**: `acquisition.api.acquire()` facade, then the strangler S0–S8 moves plan → locate →
   fetch → parse → validate → persist/merge → job/read model → identity readers out of `application/research.py`
   (deleted at S7); goldens after every step; a `worker` process with a Postgres `SKIP LOCKED` queue takes over the
   background loops and runs prefetch.
3. **Honest reputation (US3)**: gold, family agreement, physics and replacement signals; vector blame; promotion only
   after a minimum of accuracy signals; Thompson-sampled exploration with a budget; searches per accepted value;
   7-day baseline, then the owner switches `registry.autonomy` on.
4. **Parsers + drift (US4)**: Pydantic parser specs in the database, v1 migrated from `site_readers.yaml` with a
   proven-equal interpreter; daily per-version metrics, structure fingerprint, drift → degraded.
5. **Agents + gates (US5)**: scout, parser doctor, rule auditor, extractor tuner (LangGraph, web-reader roles, daily
   budgets, data-only levers), evaluator (code); replay → shadow → accept → watch → rollback; `acq_changes` journal.
6. **Admin (US6)**: Parsers and Changes tabs, rollback/freeze/forbid-similar, accuracy drill-down to the quote.
7. **Leftovers (US7)**: unverified label at half weight, "no data — tried: …", learned-sources rule deleted.

Technical decisions: [research.md](research.md) R1–R16. Schema: [data-model.md](data-model.md) (migrations
0018–0024). Contracts: [acquire](contracts/acquire.md), [task queue](contracts/task-queue.md),
[replay CLI](contracts/replay-cli.md), [parser spec](contracts/parser-spec.md), [admin API](contracts/admin-api.md).
Validation: [quickstart.md](quickstart.md).

## Technical Context

**Language/Version**: Python 3.13 (backend, `requires-python >= 3.13`), TypeScript 5 / React 18 (admin page).

**Primary Dependencies**: existing FastAPI, Pydantic v2, SQLAlchemy 2 async + asyncpg, Alembic, LangGraph,
LangChain integrations behind `infrastructure/llm_gateway.py`, selectolax, trafilatura, httpx, prometheus-client.
New: `zstandard` (snapshot compression; stdlib `compression.zstd` needs 3.14). No new infrastructure.

**Storage**: PostgreSQL 16 only. New tables: `snapshot_blobs`, `page_snapshots`, `gold_datasets`, `gold_values`,
`acq_tasks`, `acq_workers`, `component_reputation`, `acq_daily`, `kpi_baselines`, `parsers`, `parser_versions`,
`parser_daily`, `prompt_versions`, `role_model_overrides`, `rule_overrides`, `acq_changes`, `acq_experiments`,
`change_blocks`, `extraction_cache`; altered `claims`, `registry_attempts`, `page_relevance`, `research_runs`,
`capabilities`, `truth_signals`, `evidence`.

**Testing**: pytest (unit: pure cores test-first — snapshot codec, gold matching, replay comparison, physics, blame
vector, Thompson sampling, lifecycle, parser spec + interpreter + v1 equivalence, fingerprint, drift, gates, levers;
integration on `automind_test`; migrations on `automind_mig`; graph tests with fake LLMs), golden dialogues g1–g12
after every strangler step, import-linter, `tests/unit/test_architecture.py`, vitest for the admin tabs.

**Target Platform**: Linux server, Docker Compose (`app`, `worker` new, `postgres`, profiles `monitoring`, `public`).

**Project Type**: web service (modular monolith backend + React frontend), now with two processes from one image.

**Performance Goals**: replay of 30 days ≤ 5 min (SC-001); snapshot write adds ≤ 20 ms per fetched page (compression
off the event loop via `asyncio.to_thread`); no measurable added latency on user turns from background work
(SC-005: p50/p95 of `automind_turn_duration_seconds` unchanged within noise before/after US2).

**Constraints**: constitution I–XIII; no LLM-written executable code; agents change only declarative data;
`application/research.py` only shrinks and is deleted at S7; goldens unchanged after each moved stage;
`registry.autonomy: false` until the baseline task; daily budgets and `DAILY_CAP_EUR` human-set; snapshot cap
`snapshots.max_gb` (default 5).

**Scale/Scope**: one owner, few users; ≤ ~1,000 fetched pages/day incl. prefetch; ~200 registry sources; 3 site
readers today; 5 agents; ~120 tasks.

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after Phase 1 design (same verdicts).*

| Principle | How 011 complies | Verdict |
|---|---|---|
| I Evidence first | Snapshots make every value's evidence reproducible (raw page kept); gold values carry origin, dataset, date, matching rule, confidence; flagged gold is not trusted blindly; "no data" names sources tried. | Pass |
| II Exact identity | Gold matching rules key on make + model + fuel + power ± 1 kW + generation years; ambiguous dataset groups give **no gold**; relevance blame catches other-variant pages. | Pass |
| III Deterministic computation | Physics checks, blame rules, Wilson bounds, gates, drift, fingerprint, gold conversions are pure functions; Thompson sampling seeded by `hash(job_id, area)`; LLMs only extract, draft declarative specs or judge disputed blame with a verified quote. | Pass |
| IV Provenance classes | Gold is evidence for checking, not a new displayed class; dataset values shown to users (later) would be `SOURCED_FACT` with source type `DATASET`; CdA in physics is an `Assumption` used only for a check. | Pass |
| V Layered monolith | One codebase and image; `worker` is a second process of the same deployable (not a microservice); engine packages have their own domain/application/infrastructure with import contracts; domain stays free of SQLAlchemy/LangGraph/httpx. | Pass (see Complexity Tracking) |
| VI Bounded orchestration | Every agent has a daily budget and max runs; gates, shadow and watch have page/day bounds; queue retries bounded with back-off and `dead`; budgets and deny-list remain human-only; declarative data changed by the engine per VI's 1.3.0 bullet. | Pass |
| VII Provider independence | New roles (`scout`, `parser_doctor`, `rule_auditor`, `extractor_tuner`, `blame_judge`) in `config/models.yaml` through the gateway; per-call usage tracked; role model overrides only for extractor roles via the gateway. | Pass |
| VIII Untrusted content | Agents that see pages are web readers (no tools); page text in `<untrusted_document>`; outputs validated by schema; levers limited by code; datasets fetched from official APIs, never deny-listed sites; robots/terms fields not writable by agents. | Pass |
| IX Test-first core | Pure cores listed under Testing get tests written first (tasks marked); graph tests with fake LLMs for agents; replay is the reproducibility mechanism the principle asks for. | Pass |
| X Simplicity | Queue in Postgres (required by XIII) instead of Redis/Celery; snapshots in Postgres instead of object storage; KBA used only where it adds value; no vector DB. | Pass |
| XI Quality gates | Validation step unchanged and now versioned; minimum evidence per section unchanged; unverified sources count half. | Pass |
| XII Self-observation, bounded autonomy | Every value records source, parser/prompt version, model; snapshots kept for replay; agents change only the five declarative lever kinds + registry entries, only through replay → shadow → accept → watch → rollback; one change per object; journal with diff, reason, evidence, metrics, one-sentence explanation; owner revert in one action; background never in a user's turn. | Pass |
| XIII Separate engine | `acquisition.api` is the chat's only door (contract without exceptions after S8); background work in the `worker` with `acq_tasks`; the API keeps only retention and process metrics. | Pass |

## Project Structure

### Documentation (this feature)

```text
specs/011-acquisition-engine/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R16
├── data-model.md        # migrations 0018–0024
├── quickstart.md        # validation scenarios incl. the simulated redesign
├── contracts/
│   ├── acquire.md       # acquisition.api
│   ├── task-queue.md    # worker, acq_tasks, schedule, metrics
│   ├── replay-cli.md    # python -m automind.acquisition.replay
│   ├── parser-spec.md   # ParserSpec schema + v1 migration
│   └── admin-api.md     # Parsers, Changes, accuracy drill-down, engine status
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/
│   ├── 0018_snapshots_versions.py      # US1
│   ├── 0019_gold.py                    # US1
│   ├── 0020_acq_tasks.py               # US2
│   ├── 0021_reputation.py              # US3
│   ├── 0022_parsers.py                 # US4 (+ acq_changes)
│   ├── 0023_agents.py                  # US5
│   └── 0024_evidence_unverified.py     # US7
├── config/
│   ├── acquisition.yaml                # snapshots, schedule, worker, prefetch, drift, replay (new)
│   ├── gold_datasets.yaml              # dataset endpoints, columns, attribute map, tolerances, strip words (new)
│   ├── physics.yaml                    # envelopes and tolerances (new)
│   ├── agents.yaml                     # budgets, max runs, gates, levers + bounds, allowed models (new)
│   ├── registry.yaml                   # + weights.physics, lifecycle.promote.min_signals, explore.*
│   ├── models.yaml                     # + scout, parser_doctor, rule_auditor, extractor_tuner, blame_judge
│   └── site_readers.yaml               # seed only after US4 (read by migrate_v1)
├── src/automind/acquisition/
│   ├── api.py                          # THE interface (contracts/acquire.md)
│   ├── ports.py                        # AcqPorts
│   ├── read.py                         # read model (missing_critical, last_done, …)
│   ├── domain/                         # pure: replay.py, physics.py, blame.py, thompson.py, gates.py, drift.py
│   ├── snapshots/                      # codec.py (pure), store.py (DB), retention.py
│   ├── gold/                           # domain/match.py (pure), loaders/{eea_co2,eea_obfcm,rdw,reference_set,challenges}.py, load.py (CLI)
│   ├── pipeline/                       # plan.py, locate.py, fetch.py, relevance.py, parse.py, extract.py, validate.py, persist.py, merge.py, market.py, job.py
│   ├── parsing/                        # spec.py, interpreter.py, fingerprint.py, migrate_v1.py, registry.py, legacy.py (v1 reader until US4)
│   ├── replay/                         # __main__.py (CLI), run.py, offline.py
│   ├── reputation/                     # signals.py (gold/agreement/physics/replacement), components.py, rollup.py, baseline.py
│   ├── drift/                          # daily.py (parser_daily + detection)
│   ├── agents/                         # levers.py, budget.py, scout.py, parser_doctor.py, rule_auditor.py, extractor_tuner.py, evaluator.py, blame_judge.py
│   ├── gates/                          # replay_gate.py, shadow.py, watch.py, journal.py (acq_changes)
│   ├── worker/                         # __main__.py, queue.py, scheduler.py, handlers.py, heartbeat.py, exporter.py
│   ├── infrastructure/                 # pages.py, fetch.py (moved at S3), wiring.py (live_acq_ports), repos
│   └── registry/                       # spec 010 (api, domain, application, infrastructure) — extended in US3
├── src/automind/application/research.py         # shrinks S1–S6, DELETED at S7
├── src/automind/application/{challenge,repair,resolve,lineup,versions}.py   # switch to acquisition.api (S0, S7, S8)
├── src/automind/orchestration/nodes/{research,understand,compute}.py        # switch to acquisition.api (S0)
├── src/automind/infrastructure/{pages,fetch}.py, site_readers/              # moved into acquisition (S3, S4)
├── src/automind/infrastructure/config.py        # rule_overrides layering (US5)
├── src/automind/infrastructure/llm_gateway.py   # prompt_versions + role_model_overrides for extractor roles (US5)
├── src/automind/api/app.py                      # registry/insight/metrics loops removed (US2)
├── src/automind/api/admin.py                    # Parsers, Changes, accuracy, engine endpoints (US6)
├── .importlinter                                # acquisition contracts (US2)
└── tests/
    ├── unit/        # test_snapshot_codec, test_gold_match, test_replay_compare, test_physics, test_blame_vector,
    │                # test_thompson, test_parser_spec, test_parser_v1_equivalence, test_fingerprint, test_drift,
    │                # test_gates, test_levers, test_no_acquisition_calls_in_chat, test_task_queue_sql
    ├── integration/ # test_snapshots, test_gold_load, test_replay, test_task_queue, test_worker, test_prefetch,
    │                # test_honest_reputation, test_parser_drift, test_redesign_acceptance, test_admin_engine_api,
    │                # test_unverified_label, test_nodata_tried, test_migrations (0018–0024)
    ├── graph/       # test_agents_*.py (fake LLM)
    ├── fixtures/    # html/redesign/, scenarios/honest/, gold/ (small dataset extracts)
    └── golden/      # unchanged
frontend/src/admin/  # Parsers.tsx, ParserCard.tsx, Changes.tsx, ChangeCard.tsx, Accuracy.tsx, Engine.tsx (+ tests)
docker-compose.yml   # service `worker`
deploy/prometheus/   # scrape job `worker`, rule WorkerDown, drift/canary rules
docs/adr/ADR-032-acquisition-engine.md
```

**Structure Decision**: the engine grows inside the existing `automind.acquisition` package (created by spec 010 for
the registry), with its own pure `domain` and per-concern subpackages; the chat side keeps `automind.application`,
`automind.orchestration` and `automind.domain` and reaches the engine only through `automind.acquisition.api`. Pure
domain modules shared by both (`domain/evidence`, `specs`, `units`, `sense`, `plausibility`, `relevance`,
`search_plan`, `research_plan`) stay in `automind.domain` (research R5).

## Delivery order by stage

| Stage | Story | Ships | Acceptance before the next stage |
|---|---|---|---|
| 0 | Setup + Foundational | deps, packages, config files, contracts in `.importlinter` (lenient), ADR | `scripts/check.sh` green |
| 1 | US1 measurability (P1, MVP) | 0018, 0019, snapshot writer, producer versions, gold loaders, replay CLI | US1 independent test; SC-001, SC-002 |
| 2 | US2 separation + worker (P1) | facade S0, strangler S1–S8 one by one, 0020, worker, compose service, loops moved, prefetch | goldens after each step; research.py deleted; contract without exceptions; worker independence test |
| 3 | US3 honest reputation (P1) | 0021, signals, blame vector, physics, Thompson, promotion minimum, roll-ups, baseline | US3 fixture test; 7-day baseline row; **owner** flips `registry.autonomy: true` |
| 4 | US4 parsers + drift (P2) | 0022, ParserSpec + interpreter, v1 migration with equivalence, parser_daily, drift | v1 equivalence on fixtures + snapshots; redesign fixture marks degraded |
| 5 | US5 agents + gates (P2) | 0023, levers, gates, journal, 5 agents, overrides layering | simulated redesign accepted with no human (SC-007); worse proposal rejected; rollback works |
| 6 | US6 admin (P3) | Parsers, Changes, accuracy drill-down, engine status | 3-click drill-down (SC-010) |
| 7 | US7 010 leftovers (P3) | unverified label, tried sources, learned rule deleted | US7 independent test |
| 8 | Polish | docs, ADR, quickstart walk, monthly SC-009 review | quickstart sections 0–7 pass |

US7's T059/T067 can run in parallel with stage 3+ (they touch persist/compose and the frontend); T075 waits for S7
(the learned rule lives in `pipeline/plan.py` and `pipeline/job.py` after the move).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| A second process (`worker`) from the same image (V: single deployable; X: no queues before a requirement) | Constitution XIII requires background acquisition in a separate process with a database-backed queue; SC-005 forbids background work slowing turns | asyncio tasks in the API (today) — stop with the API and compete with turns; Redis/Celery — new infrastructure |
| Raw page bodies stored for 30–180 days | XII: no automatic change may be accepted without replayable snapshots | storing only extracted text — readers need raw HTML; no storage — no gate possible |
| `rule_overrides` layered over YAML config | XII lets agents change thresholds/keywords, but no code path may write YAML (spec 010 test) | agents editing YAML — forbidden; moving all rules into the DB — large change for no gain |
