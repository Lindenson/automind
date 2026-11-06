# Target structure (the "data model" of a refactoring): packages, what they own, where today's code goes

No database entity changes (FR-003). This file is the map `old module → new place`; the exact per-step mapping
files (`specs/012-refactoring/moves/*.yaml`) are generated from it.

```text
backend/src/automind/
├── shared/                         SHARED KERNEL — what both areas speak; imports nothing from chat/acquisition
│   ├── vehicle/
│   │   ├── identity.py             ← domain/identity.py (aliases, canonical keys, generation years)
│   │   ├── specs/                  ← domain/specs.py (attribute registry: registry.py, tiers.py, transmission.py)
│   │   ├── units.py                ← domain/units.py
│   │   └── markets.py              ← domain/intake.py EUROPE/ANYWHERE/european (+ markets cluster 676-728)
│   ├── evidence/
│   │   ├── provenance.py, confidence.py, conflicts.py   ← domain/evidence.py (427, split by concept)
│   │   └── sense.py                ← domain/sense.py
│   ├── research_order/plan.py      ← domain/research_plan.py (the order format: car × area × kinds)
│   └── infrastructure/
│       ├── config/ loader.py, overrides.py, settings.py   ← infrastructure/config.py, overrides.py, config.py
│       ├── db/ base.py, session.py, migrate.py             ← infrastructure/db/{session,migrate}.py, Base
│       ├── llm/ gateway.py, usage_callback.py              ← infrastructure/llm_gateway.py, usage_callback.py
│       └── events.py                                       ← infrastructure/events.py
│
├── chat/                           AREA 1 — ANSWER THE PERSON
│   ├── domain/                     pure; no I/O
│   │   ├── case/                   ← domain/casefile.py (804): model.py (CaseFile, CaseCar, …), delta.py (apply),
│   │   │                             weights.py (set_weights), fit.py (Fit + Fit.from_case ← identify.fit_of)
│   │   ├── intake/                 ← domain/intake.py (786): pick.py (choice picking), lineup_rank.py,
│   │   │                             body.py, names.py; text parsers → chat/domain/understanding/
│   │   ├── understanding/          text → facts, no LLM: distance.py, region.py, condition.py, charging.py,
│   │   │                             energy_figures.py, cars_in_text.py (← intake.py parsers, nodes/understand.py
│   │   │                             _*_from_text helpers)
│   │   ├── identification/         ladder.py (540 → ladder/ package), identification.py, used.py
│   │   ├── assessment/             criteria.py, weights.py, metrics.py, dragrace.py, feasibility.py,
│   │   │                             profile_gaps.py, ask_value.py, reliability.py, reviews.py
│   │   ├── cost/                   tco/ (566 → engine.py, inputs.py, periods.py), energy/ (550 → per powertrain),
│   │   │                             incentives.py, turn_cost.py (← cost.py)
│   │   ├── verdict/                verdict.py, insights.py, suggestions.py, report_layout.py
│   │   ├── outcome.py
│   │   └── vocabulary/             patterns.py + words_<lang>.py (all regexes / word tables of the chat domain)
│   ├── dialog/                     THE DIALOG STATE MACHINE (runs on LangGraph)
│   │   ├── phases.py, contracts.py, state.py      ← orchestration/state.py (+ typed DTOs)
│   │   ├── policy/ contracts.py, chain.py, rules/*.py   ← domain/policy.py (one rule per module)
│   │   ├── intake_steps.py                         ← domain/intake.py step machine (23-147)
│   │   ├── confirmation.py                         ← the prepare→wait→apply pattern of nodes/confirm.py,
│   │   │                                             feasibility.py, research.py (limit)
│   │   ├── graph.py                                ← orchestration/graph.py (transitions table)
│   │   ├── nodes/ understand.py, identify.py, decide.py, ask.py, confirm_*.py, research.py, answer.py, report.py
│   │   │                                           ← orchestration/nodes/* (thin; logic → services)
│   │   ├── runner.py, retry.py, tracing.py         ← orchestration/runner.py, retry.py, outcomes.py
│   │   └── phrases/ <lang>.py, report_text/       ← orchestration/phrases.py, report_text.py
│   ├── application/
│   │   ├── usecases/               send_message.py, confirm_answer.py, find_more.py, edit_car.py, rescore.py,
│   │   │                             open_chat.py, delete_chats.py (← chats.py), challenge_value.py (← challenge.py)
│   │   ├── services/
│   │   │   ├── interpretation/     ← application/interpret.py (LLM proposes delta, code validates), ask.py
│   │   │   ├── identification/     ← identify.py (721), resolve.py (642), lineup.py, versions.py, makes.py,
│   │   │   │                         candidates.py: service.py + stages/ (name, catalogue, ladder, result) +
│   │   │   │                         strategies/ (catalogue, registered, open_world fallbacks)
│   │   │   ├── research/           ← nodes/research.py logic: plan jobs, order via acquisition.api, collect
│   │   │   ├── feasibility/        ← application/feasibility.py, nodes/feasibility.py logic
│   │   │   ├── report/             ← compose.py (1228), nodes/compute.py (714), electric_block.py, car_view.py,
│   │   │   │                         intake_card.py: service.py + facts/ (car facts) + blocks/ (one per block) +
│   │   │   │                         tco_inputs.py
│   │   │   └── usage/              ← application/usage.py (turn budget)
│   │   └── ports.py                ← application/ports.py (+ CarRepository, VariantRepository from compose/resolve)
│   └── infrastructure/
│       ├── persistence/ models/ (chat, case, turn, usage, catalogue), repositories/ (one per aggregate)
│       │                           ← infrastructure/db/models.py (chat part), repositories.py, outcomes.py
│       ├── car_repository.py, variant_repository.py   ← DB reads of compose.load_car/tco_car, resolve catalogue
│       ├── checkpoint.py, models_on_sale.py, adapters.py, retention.py
│       └── mcp_tools.py            ← mcp_server.py tool bodies (server entry point → delivery)
│
├── acquisition/                    AREA 2 — COLLECT, VALIDATE AND IMPROVE DATA (constitution XIII)
│   ├── api.py                      the ONLY entry for the chat (typed facade, no type: ignore)
│   ├── domain/                     today's acquisition/domain + validation/ (sense_ev, plausibility ← domain/),
│   │                                 relevance.py (← domain/relevance.py), search_plan.py (← domain/search_plan.py)
│   ├── pipeline/                   job.py = the staged pipeline (run() lists plan→locate→fetch→parse→relevance→
│   │                                 validate→merge→persist), stages/*.py, contracts.py (Job, StageResult DTOs)
│   ├── parsing/                    ONE place for "page → fields → claims": readers/ (spec, interpreter, registry,
│   │                                 store, fingerprint, legacy, migrate), extraction/ (contracts.py ← extract.py
│   │                                 schemas, extract.py logic), normalise/ (units, cycles, CLTC), patterns.py
│   ├── identity_readers/           ← pipeline/identity.py, gold/versions.py (line-ups, versions for the chat)
│   ├── gold/, snapshots/, gates/, reputation/, drift/, replay/, registry/   (as today, each with docs + __all__)
│   ├── agents/                     one package per agent: scout/, parser_doctor/, rule_auditor/, extractor_tuner/,
│   │                                 blame_judge/, evaluator; levers.py, budget.py shared by agents
│   ├── insight/                    ← automind/insight (application, domain, infrastructure, metrics, loop)
│   ├── worker/                     queue, scheduler, process, handlers, prefetch, heartbeat, exporter
│   ├── admin/                      ← admin_api.py (1049): parsers.py, changes.py, accuracy.py, snapshots.py,
│   │                                 engine.py, _common.py
│   └── infrastructure/             fetch, pages, wiring, search/ (← infrastructure/search), persistence/ models
│                                     (acq_*, registry, gold, insight tables ← db/models.py) + repos
│
└── delivery/                       ADAPTERS TO THE OUTSIDE WORLD — composition roots, no logic
    ├── web/ app.py (composition root), rest.py, ws.py, admin.py, metrics.py, access.py   ← api/*
    ├── mcp/ server.py              ← mcp_server.py (entry point)
    └── cli/ worker.py, replay.py, baseline.py   (`python -m automind.delivery.cli.worker`; compose files updated)
```

## Removed (FR-018)

Zero-caller functions listed in the spec; `application/repair.py`, `application/backfill.py` (one-off, applied);
`__init__.hello`; empty `infrastructure/site_readers/`; duplicate `_NUM`; config keys nobody reads
(`insights.tie_margin_points`, `search.limits.max_fetch_bytes_per_turn`, `rates.base_reserve_eur_per_year.age_bands`
— each verified again before removal; `energy.prices.home_pvpc` and `outcome.weights.left_after_answer` kept if a
computed key reads them).

## Package documentation template (every `__init__.py`, FR-011)

```python
"""<Area> · <package>: <one sentence: what this package does>.

Owns: <concepts/aggregates it is the home of>.
Flow: <2–5 lines, the main path through the package, if it has one>.
Depends on: <allowed packages>. Must not depend on: <forbidden>.
Public API: see __all__ (everything else is internal).
"""
from .service import IdentificationService
from .contracts import Identified, IdentifyRequest

__all__ = ["IdentificationService", "Identified", "IdentifyRequest"]
```
