"""Chat · chat.dialog: the dialog state machine — one chat turn as an explicit machine of named phases, run on
LangGraph (pause/resume across messages, parallel research, retries), with its runner and the reply texts.

Owns:
  `phases` — the phases (UNDERSTAND → DECIDE → ASK | CONFIRM | RESEARCH | ANSWER) and the confirmation kinds;
  `graph` — the transitions as tables (nodes, policy routes, confirmations, research fan-out);
  `policy` — which action a pass takes: an ordered chain of rules behind the `Policy` protocol;
  `confirmation` — the prepare → wait → apply pattern, defined once, configured five times;
  `state` — the turn state (plain data: TypedDicts, never classes in a checkpoint);
  `nodes` — the graph nodes; `context` — what a node reads from the runtime (ports, case load/save);
  `runner` — `ChatRunner`: what a message does (start / answer / replace / busy), one task per chat, cancel, restart;
  `turn` — the turn's life apart from the dialog logic: entry table, execution, endings (exception → plain answer),
    status writes through the lifecycle table (`chat.domain.turn.TRANSITIONS`), replies, outcome;
  `tracing` — the per-turn path of nodes and signals; `retry` — transient provider errors;
  `guard` — every number in AI text must exist in the data; `agents` — persona reporters' scoped tools;
  `phrases` / `report_text` — fixed texts in ru / es / en; `prompts` — the versioned LLM prompts.
Flow: delivery.web → runner.ChatRunner → turn.TurnExecution → graph (phases) → nodes → application services /
  domain; policy decides.
Depends on: chat.application, chat.domain, langgraph, acquisition.api, shared.
Must not depend on: delivery.web, chat.infrastructure (gets ports from the composition root).
Note: nodes still hold logic (compute.py 719 lines, understand.py 500); they shrink to ≤ 30-line adapters in S7–S9.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = [
    "agents",
    "confirmation",
    "context",
    "graph",
    "guard",
    "nodes",
    "phases",
    "phrases",
    "policy",
    "prompts",
    "report_text",
    "retry",
    "runner",
    "state",
    "tracing",
    "turn",
]
