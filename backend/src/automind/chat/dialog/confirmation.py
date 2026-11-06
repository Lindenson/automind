"""The confirmation pattern of the dialog, defined once: a turn asks the person something and waits for the answer.

Every confirmation is three nodes with fixed ids — `prepare_<kind>` (build the question), `wait_<kind>` (pause the
turn: a LangGraph interrupt; the answer comes with the person's next message, even after a restart) and
`apply_<kind>` (use the answer) — and two decisions: an optional one after prepare (nothing to ask → skip the wait)
and one after apply (where the turn goes on). The five confirmations of the chat are configurations of this pattern
(graph.CONFIRMATIONS): the intake card, variants, research cost, feasibility, the research limit.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import Any

Node = Callable[..., Any]
Targets = dict[Hashable, str] | Sequence[str]


@dataclass(frozen=True)
class Route:
    decide: Callable[..., Any]  # state -> one of the targets' keys
    targets: Targets


@dataclass(frozen=True)
class Confirmation:
    kind: str
    prepare: Node
    apply: Node
    after_apply: Route
    after_prepare: Route | None = None  # prepare may find nothing to ask and skip the wait


def add_confirmation(graph: Any, c: Confirmation, wait: Node) -> None:
    """Add the three nodes of `c` and their transitions to `graph` (node ids: prepare_/wait_/apply_ + kind)."""
    prepare, waiting, apply = f"prepare_{c.kind}", f"wait_{c.kind}", f"apply_{c.kind}"
    graph.add_node(prepare, c.prepare)
    graph.add_node(waiting, wait)
    graph.add_node(apply, c.apply)
    if c.after_prepare is None:
        graph.add_edge(prepare, waiting)
    else:
        graph.add_conditional_edges(prepare, c.after_prepare.decide, c.after_prepare.targets)
    graph.add_edge(waiting, apply)
    graph.add_conditional_edges(apply, c.after_apply.decide, c.after_apply.targets)
