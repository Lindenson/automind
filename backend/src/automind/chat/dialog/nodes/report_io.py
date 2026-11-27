"""The contracts of the answering nodes (spec 014 T102): report, answer (from context) and general — what each reads
from the turn state and writes back, over today's flat keys."""

from __future__ import annotations

from pydantic import SkipValidation

from automind.chat.application.services.interpretation.contracts import Preset
from automind.chat.application.services.report.blocks.notice import Notice
from automind.chat.application.services.research.contracts import JobResult
from automind.chat.dialog.contract import NodeIn, NodeOut
from automind.chat.dialog.state import DecisionState
from automind.chat.domain.decision import RequestKind
from automind.shared.contracts.json import JsonObject


class ComposeIn(NodeIn):
    """What composing a report or an answer reads: the person's words and language, the request, the policy's
    decision, a button's preset, the turn's notices, and the research of this turn (for a critique's lead)."""

    language: str | None = "en"
    user_text: str | None = ""
    request_kind: RequestKind | None = None
    decision: SkipValidation[DecisionState | None] = None
    preset: SkipValidation[Preset | None] = None
    notices: SkipValidation[list[Notice]] = []
    research_results: SkipValidation[list[JobResult]] = []
    research_done: bool | None = None
    persona_changed: bool | None = None
    case_changed: bool | None = None


class AnswerIn(ComposeIn):
    """An answer from context needs the policy's decision (`nothing_new`)."""

    decision: SkipValidation[DecisionState]


class ReportOut(NodeOut):
    """The report: its text and blocks, the turn's action, the fingerprint shown, the case version saved."""

    reply_text: str
    blocks: SkipValidation[list[JsonObject]]
    action: str
    fingerprint: str
    case_version: int


class ReplyOut(NodeOut):
    """A reply that ends the turn: its text, its blocks and the turn's action."""

    reply_text: str
    blocks: SkipValidation[list[JsonObject]]
    action: str


class GeneralIn(NodeIn):
    """A general answer reads the person's words and language."""

    language: str | None = "en"
    user_text: str | None = ""
