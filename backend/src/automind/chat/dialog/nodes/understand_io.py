"""The contracts of the understanding nodes (spec 014 T102): load_case, interpret, apply_delta, assess — what
each reads from the turn state and writes back, over today's flat keys. The `from_*` builders map a service result
to the update, field for field as the services' former `to_state()` did."""

from __future__ import annotations

from typing import Literal

from pydantic import SkipValidation

from automind.chat.application.services.assessment.contracts import Planned
from automind.chat.application.services.interpretation.contracts import Applied, Preset, Reading
from automind.chat.application.services.report.blocks.notice import Notice
from automind.chat.application.services.research.contracts import JobResult, JobState, LimitHit, PlanRow, PlanState
from automind.chat.dialog.contract import NodeIn, NodeOut
from automind.chat.dialog.state import DecisionState
from automind.chat.domain.decision import RequestKind
from automind.shared.contracts.json import JsonObject

Asked = Literal["ASK"]


class LoadCaseIn(NodeIn):
    """load_case reads nothing from the state: the turn's ids come from the context."""


class LoadCaseOut(NodeOut):
    """The start of a turn: the turn's ids, the case version it starts from, every per-turn key reset
    (`state.PER_TURN_RESET`)."""

    chat_id: str
    turn_id: str
    case_version: int
    language: str
    request_kind: RequestKind | None
    assessments: SkipValidation[dict[str, JsonObject]]
    decision: SkipValidation[DecisionState]
    action: str | None
    cost_estimate: float | None
    research_plan: SkipValidation[PlanState]
    jobs: SkipValidation[list[JobState]]
    round: int
    cost_approved: bool
    research_declined: bool
    research_done: bool
    limit_hit: SkipValidation[LimitHit | None]
    limit_extensions: int
    feasibility: SkipValidation[JsonObject | None]
    feasibility_pending: bool
    assessed_version: int | None
    not_understood: SkipValidation[list[str]]
    picked: bool
    hops: int
    confirm_payload: SkipValidation[JsonObject | None]
    resume: SkipValidation[JsonObject | None]
    research_results: SkipValidation[list[JobResult | str]]  # [RESET]: the reducer starts over
    notices: SkipValidation[list[Notice]]
    reply_text: str
    blocks: SkipValidation[list[JsonObject]]
    fingerprint: str | None
    done: bool
    route: str | None
    case_changed: bool
    persona_changed: bool


class InterpretIn(NodeIn):
    """The person's words or a button's preset, and the turn's language for a question asked back."""

    preset: SkipValidation[Preset | None] = None
    user_text: str | None = None
    language: str | None = None


class InterpretOut(NodeOut):
    """The interpretation (its `request` is settled by apply_delta), or a question asked back (`done`)."""

    interpretation: SkipValidation[JsonObject] = {}
    language: str | None = None
    picked: bool = False
    action: Asked = "ASK"
    done: bool = False
    reply_text: str = ""

    @classmethod
    def from_reading(cls, reading: Reading, reply_text: str) -> InterpretOut:
        """The update of `reading`; `reply_text` is its question in the person's language (unused otherwise)."""
        if reading.ask is not None:
            if reading.ask == "which_car":  # a car edit knows the chat's language; a failed reading keeps the turn's
                return cls(action="ASK", done=True, reply_text=reply_text, language=reading.language)
            return cls(action="ASK", done=True, reply_text=reply_text)
        assert reading.interpretation is not None  # a reading without a question always has its interpretation
        i = reading.interpretation
        if reading.picked:
            return cls(interpretation=i.model_dump(mode="json"), language=i.language, picked=True)
        return cls(interpretation=i.model_dump(mode="json"), language=i.language)


class ApplyDeltaIn(NodeIn):
    """The interpretation to apply, the words (or a button), and whether the words picked an offered option."""

    interpretation: SkipValidation[JsonObject | None] = None
    preset: SkipValidation[Preset | None] = None
    user_text: str | None = None
    picked: bool | None = None


class ApplyDeltaOut(NodeOut):
    """The request as code settled it (the one owner of `request_kind`), and the case change — or a question."""

    request_kind: RequestKind
    not_understood: SkipValidation[list[str]] = []
    case_changed: bool = False
    persona_changed: bool = False
    action: Asked = "ASK"
    done: bool = False
    reply_text: str = ""

    @classmethod
    def from_applied(cls, applied: Applied) -> ApplyDeltaOut:
        """The update of `applied` (the node saved its case when `applied.saved`)."""
        if not applied.saved:
            return cls(not_understood=applied.not_understood, request_kind=applied.request, case_changed=False)
        persona = any(ch.startswith("persona:") for ch in applied.changes)  # the report is recomputed for it
        return cls(not_understood=applied.not_understood, request_kind=applied.request,
                   case_changed=bool(applied.changes), persona_changed=persona)  # fmt: skip


class AssessIn(NodeIn):
    """The turn's notices so far, what decides a "find it" plan (the request, its focus, research done) and the
    turn's earlier feasibility checks."""

    notices: SkipValidation[list[Notice]] = []
    interpretation: SkipValidation[JsonObject | None] = None
    request_kind: RequestKind | None = None
    research_done: bool | None = None
    feasibility: SkipValidation[JsonObject | None] = None


class AssessOut(NodeOut):
    """The assessed cars, the case version they were assessed on, the research plan and its cost, whether a
    feasibility finding waits for the person; the checks and notices only when there is something new (an earlier
    assess of the same turn may have set them)."""

    assessments: SkipValidation[dict[str, JsonObject]]
    assessed_version: int
    research_plan: SkipValidation[PlanState]
    cost_estimate: SkipValidation[float]  # as the estimator gave it (no int → float coercion in the checkpoint)
    research_declined: bool
    feasibility_pending: bool
    feasibility: SkipValidation[JsonObject] = {}
    notices: SkipValidation[list[Notice]] = []

    @classmethod
    def from_planned(cls, planned: Planned, notices: list[Notice], *, assessed_version: int) -> AssessOut:
        """The update of `planned`, assessed on case version `assessed_version`; `notices` are the turn's notices
        so far (the new warnings are appended)."""
        rows: list[PlanRow] = [[j.car_key, j.variant_id, j.area, j.fresh, j.escalate] for j in planned.plan.jobs]
        written: JsonObject = {
            "assessments": {k: a.model_dump(mode="json") for k, a in planned.assessments.items()},
            "assessed_version": assessed_version,
            "research_plan": {"jobs": rows, "rounds": planned.plan.rounds, "key": planned.plan_key},
            "cost_estimate": planned.cost_eur,
            "research_declined": planned.declined,
            "feasibility_pending": planned.feasibility_pending,
        }
        if planned.feasibility is not None:
            written["feasibility"] = planned.feasibility
        if planned.warnings:
            written["notices"] = [*notices, *planned.warnings]
        return cls.model_validate(written)
