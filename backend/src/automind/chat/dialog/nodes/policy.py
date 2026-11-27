"""The policy node (spec 015 D3): the situation of this pass, the policy's decision on it, the pass counted.

A situation that breaks an invariant (`policy.situation`) fails the turn when the config is strict (tests; the
`PolicyInputError` ends it as any failed node does); otherwise it is logged and counted in
`automind_policy_input_errors_total{field}` and the policy decides on the situation as built."""

from __future__ import annotations

import logging
from typing import cast

from automind.chat.dialog.contract import Retry, node
from automind.chat.dialog.nodes.policy_io import PolicyIn, PolicyOut
from automind.chat.dialog.policy import PolicyInputError, decide, situation_from
from automind.chat.dialog.state import DecisionState
from automind.chat.dialog.turn.context import TurnContext
from automind.shared.infrastructure.metrics import prom

log = logging.getLogger(__name__)


@node("policy", reads=PolicyIn, writes=PolicyOut, retry=Retry.NONE)
async def policy_node(inp: PolicyIn, c: TurnContext) -> PolicyOut:
    """The policy's decision for this pass over the case and the assessed cars (spec 007 FR-027: passes counted)."""
    pass_no = (inp.hops or 0) + 1
    read = situation_from(inp, case=await c.case(), case_version=await c.case_version(),
                          last_fingerprint=await c.last_report_fingerprint(), pass_no=pass_no)  # fmt: skip
    for error in read.errors:
        _broken(error, c)
    action = decide(read.situation, c.ports.policy).action
    return PolicyOut(decision=cast(DecisionState, action.model_dump(mode="json")), action=action.kind, hops=pass_no)


def _broken(error: PolicyInputError, c: TurnContext) -> None:
    """Raise `error` in strict mode, else log and count it."""
    if c.ports.policy.strict_inputs:
        raise error
    log.warning("policy.input_error chat_id=%s turn_id=%s field=%s %s", c.chat_id, c.turn_id, error.field, error)
    prom.inc("policy_input_errors", field=error.field)
