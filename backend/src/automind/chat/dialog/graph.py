"""The turn graph (plan.md "Turn graph"; research R2, R5).

    START → load_case → interpret (LLM) → apply_delta (code) → identify (spec 005) → assess (catalog) → policy
      ├─ ANSWER_GENERAL      → general
      ├─ ASK                 → ask → END (questions pending)
      ├─ CONFIRM_VARIANTS    → prepare_variants → wait (interrupt) → apply_variants → assess | interpret
      ├─ CONFIRM_INTAKE      → prepare_intake → wait → apply_intake → assess | identify | interpret (005)
      ├─ CONFIRM_COST        → prepare_cost → wait (interrupt) → apply_cost → assess | interpret
      ├─ RESEARCH            → plan_research → Send(research_job)×N → collect_round ↺ next_round (gaps,
      │                        ≤ depth rounds) → after_research → assess
      ├─ ANSWER_FROM_CONTEXT → answer
      └─ REPORT              → report

One persistent thread per chat (thread_id = chat_id) on the Postgres checkpointer.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from automind.chat.dialog.nodes import confirm, feasibility, identify, report, research, understand
from automind.chat.dialog.outcomes import traced
from automind.chat.dialog.retry import LLM_RETRY
from automind.chat.dialog.runner import TurnContext
from automind.chat.dialog.state import TurnState

MCP_TOOLS: list[Any] = []  # set by the API lifespan (persistent MCP stdio session)


def build_graph(checkpointer: Any = None, tools: list[Any] | None = None) -> Any:
    g = StateGraph(TurnState, context_schema=TurnContext)
    _add = g.add_node

    def add_node(name: str, fn: Any, **kw: Any) -> Any:  # spec 010: record the path of each turn
        return _add(name, traced(name, fn), **kw)

    g.add_node = add_node  # type: ignore[method-assign]
    g.add_node("load_case", understand.load_case_node)
    g.add_node("interpret", understand.interpret_node, retry_policy=LLM_RETRY)
    g.add_node("apply_delta", understand.apply_delta_node)
    g.add_node("identify", identify.identify_node)
    g.add_node("assess", understand.assess_node)
    g.add_node("policy", understand.policy_node)
    g.add_node("general", report.general_node, retry_policy=LLM_RETRY)
    g.add_node("ask", confirm.ask_node)
    g.add_node("prepare_variants", confirm.prepare_variants)
    g.add_node("wait_variants", confirm.wait_confirm)
    g.add_node("apply_variants", confirm.apply_variants)
    g.add_node("prepare_cost", confirm.prepare_cost)
    g.add_node("wait_cost", confirm.wait_confirm)
    g.add_node("apply_cost", confirm.apply_cost)
    g.add_node("plan_research", research.plan_research)
    g.add_node("research_job", research.research_job)
    g.add_node("collect_round", research.collect_round)
    g.add_node("next_round", research.next_round)
    g.add_node("after_research", research.after_research)
    g.add_node("prepare_feasibility", feasibility.prepare_feasibility)
    g.add_node("wait_feasibility", confirm.wait_confirm)
    g.add_node("apply_feasibility", feasibility.apply_feasibility)
    g.add_node("alternatives", feasibility.alternatives)
    g.add_node("prepare_limit", research.prepare_limit)
    g.add_node("wait_limit", confirm.wait_confirm)
    g.add_node("apply_limit", research.apply_limit)
    g.add_node("prepare_intake", confirm.prepare_intake)
    g.add_node("select_candidates", confirm.select_candidates)
    g.add_node("wait_intake", confirm.wait_confirm)
    g.add_node("apply_intake", confirm.apply_intake)
    g.add_node("answer", report.answer_node, retry_policy=LLM_RETRY)
    g.add_node("report", report.make_report_node(), retry_policy=LLM_RETRY)

    g.add_edge(START, "load_case")
    g.add_edge("load_case", "interpret")
    g.add_conditional_edges("interpret", understand.route_after_interpret, {"end": END, "apply_delta": "apply_delta"})
    g.add_conditional_edges("apply_delta", understand.route_after_apply, {"end": END, "assess": "identify"})
    g.add_edge("identify", "assess")
    g.add_edge("assess", "policy")
    g.add_conditional_edges(
        "policy",
        understand.route_policy,
        [
            "general",
            "ask",
            "prepare_variants",
            "prepare_cost",
            "plan_research",
            "answer",
            "report",
            "prepare_feasibility",
            "prepare_intake",
            "select_candidates",
        ],
    )
    # spec 007 US7: candidates become the case's cars and go through identification and the card
    g.add_conditional_edges("select_candidates", confirm.route_after_candidates,
                            {"identify": "identify", "general": "general"})  # fmt: skip
    g.add_edge("prepare_intake", "wait_intake")  # spec 005: one card for the cars, the person and the cost
    g.add_edge("wait_intake", "apply_intake")
    g.add_conditional_edges(
        "apply_intake",
        confirm.route_after_apply,
        {"assess": "assess", "interpret": "interpret", "identify": "identify"},
    )
    g.add_conditional_edges(  # every car unknown: nothing to confirm, ask about the model instead
        "prepare_variants", confirm.route_after_prepare, {"wait": "wait_variants", "assess": "assess"}
    )
    g.add_edge("wait_variants", "apply_variants")
    g.add_conditional_edges(
        "apply_variants", confirm.route_after_apply, {"assess": "assess", "interpret": "interpret", "end": END}
    )
    g.add_edge("prepare_feasibility", "wait_feasibility")
    g.add_edge("wait_feasibility", "apply_feasibility")
    g.add_conditional_edges(
        "apply_feasibility",
        feasibility.route_after_apply,
        {"assess": "assess", "interpret": "interpret", "alternatives": "alternatives"},
    )
    g.add_edge("prepare_cost", "wait_cost")
    g.add_edge("wait_cost", "apply_cost")
    g.add_conditional_edges("apply_cost", confirm.route_after_apply, {"assess": "assess", "interpret": "interpret"})
    g.add_conditional_edges("plan_research", research.fan_out, ["research_job", "after_research"])
    g.add_edge("research_job", "collect_round")
    g.add_conditional_edges("collect_round", research.route_round, ["next_round", "after_research", "prepare_limit"])
    g.add_edge("prepare_limit", "wait_limit")
    g.add_edge("wait_limit", "apply_limit")
    g.add_conditional_edges("apply_limit", research.route_after_limit, ["next_round", "after_research", "interpret"])
    g.add_conditional_edges("next_round", research.fan_out, ["research_job", "after_research"])
    g.add_edge("after_research", "assess")
    for terminal in ("general", "ask", "answer", "report", "alternatives"):
        g.add_edge(terminal, END)
    return g.compile(checkpointer=checkpointer)
