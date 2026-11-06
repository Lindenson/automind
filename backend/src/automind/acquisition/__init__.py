"""Acquisition · acquisition: the data engine — finds, reads, checks and stores car data from the web and open datasets.

Owns:
  `api` — the only module the chat may import: order data for a car, read what is stored (contracts in api/contracts).
  `admin_api` — the only module the admin page (delivery.web.admin) may import: parsers, changes, accuracy.
  `backend` — the engine object behind `api` (implements api.contracts.Backend; loaded by `api` at call time).
  `facade` — request → research jobs → result; `read` — the read model per car; `recheck` — claims checked again.
  `engine` — the engine bound to its ports (what the chat's Ports.acquisition holds); `ports` — AcqPorts.
  `pipeline` — one research job (car × area); `domain` — pure rules; `infrastructure` — fetch, pages, search, wiring.
  `registry` — the source registry (spec 010); `gold` — reference values from open datasets.
  `snapshots` — raw page bodies for replay; `parsing` — declarative site parsers; `drift` — parser drift.
  `replay` — offline re-run of a reader/extractor version; `reputation` — accuracy signals and scores.
  `agents` — agents that propose data changes; `gates` — replay/shadow/watch gates for those changes.
  `worker` — the background process (Postgres task queue) that runs everything not live.
Flow: chat → api.acquire → backend → facade → pipeline.job per area → stored claims → read / api answers.
  Background: worker → prefetch, reputation, drift, agents → gates → accepted data changes.
Depends on: shared (contracts, evidence, vehicle, research_order, infrastructure, metering), observability.metrics.
Must not depend on: chat.dialog, delivery.web, chat.domain.case.casefile, observability domain / application /
  infrastructure (import-linter registry-no-chat). Callers: the chat only via `api` (chat-uses-acquire-only),
  the web only via `api`, `admin_api` and a few registry modules (api-uses-engine-facades).
Public API: the modules in __all__ (callers import from them); outside the engine only `api` and `admin_api`.
Note: the engine facades (backend, engine, facade, ports, read, recheck) sit loose next to the subpackages;
  admin_api.py is over 1000 lines.
"""

__all__: list[str] = [
    "admin_api",
    "agents",
    "api",
    "backend",
    "domain",
    "drift",
    "engine",
    "facade",
    "gates",
    "gold",
    "infrastructure",
    "parsing",
    "pipeline",
    "ports",
    "read",
    "recheck",
    "registry",
    "replay",
    "reputation",
    "snapshots",
    "worker",
]
