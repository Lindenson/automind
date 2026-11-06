"""Chat · chat.dialog.policy: which action a turn takes next — a fixed, ordered chain of rules (research R5). The LLM
never chooses the action; the `Policy` protocol is the seam for a later planner that proposes and code gates.

Owns: `contracts` — Situation (everything known in one pass), Rule, Policy, the limits; `rules` — the rules by phase;
  `chain` — RULES in order, RulesInOrder (the policy) and `decide(...)`.
Flow: understand → assess → Situation → RulesInOrder.decide → Action → the graph routes on Action.kind.
Depends on: chat.domain. Must not depend on: the application, infrastructure, sqlalchemy, langgraph.
Public API: the names below.
"""

from automind.chat.dialog.policy.chain import RULES, RulesInOrder, decide
from automind.chat.dialog.policy.contracts import MAX_HOPS, Policy, Rule, Situation
from automind.chat.dialog.policy.rules.general import wants_candidates

__all__ = ["MAX_HOPS", "RULES", "Policy", "Rule", "RulesInOrder", "Situation", "decide", "wants_candidates"]
