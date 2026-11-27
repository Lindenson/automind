"""Chat · chat.dialog.contract: the typed contract of every graph node (spec 014) — what it reads, what it writes,
who may write each state key, and what happens when a node breaks it.

Owns: `node` — the `@node(name, reads=, writes=, retry=)` decorator and `Node`, `Retry`; `models` — the `NodeIn` /
  `NodeOut` bases over the flat `TurnState` keys (step C1); `owners` — the registry state key → writers, append-only
  keys; `violation` — `ContractError`, strict in tests, log + metric in production; `table` — the contract table
  "node · retry · reads · writes · next" (`python -m automind.chat.dialog.contract`, committed as
  specs/014-node-contracts/contract.md).
Depends on: chat.dialog (state, context, tracing, retry, turn.context), langgraph, pydantic, shared.infrastructure
  (settings, metrics). Must not depend on: chat.dialog.nodes, chat.dialog.graph (only the CLI, `__main__`, imports
  the graph).
Public API: the names in __all__.
"""

from automind.chat.dialog.contract.models import NodeIn, NodeOut, TurnUpdate
from automind.chat.dialog.contract.node import Node, Retry, node
from automind.chat.dialog.contract.violation import ContractError, ViolationKind

__all__ = ["ContractError", "Node", "NodeIn", "NodeOut", "Retry", "TurnUpdate", "ViolationKind", "node"]
