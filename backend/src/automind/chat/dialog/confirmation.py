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

from automind.chat.dialog.contract import Node

Targets = dict[Hashable, str] | Sequence[str]
AnyNode = Node[Any, Any]  # a node of any contract (the In/Out types differ per confirmation)
WaitFactory = Callable[[str], AnyNode]  # kind -> the wait node `wait_<kind>`


class ConfirmationIdError(ValueError):
    """A confirmation's node is declared under another id than `prepare_/wait_/apply_<kind>` (a bug: checkpoints
    resume by node id)."""


@dataclass(frozen=True)
class Route:
    decide: Callable[..., Any]  # state -> one of the targets' keys
    targets: Targets


@dataclass(frozen=True)
class Confirmation:
    """One confirmation: its kind, its prepare and apply nodes (ids `prepare_<kind>`, `apply_<kind>`) and where the
    turn goes after each."""

    kind: str
    prepare: AnyNode
    apply: AnyNode
    after_apply: Route
    after_prepare: Route | None = None  # prepare may find nothing to ask and skip the wait

    def nodes(self, wait: WaitFactory) -> tuple[AnyNode, ...]:
        """prepare, wait (made by `wait` for this kind) and apply, in the order the turn runs them; their ids are
        fixed by the kind (checkpoints resume by them). Raises `ConfirmationIdError` for a node under another id."""
        steps = (self.prepare, wait(self.kind), self.apply)
        ids = (f"prepare_{self.kind}", f"wait_{self.kind}", f"apply_{self.kind}")
        if tuple(n.name for n in steps) != ids:
            raise ConfirmationIdError(f"confirmation {self.kind}: nodes {[n.name for n in steps]} are not {list(ids)}")
        return steps


def add_confirmation(graph: Any, c: Confirmation, wait: WaitFactory) -> None:
    """Add the three nodes of `c` and their transitions to `graph` (node ids: prepare_/wait_/apply_ + kind)."""
    steps = c.nodes(wait)
    for n in steps:
        graph.add_node(n.name, n.for_graph(), retry_policy=n.retry.policy())
    prepare, waiting, apply = (n.name for n in steps)
    if c.after_prepare is None:
        graph.add_edge(prepare, waiting)
    else:
        graph.add_conditional_edges(prepare, c.after_prepare.decide, c.after_prepare.targets)
    graph.add_edge(waiting, apply)
    graph.add_conditional_edges(apply, c.after_apply.decide, c.after_apply.targets)
