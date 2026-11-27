"""Where each action of the policy leads (spec 015 D4): one table, `ROUTES`, from which the graph builds the policy's
router and path map. `Continuation` says what follows the target node: the turn ends (END), waits for the person in
an interrupt (SUSPEND), or comes back to the policy through assess (LOOP)."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final, NamedTuple

from automind.chat.domain.decision import ActionKind

NodeId = str


class Continuation(StrEnum):
    """What follows the node an action leads to."""

    END = "end"  # the turn ends with the node's reply
    SUSPEND = "suspend"  # a confirmation waits for the person (interrupt); the next message resumes it
    LOOP = "loop"  # the node changes the case or its data, then the policy decides again


class Route(NamedTuple):
    """The node an action leads to and what follows it."""

    node: NodeId
    continuation: Continuation


ROUTES: Final[MappingProxyType[ActionKind, Route]] = MappingProxyType({
    "ANSWER_GENERAL": Route("general", Continuation.END),
    "ASK": Route("ask", Continuation.END),
    "CONFIRM_VARIANTS": Route("prepare_variants", Continuation.SUSPEND),
    "CONFIRM_COST": Route("prepare_cost", Continuation.SUSPEND),
    "RESEARCH": Route("plan_research", Continuation.LOOP),
    "ANSWER_FROM_CONTEXT": Route("answer", Continuation.END),
    "REPORT": Route("report", Continuation.END),
    "RESCORE": Route("report", Continuation.END),  # spec 007: the report node recomputes and says what changed
    "FEASIBILITY": Route("prepare_feasibility", Continuation.SUSPEND),
    "CONFIRM_INTAKE": Route("prepare_intake", Continuation.SUSPEND),
    "SELECT_CANDIDATES": Route("select_candidates", Continuation.LOOP),
})  # fmt: skip


def route_of(kind: ActionKind) -> NodeId:
    """The node the action `kind` leads to."""
    return ROUTES[kind].node


def policy_targets() -> list[NodeId]:
    """Every node an action may lead to, once each, in the order of `ROUTES` (the graph's path map)."""
    return list(dict.fromkeys(r.node for r in ROUTES.values()))
