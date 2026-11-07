"""Contracts of the research service: the shapes it reads from and writes to the turn state (the plan, a job, a job's
result, a limit reached), the grid cell it shows while it works, and its two ports — the turn's event stream and the
words it needs in the person's language.

The shapes are `TypedDict`s because they live in the graph state, which holds plain data only (code-shape.md
"Dialog state"); the dialog's `TurnState` refers to them."""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict

CellState = Literal["queued", "searching", "reading", "paused", "failed", "partial", "done"]
PlanRow = list[str | bool]  # [car key, variant id, area, fresh, escalate] (JSON in the checkpoint: a list)


class PlanState(TypedDict, total=False):
    """The research plan as the assessment writes it into the turn state."""

    jobs: list[PlanRow]
    rounds: int  # gap rounds allowed after the first
    key: str  # identity of the plan: a refusal of this plan is remembered by it


class StoppedJob(TypedDict):
    """A job a limit stopped: everything needed to create it again when the person goes on."""

    car_key: str
    variant_id: str
    area: str
    round: int
    fresh: bool  # "find it": past the search cache, wider queries
    escalate: bool  # the registry's sources of the other markets too


class JobState(StoppedJob):
    """A job as the graph sends it to a worker: a `research_jobs` row and its place in the plan."""

    job_id: str


class JobOutcome(TypedDict, total=False):
    """How a job ended. `limit` is set when a limit stopped it (`calls`, `cost`, `time`, …)."""

    ok: bool
    reused: bool  # already DONE before a restart: not run again
    minimum_met: bool | None  # None: not known (reused, superseded, stopped)
    error: str | None
    limit: str
    accepted: int
    rejected: int


class JobResult(JobState, JobOutcome):
    """What a job left for the round: the job and its outcome, flat (the graph state's `research_results`)."""


class LimitHit(TypedDict):
    """A round stopped at a limit: why, and the jobs to run if the person goes on."""

    reasons: list[str]
    jobs: list[StoppedJob]


class GridCell(TypedDict):
    """One cell of the car × area grid the chat shows (spec 004 FR-023)."""

    car: str  # the car's label as the person sees it
    car_key: str
    area: str
    state: CellState
    accepted: int | None  # documents accepted so far, once known
    round: int


class ResearchEvents(Protocol):
    """The turn's event stream (implemented by the dialog's TurnContext). Publishing never fails the research: a
    lost event only leaves the grid behind."""

    async def progress(self, cell: GridCell) -> None:
        """Show a grid cell in its new state."""
        ...

    async def status(self, stage: str, text: str, *, car: str, area: str) -> None:
        """Show a status line of a job's stage (`stage` is the engine's stage name)."""
        ...


class ResearchWording(Protocol):
    """The words of the research in the person's language (implemented by the dialog's wording)."""

    def t(self, key: str, lang: str | None, **params: object) -> str:
        """The phrase `key` with its parameters filled in."""
        ...

    def area_label(self, area: str, lang: str | None) -> str:
        """The name of a research area as the person reads it."""
        ...
