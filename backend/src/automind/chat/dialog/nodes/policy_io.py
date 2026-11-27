"""The contract of the policy node (spec 014 T102, spec 015 T214): what it reads from the turn state besides the case
— the request, the assessed cars and the case version they were assessed on, the cost, the confirmations, the
feasibility fact, the passes so far — and what it writes back."""

from __future__ import annotations

from pydantic import SkipValidation

from automind.chat.dialog.contract import NodeIn, NodeOut
from automind.chat.dialog.state import DecisionState
from automind.chat.domain.decision import RequestKind
from automind.shared.contracts.json import JsonObject


class PolicyIn(NodeIn):
    """What the policy decides on besides the case (`policy.situation.PolicyFacts`)."""

    request_kind: RequestKind | None = None
    assessments: SkipValidation[dict[str, JsonObject]] = {}
    assessed_version: int | None = None
    cost_estimate: float | None = None
    cost_approved: bool | None = None
    research_declined: bool | None = None
    research_done: bool | None = None
    case_changed: bool | None = True
    feasibility_pending: bool | None = None
    hops: int | None = None


class PolicyOut(NodeOut):
    """The policy's Action as plain data, its kind as the turn's action, and the pass counted."""

    decision: SkipValidation[DecisionState]
    action: str
    hops: int
