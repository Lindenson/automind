"""The policy node (spec 015 D3, D5): the situation of this pass, the policy's decision on it, the pass counted and
recorded.

A situation that breaks an invariant (`policy.situation`) fails the turn when the config is strict (tests; the
`PolicyInputError` ends it as any failed node does); otherwise it is logged and counted in
`automind_policy_input_errors_total{field}` and the policy decides on the situation as built. Every pass is logged
(`policy.decided`), counted (`automind_policy_decisions_total{rule,action}`, the limit pass in
`automind_policy_pass_limit_total`) and written to the `DecisionLog`; a store that cannot be written
(`StoreUnavailable`) is logged at ERROR and counted in `automind_policy_record_errors_total`, and the turn goes on."""

from __future__ import annotations

import logging
from typing import cast

from automind.chat.application.ports import StoreUnavailable
from automind.chat.dialog.contract import Retry, node
from automind.chat.dialog.nodes.policy_io import PolicyIn, PolicyOut
from automind.chat.dialog.policy import (
    Decision,
    PolicyInputError,
    Situation,
    config_json,
    decide,
    record_of,
    situation_from,
)
from automind.chat.dialog.policy.rules.limits import PassLimit
from automind.chat.dialog.state import DecisionState
from automind.chat.dialog.turn.context import TurnContext
from automind.shared.infrastructure.metrics import policy as metrics

log = logging.getLogger(__name__)


@node("policy", reads=PolicyIn, writes=PolicyOut, retry=Retry.NONE)
async def policy_node(inp: PolicyIn, c: TurnContext) -> PolicyOut:
    """The policy's decision for this pass over the case and the assessed cars (spec 007 FR-027: passes counted)."""
    pass_no = (inp.hops or 0) + 1
    read = situation_from(inp, case=await c.case(), case_version=await c.case_version(),
                          last_fingerprint=await c.last_report_fingerprint(), pass_no=pass_no)  # fmt: skip
    for error in read.errors:
        _broken(error, c)
    decision = decide(read.situation, c.ports.policy)
    await _record(decision, read.situation, c)
    action = decision.action
    return PolicyOut(decision=cast(DecisionState, action.model_dump(mode="json")), action=action.kind, hops=pass_no)


def _broken(error: PolicyInputError, c: TurnContext) -> None:
    """Raise `error` in strict mode, else log and count it."""
    if c.ports.policy.strict_inputs:
        raise error
    log.warning("policy.input_error chat_id=%s turn_id=%s field=%s %s", c.chat_id, c.turn_id, error.field, error)
    metrics.input_error(error.field)


async def _record(d: Decision, s: Situation, c: TurnContext) -> None:
    """Log, count and store the pass (see the module docstring)."""
    rec = record_of(d, s, c.ports.policy, chat_id=c.chat_id, turn_id=c.turn_id, case_version=await c.case_version())
    log.info("policy.decided chat_id=%s turn_id=%s pass_no=%s decided_by=%s action=%s next_node=%s",
             c.chat_id, c.turn_id, rec.pass_no, rec.decided_by, d.action.kind, rec.next_node)  # fmt: skip
    metrics.decided(d.decided_by, d.action.kind, pass_limit=d.decided_by == PassLimit.name)
    if c.ports.decisions is None:
        return
    try:
        await c.ports.decisions.record(rec, config_json(c.ports.policy))
    except StoreUnavailable:
        log.exception("policy.record_failed chat_id=%s turn_id=%s pass_no=%s", c.chat_id, c.turn_id, rec.pass_no)
        metrics.record_error()
