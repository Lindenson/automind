"""The contract of the identify node (spec 014 T102): what re-identifying the case's cars reads and writes."""

from __future__ import annotations

from pydantic import SkipValidation

from automind.chat.application.services.report.blocks.notice import Notice
from automind.chat.dialog.contract import NodeIn, NodeOut
from automind.shared.contracts.json import JsonObject


class IdentifyIn(NodeIn):
    """The cars whose answer was not understood, the delta the message made, the turn's language and notices."""

    not_understood: SkipValidation[list[str] | None] = None
    interpretation: SkipValidation[JsonObject | None] = None
    language: str | None = None
    notices: SkipValidation[list[Notice]] = []


class IdentifyOut(NodeOut):
    """The cars still not understood; the case version when it was saved; the notices with the new ones."""

    not_understood: SkipValidation[list[str]]
    case_version: int = 0
    notices: SkipValidation[list[Notice]] = []
