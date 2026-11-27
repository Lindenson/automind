"""The contracts of the asking and confirming nodes (spec 014 T102): ask, select_candidates, the wait of every
confirmation, and the prepare/apply pairs of variants, cost and the intake card — over today's flat keys."""

from __future__ import annotations

from pydantic import SkipValidation

from automind.chat.application.services.report.blocks.notice import Notice
from automind.chat.application.services.research.contracts import PlanState
from automind.chat.dialog.contract import NodeIn, NodeOut
from automind.chat.dialog.state import DecisionState
from automind.shared.contracts.json import JsonObject


class QuestionsIn(NodeIn):
    """The questions or cars the policy chose, the assessed cars, the turn's notices and the open answers."""

    decision: SkipValidation[DecisionState]
    assessments: SkipValidation[dict[str, JsonObject]] = {}
    notices: SkipValidation[list[Notice]] = []
    not_understood: SkipValidation[list[str] | None] = None
    user_text: str | None = None


class AskIn(QuestionsIn):
    """What ask reads; the language as the state holds it (`"en"` when the key is missing)."""

    language: SkipValidation[str] = "en"


class AskOut(NodeOut):
    """The questions as the reply (the turn ends; the next message continues)."""

    reply_text: str
    blocks: SkipValidation[list[JsonObject]]
    action: str


class PrepareVariantsIn(QuestionsIn):
    """The cars to confirm (the policy's decision) and their catalogue candidates; language as the chat's."""

    language: str | None = None


class ConfirmOut(NodeOut):
    """A prepared question (None: nothing to ask)."""

    confirm_payload: SkipValidation[JsonObject | None]


class PrepareVariantsOut(ConfirmOut):
    """The proposals to confirm with the notices of the lookup; `route` assess when every car was unknown."""

    notices: SkipValidation[list[Notice]]
    route: str = "assess"


class WaitIn(NodeIn):
    """The question the turn waits on."""

    confirm_payload: SkipValidation[JsonObject | None]


class WaitOut(NodeOut):
    """The person's answer (a button's dict, or typed words as `{"choice": "text", "text": …}`)."""

    resume: SkipValidation[JsonObject]


class ResumeIn(NodeIn):
    """A confirmation's answer and the turn's language."""

    resume: SkipValidation[JsonObject | None] = None
    language: str | None = None


class PlanResumeIn(ResumeIn):
    """An answer to a question about the research plan: the plan (its key remembers a refusal)."""

    research_plan: SkipValidation[PlanState | None] = None


class CostResumeIn(NodeIn):
    """The cost answer and the plan it answers (its key remembers a refusal)."""

    resume: SkipValidation[JsonObject | None] = None
    research_plan: SkipValidation[PlanState | None] = None


class VariantsAppliedOut(NodeOut):
    """Where the turn goes after the variants answer (`route`: interpret, end, assess), the question closed, typed
    words as the new message, or the reply when the person skipped."""

    route: str
    confirm_payload: SkipValidation[JsonObject | None] = None
    resume: SkipValidation[JsonObject | None] = None
    user_text: str = ""
    action: str = ""
    reply_text: str = ""


class ResearchAnsweredOut(NodeOut):
    """Where the turn goes after a research question (cost, intake card), the question closed, typed words as the new
    message, and the research approved or declined."""

    route: str
    confirm_payload: SkipValidation[JsonObject | None]
    resume: SkipValidation[JsonObject | None]
    user_text: str = ""
    cost_approved: bool = False
    research_declined: bool = False


class CostIn(NodeIn):
    """What a research question shows: the policy's decision (cars, over the cap), the estimate, the plan."""

    decision: SkipValidation[DecisionState]
    cost_estimate: float | None = None
    language: str | None = None
    research_plan: SkipValidation[PlanState | None] = None


class SelectCandidatesIn(NodeIn):
    """Choosing candidates reads only the case."""


class SelectCandidatesOut(NodeOut):
    """identify when candidates (or a make's question) became the case's cars, else general."""

    route: str
