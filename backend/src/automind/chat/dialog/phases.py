"""The named phases of the dialog state machine and the kinds of confirmation. A turn always runs
UNDERSTAND → DECIDE, then one of ASK, CONFIRM (pausing for the answer), RESEARCH (and back to DECIDE) or ANSWER.
Every node of the graph belongs to exactly one phase (tests/graph/test_graph_shape.py checks it)."""

from __future__ import annotations

from enum import StrEnum


class Phase(StrEnum):
    UNDERSTAND = "understand"  # read the message into the case: load, interpret (LLM), apply, identify, assess
    DECIDE = "decide"  # the policy chooses the action (chat.dialog.policy)
    ASK = "ask"  # questions; the turn ends, the next message continues
    CONFIRM = "confirm"  # a question the turn waits for (chat.dialog.confirmation)
    RESEARCH = "research"  # parallel acquisition jobs, gap rounds
    ANSWER = "answer"  # general answer, answer from context, report, alternatives


class ConfirmKind(StrEnum):
    INTAKE = "intake"  # the card: cars, profile, research cost (spec 005)
    VARIANTS = "variants"  # ambiguous, used or new variants
    COST = "cost"  # research above the cost threshold
    FEASIBILITY = "feasibility"  # the request does not fit the budget or needs (spec 003)
    LIMIT = "limit"  # research paused at a limit: go on or stop


PHASE_OF: dict[str, Phase] = {
    "load_case": Phase.UNDERSTAND, "interpret": Phase.UNDERSTAND, "apply_delta": Phase.UNDERSTAND,
    "identify": Phase.UNDERSTAND, "assess": Phase.UNDERSTAND, "select_candidates": Phase.UNDERSTAND,
    "policy": Phase.DECIDE,
    "ask": Phase.ASK,
    **{f"{step}_{kind}": Phase.CONFIRM for kind in ConfirmKind for step in ("prepare", "wait", "apply")},
    "plan_research": Phase.RESEARCH, "research_job": Phase.RESEARCH, "collect_round": Phase.RESEARCH,
    "next_round": Phase.RESEARCH, "after_research": Phase.RESEARCH,
    "general": Phase.ANSWER, "answer": Phase.ANSWER, "report": Phase.ANSWER, "alternatives": Phase.ANSWER,
}  # fmt: skip
