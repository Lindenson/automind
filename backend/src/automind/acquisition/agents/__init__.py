"""Acquisition · acquisition.agents: agents that propose changes to declarative data only, never to code.

Owns:
  `levers` — the data levers an agent may pull (parser spec, rule, prompt, model, source) and the check of a proposal.
  `budget` — daily budgets and run limits per agent.
  `parser_doctor` — a new parser spec version for a drifted (or missing) site parser.
  `rule_auditor` — a bounded threshold change for a rule that rejects values other sources later confirm.
  `extractor_tuner` — a new extraction prompt version or extractor model when extractor accuracy falls.
  `scout` — new sources for gaps (area × market with no accepted values).
  `blame_judge` — settles a disputed wrong signal (which component was wrong).
  `evaluator` — daily, code only: the accuracy KPI and the fate of changes already behind the gates.
Flow: worker task → agent (model call, within budget) → proposal → levers.validate → gates.journal.propose → gates.
Depends on: domain, gates, parsing, replay, reputation, snapshots, registry, infrastructure, worker, shared
  (infrastructure.llm, db, config, evidence), observability.metrics; langgraph, pydantic, sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them); run by worker.handlers.
Note: scout.py (600+ lines) and parser_doctor.py (400+) are over the module size limit.
"""

__all__: list[str] = [
    "blame_judge",
    "budget",
    "evaluator",
    "extractor_tuner",
    "levers",
    "parser_doctor",
    "rule_auditor",
    "scout",
]
