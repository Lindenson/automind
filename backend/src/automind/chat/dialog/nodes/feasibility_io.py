"""The contracts of the feasibility nodes (spec 014 T102): prepare/apply of the feasibility question and the
alternatives reply, over today's flat keys."""

from __future__ import annotations

from pydantic import SkipValidation

from automind.chat.dialog.contract import NodeIn, NodeOut
from automind.shared.contracts.json import JsonObject


class FeasibilityIn(NodeIn):
    """The feasibility checks the assessment found (`{results, fingerprint}`) and the turn's language."""

    feasibility: SkipValidation[JsonObject | None] = None
    language: str | None = None


class PrepareFeasibilityOut(NodeOut):
    """The feasibility question and the turn's action (FEASIBILITY)."""

    confirm_payload: SkipValidation[JsonObject]
    action: str


class ApplyFeasibilityIn(NodeIn):
    """The answer and the checks it answers (their fingerprint is acknowledged)."""

    resume: SkipValidation[JsonObject | None] = None
    feasibility: SkipValidation[JsonObject | None] = None


class ApplyFeasibilityOut(NodeOut):
    """Where the turn goes (`route`: interpret, assess, alternatives), the question closed, typed words as the new
    message."""

    route: str
    confirm_payload: SkipValidation[JsonObject | None]
    resume: SkipValidation[JsonObject | None]
    user_text: str = ""


class AlternativesOut(NodeOut):
    """The suggested kinds of cars as the reply, the checks' block, and the turn's action (FEASIBILITY)."""

    reply_text: str
    blocks: SkipValidation[list[JsonObject]]
    action: str
