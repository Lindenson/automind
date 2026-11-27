"""The `@node` decorator (spec 014 D2, T101): a graph node declared with its id, what it reads, what it writes and
its retry, once for all nodes.

    @node("interpret", reads=InterpretIn, writes=InterpretOut, retry=Retry.PROVIDER)
    async def interpret_node(inp: InterpretIn, c: TurnContext) -> InterpretOut: ...

At declaration the keys are checked against `TurnState` and the owners registry; on every run `Node` records the
node in the turn's path (replaces `tracing.traced`), builds `In` from the state (a missing required key is a
violation), calls the body with typed objects, checks the result is the node's `Out` and that append-only keys keep
their earlier items, and returns the update. A violation raises in strict mode, else is logged and counted
(contract/violation.py).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, TypeVar

from langgraph.runtime import Runtime
from langgraph.types import RetryPolicy
from pydantic import ValidationError

from automind.chat.application.services.research.contracts import JobState
from automind.chat.dialog.context import ctx
from automind.chat.dialog.contract import owners
from automind.chat.dialog.contract.models import NodeIn, NodeOut, TurnUpdate
from automind.chat.dialog.contract.violation import ViolationKind, violated
from automind.chat.dialog.retry import LLM_RETRY
from automind.chat.dialog.state import TurnState
from automind.chat.dialog.tracing import visit
from automind.chat.dialog.turn.context import TurnContext

InT = TypeVar("InT", bound=NodeIn)
OutT = TypeVar("OutT", bound=NodeOut)
GraphCallable = Callable[..., Awaitable[TurnUpdate]]  # what LangGraph registers: (state | job, runtime) -> update
STATE_KEYS = TurnState.__required_keys__ | TurnState.__optional_keys__


class Retry(StrEnum):
    """What a node does when its step fails: PROVIDER retries a transient model-provider failure once
    (`retry.LLM_RETRY`; a budget stop or a bug is never retried); NONE never retries."""

    PROVIDER = "provider"
    NONE = "none"

    def policy(self) -> RetryPolicy | None:
        """The LangGraph retry policy of this setting (None: no retry)."""
        return LLM_RETRY if self is Retry.PROVIDER else None


@dataclass(frozen=True)
class Node(Generic[InT, OutT]):
    """One graph node with its contract. `sent`: the input is a `Send` payload (a research job), not the turn state.
    Calling it with (state, runtime) runs the node as the graph does and returns the state update."""

    name: str
    reads: type[InT]
    writes: type[OutT]
    retry: Retry
    body: Callable[[InT, TurnContext], Awaitable[OutT]]
    sent: bool = False

    async def __call__(self, state: Mapping[str, object], runtime: Runtime[TurnContext]) -> TurnUpdate:
        """Run the node on `state`. Raises `ContractError` on a violation in strict mode; the body's errors pass."""
        visit(self.name)
        inp = _input(self, state)
        out = await self.body(inp, ctx(runtime))
        return _update(self, state, out)

    def for_graph(self) -> GraphCallable:
        """The callable LangGraph registers, annotated with the node's input schema (`TurnState`, or `JobState` for a
        sent node) so the compiled graph's channels stay those of the state."""
        if self.sent:

            async def run_job(job: JobState, runtime: Runtime[TurnContext]) -> TurnUpdate:
                return await self(job, runtime)

            return run_job

        async def run(state: TurnState, runtime: Runtime[TurnContext]) -> TurnUpdate:
            return await self(state, runtime)

        return run


def node(name: str, *, reads: type[InT], writes: type[OutT], retry: Retry = Retry.NONE,
         sent: bool = False) -> Callable[[Callable[[InT, TurnContext], Awaitable[OutT]]], Node[InT, OutT]]:  # fmt: skip
    """Declare a graph node: `name` is its id (never changes: checkpoints resume by it), `reads`/`writes` its
    contract, `retry` its retry setting. The declaration is checked at once (keys of `TurnState`, owners)."""

    def declare(body: Callable[[InT, TurnContext], Awaitable[OutT]]) -> Node[InT, OutT]:
        declared = Node(name, reads, writes, retry, body, sent)
        _check_declaration(declared)
        return declared

    return declare


def _check_declaration(n: Node[InT, OutT]) -> None:
    """Every key read or written is a `TurnState` key (no ad-hoc key) and every write is the node's to make."""
    for key in [] if n.sent else n.reads.model_fields:
        if key not in STATE_KEYS:
            violated(n.name, key, ViolationKind.UNKNOWN, "read, not in TurnState")
    for key in n.writes.model_fields:
        if key not in STATE_KEYS:
            violated(n.name, key, ViolationKind.UNKNOWN, "written, not in TurnState")
        elif not owners.may_write(n.name, key):
            violated(n.name, key, ViolationKind.FOREIGN, "not an owner (contract/owners.py)")


def _input(n: Node[InT, OutT], state: Mapping[str, object]) -> InT:
    """`In` from the state; on a violation (lenient mode) the input as found, like the `state.get` it replaces."""
    try:
        return n.reads.model_validate(dict(state))
    except ValidationError as e:
        for err in e.errors():
            key = str(err["loc"][0]) if err["loc"] else "?"
            kind = ViolationKind.INVALID if key in state else ViolationKind.MISSING
            violated(n.name, key, kind, err["msg"])
        found: dict[str, Any] = {k: state[k] for k in n.reads.model_fields if k in state}  # values as in the state
        return n.reads.model_construct(**found)


def _update(n: Node[InT, OutT], state: Mapping[str, object], out: object) -> TurnUpdate:
    """The update of `out`; a result of another type or an append-only key that lost items is a violation."""
    if not isinstance(out, n.writes):
        violated(n.name, "<return>", ViolationKind.TYPE, f"{type(out).__name__}, expected {n.writes.__name__}")
        return dict(out) if isinstance(out, Mapping) else {}
    update = out.update()
    for key, value in update.items():
        if not owners.keeps_earlier(n.name, key, state.get(key), value):
            violated(n.name, key, ViolationKind.APPEND, "earlier items dropped")
    return update
