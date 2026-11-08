"""The turn graph: the dialog state machine of one chat turn (plan.md "Turn graph"; research R2, R5), as tables.

    START → load_case → interpret (LLM) → apply_delta (code) → identify (spec 005) → assess (catalog) → policy
    policy decides the action (chat.dialog.policy) and the graph routes on it (POLICY_ROUTES):
      answer      general | answer | report                                       → END
      ask         ask                                                             → END (the next message continues)
      confirm     prepare_<kind> → wait_<kind> (interrupt) → apply_<kind> → assess | interpret | …  (CONFIRMATIONS)
      research    plan_research → research_job × N (parallel) → collect_round ↺ next_round → after_research → assess
      candidates  select_candidates → identify | general

One persistent thread per chat (thread_id = chat_id) on the Postgres checkpointer. Node ids are part of the stored
state (a pending interrupt resumes by node id): they never change (tests/graph/test_graph_shape.py).
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from automind.chat.dialog.confirmation import Confirmation, Route, add_confirmation
from automind.chat.dialog.nodes import confirm, feasibility, identify, report, research, understand
from automind.chat.dialog.retry import LLM_RETRY
from automind.chat.dialog.state import TurnState
from automind.chat.dialog.tracing import traced
from automind.chat.dialog.turn.context import TurnContext

MCP_TOOLS: list[Any] = []  # set by the API lifespan (persistent MCP stdio session)

# --- nodes outside the confirmations: (id, function, uses a model → retried) -------------------------------------
NODES: tuple[tuple[str, Any, bool], ...] = (
    ("load_case", understand.load_case_node, False),
    ("interpret", understand.interpret_node, True),
    ("apply_delta", understand.apply_delta_node, False),
    ("identify", identify.identify_node, False),
    ("assess", understand.assess_node, False),
    ("policy", understand.policy_node, False),
    ("general", report.general_node, True),
    ("ask", confirm.ask_node, False),
    ("select_candidates", confirm.select_candidates, False),
    ("plan_research", research.plan_research, False),
    ("research_job", research.research_job, False),
    ("collect_round", research.collect_round, False),
    ("next_round", research.next_round, False),
    ("after_research", research.after_research, False),
    ("alternatives", feasibility.alternatives, False),
    ("answer", report.answer_node, True),
    ("report", report.make_report_node(), True),
)

# --- what the policy's action leads to (understand.route_policy maps Action.kind to these node ids) ----------------
POLICY_ROUTES = ["general", "ask", "prepare_variants", "prepare_cost", "plan_research", "answer", "report",
                 "prepare_feasibility", "prepare_intake", "select_candidates"]  # fmt: skip

# --- the five confirmations (chat.dialog.confirmation) ----------------------------------------------------------
CONFIRMATIONS: tuple[Confirmation, ...] = (
    # spec 005: the cars, the person and the cost on one card
    Confirmation("intake", confirm.prepare_intake, confirm.apply_intake,
                 Route(confirm.route_after_apply, {"assess": "assess", "interpret": "interpret",
                                                   "identify": "identify"})),
    Confirmation("variants", confirm.prepare_variants, confirm.apply_variants,
                 Route(confirm.route_after_apply, {"assess": "assess", "interpret": "interpret", "end": END}),
                 # every car unknown: nothing to confirm, ask about the model instead
                 after_prepare=Route(confirm.route_after_prepare, {"wait": "wait_variants", "assess": "assess"})),
    Confirmation("cost", confirm.prepare_cost, confirm.apply_cost,
                 Route(confirm.route_after_apply, {"assess": "assess", "interpret": "interpret"})),
    Confirmation("feasibility", feasibility.prepare_feasibility, feasibility.apply_feasibility,
                 Route(feasibility.route_after_apply,
                       {"assess": "assess", "interpret": "interpret", "alternatives": "alternatives"})),
    Confirmation("limit", research.prepare_limit, research.apply_limit,  # research paused at a limit: go on or stop
                 Route(research.route_after_limit, ["next_round", "after_research", "interpret"])),
)  # fmt: skip

TERMINALS = ("general", "ask", "answer", "report", "alternatives")


def build_graph(checkpointer: Any = None, tools: list[Any] | None = None) -> Any:
    g = StateGraph(TurnState, context_schema=TurnContext)
    _add = g.add_node

    def add_node(name: str, fn: Any, **kw: Any) -> Any:  # spec 010: record the path of each turn
        return _add(name, traced(name, fn), **kw)

    g.add_node = add_node  # type: ignore[method-assign]
    for name, fn, uses_model in NODES:
        g.add_node(name, fn, retry_policy=LLM_RETRY if uses_model else None)
    for c in CONFIRMATIONS:
        add_confirmation(g, c, confirm.wait_confirm)

    # understand → decide
    g.add_edge(START, "load_case")
    g.add_edge("load_case", "interpret")
    g.add_conditional_edges("interpret", understand.route_after_interpret, {"end": END, "apply_delta": "apply_delta"})
    g.add_conditional_edges("apply_delta", understand.route_after_apply, {"end": END, "assess": "identify"})
    g.add_edge("identify", "assess")
    g.add_edge("assess", "policy")
    g.add_conditional_edges("policy", understand.route_policy, POLICY_ROUTES)
    # spec 007 US7: candidates become the case's cars and go through identification and the card
    g.add_conditional_edges("select_candidates", confirm.route_after_candidates,
                            {"identify": "identify", "general": "general"})  # fmt: skip
    # research: parallel jobs per car × area, gap rounds bounded by depth, a pause at a limit
    g.add_conditional_edges("plan_research", research.fan_out, ["research_job", "after_research"])
    g.add_edge("research_job", "collect_round")
    g.add_conditional_edges("collect_round", research.route_round, ["next_round", "after_research", "prepare_limit"])
    g.add_conditional_edges("next_round", research.fan_out, ["research_job", "after_research"])
    g.add_edge("after_research", "assess")
    for terminal in TERMINALS:
        g.add_edge(terminal, END)
    return g.compile(checkpointer=checkpointer)
