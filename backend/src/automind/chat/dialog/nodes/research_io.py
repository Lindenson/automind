"""The contracts of the research nodes (spec 014 T102): plan_research, research_job (a `Send` payload, not the
state), collect_round, next_round, after_research and the limit confirmation, over today's flat keys."""

from __future__ import annotations

from pydantic import SkipValidation

from automind.chat.application.services.report.blocks.notice import Notice
from automind.chat.application.services.research.contracts import JobResult, JobState, LimitHit, PlanState
from automind.chat.dialog.contract import NodeIn, NodeOut
from automind.chat.dialog.state import DecisionState
from automind.chat.domain.decision import RequestKind
from automind.shared.contracts.json import JsonObject

Results = list[JobResult | str]  # what a node writes to the `research_results` reducer: results, or [RESET] first


class PlanResearchIn(NodeIn):
    """The cars to research (the policy's decision) and the plan the assessment made."""

    decision: SkipValidation[DecisionState]
    research_plan: SkipValidation[PlanState | None] = None


class PlanResearchOut(NodeOut):
    """The first round's jobs; the round counter and the round's results start over."""

    jobs: SkipValidation[list[JobState]]
    round: int
    research_results: SkipValidation[Results]


class ResearchJobIn(NodeIn):
    """One job as `plan_research`/`collect_round` sent it (`research_jobs` row and its place in the plan)."""

    job_id: str
    car_key: str
    variant_id: str
    area: str
    round: int
    fresh: bool
    escalate: bool

    def job(self) -> JobState:
        """The job as the research service takes it."""
        return JobState(job_id=self.job_id, car_key=self.car_key, variant_id=self.variant_id, area=self.area,
                        round=self.round, fresh=self.fresh, escalate=self.escalate)  # fmt: skip


class ResearchJobOut(NodeOut):
    """The job's result, appended by the reducer."""

    research_results: SkipValidation[Results]


class CollectRoundIn(NodeIn):
    """The round's results and jobs, the plan (its minimums) and the round counter."""

    research_results: SkipValidation[list[JobResult]] = []
    jobs: SkipValidation[list[JobState]] = []
    research_plan: SkipValidation[PlanState | None] = None
    round: int = 0


class CollectRoundOut(NodeOut):
    """The next round's jobs (none: done), the limit hit when a limit stopped the round, the round counted."""

    jobs: SkipValidation[list[JobState]]
    limit_hit: SkipValidation[LimitHit] = LimitHit(reasons=[], jobs=[])
    round: int = 0


class LimitIn(NodeIn):
    """The limit the research stopped at and the turn's language."""

    limit_hit: SkipValidation[LimitHit | None] = None
    language: str | None = None


class ApplyLimitIn(NodeIn):
    """The answer, the limit it answers and how many times the person already said "continue" in this turn."""

    resume: SkipValidation[JsonObject | None] = None
    limit_hit: SkipValidation[LimitHit | None] = None
    limit_extensions: int | None = None


class ApplyLimitOut(NodeOut):
    """The jobs to run again (none: answer now), the limit and the question cleared, `route` interpret for typed
    words read as a new message (else None), the extension counted."""

    jobs: SkipValidation[list[JobState]]
    limit_hit: SkipValidation[LimitHit | None]
    confirm_payload: SkipValidation[JsonObject | None]
    resume: SkipValidation[JsonObject | None]
    route: str | None
    user_text: str = ""
    limit_extensions: int = 0


class NothingIn(NodeIn):
    """A node that reads nothing."""


class NothingOut(NodeOut):
    """A node that writes nothing."""


class AfterResearchIn(NodeIn):
    """The research's results, the turn's notices and language, and the request ("find it" remembers a miss)."""

    research_results: SkipValidation[list[JobResult]] = []
    notices: SkipValidation[list[Notice]] = []
    language: str | None = None
    request_kind: RequestKind | None = None


class AfterResearchOut(NodeOut):
    """Research done, the notices with its warnings, no jobs left."""

    research_done: bool
    notices: SkipValidation[list[Notice]]
    jobs: SkipValidation[list[JobState]]
