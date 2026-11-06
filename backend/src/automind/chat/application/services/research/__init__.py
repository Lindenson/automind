"""Chat · chat.application.services.research: researching the compared cars through the acquisition engine.

Owns: `service` — `ResearchService`: job rows (`create`), one job run within the budget and timeout (`run_job`),
  what a finished research leaves (`conclude`); `rounds` — the plan as the turn state carries it, what the engine is
  asked per job, minimums met, a limit hit, the gaps of another round; `contracts` — the events and wording ports.
Flow: the dialog's research nodes: plan_research → research_job × N → collect_round ↺ → after_research.
Depends on: acquisition.api, chat.application.ports, chat.domain, shared.metering, shared.research_order.
Must not depend on: chat.dialog (events and wording come through `contracts`), the database.
Public API: the modules in __all__.
"""

__all__ = ["contracts", "rounds", "service"]
