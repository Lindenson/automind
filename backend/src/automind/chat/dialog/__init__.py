"""Chat · chat.dialog: the conversation machine — the LangGraph turn graph, its runner and the reply texts.

Owns: `graph` — the turn graph (load case → interpret → apply → identify → assess → policy → ask / confirm /
  research / report); `runner` — `ChatRunner`: one thread per chat, one active turn, budgets, resume;
  `state` — graph state; `nodes` — the graph nodes; `guard` — every number in AI text must exist in the data;
  `agents` — persona reporters' scoped MCP tools; `outcomes` — per-turn trace of nodes and signals;
  `retry` — transient provider errors; `phrases` / `report_text` — fixed texts in ru / es / en;
  `prompts` — the versioned LLM prompts.
Flow: delivery.web → `runner.ChatRunner` → `graph.build_graph` → `nodes.*` → application services.
Depends on: chat.application, chat.domain, langgraph, acquisition.api, shared (incl. shared.infrastructure in nodes),
  observability.metrics.
Must not depend on: delivery.web, chat.infrastructure (gets ports from the composition root).
Note: nodes still hold logic (compute.py 718 lines); they shrink to ≤ 30-line adapters in S6–S9.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = [
    "agents",
    "graph",
    "guard",
    "nodes",
    "outcomes",
    "phrases",
    "prompts",
    "report_text",
    "retry",
    "runner",
    "state",
]
