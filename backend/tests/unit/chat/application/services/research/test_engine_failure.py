"""A job's engine failure is that job's result, never the round's (review 2026-11-27: one failing engine call failed
the whole fan-out). The job store's own failure still propagates (the module's failure contract)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from automind.chat.application.ports import StoreUnavailable
from automind.chat.application.services.research.service import ResearchService
from automind.chat.domain.case import CaseCar, CaseFile
from automind.chat.domain.turn import JobStatus
from automind.shared.infrastructure.llm.gateway import new_budget

CASE = CaseFile(cars=[CaseCar(key="car#1", request_text="Golf", make="Volkswagen", model="Golf", variant_id="v1")])
JOB: Any = {"job_id": "j1", "car_key": "car#1", "variant_id": "v1", "area": "specs", "round": 0, "fresh": False,
            "escalate": False}  # fmt: skip


@dataclass
class Jobs:
    down: bool = False
    marks: list[tuple[str, JobStatus, str | None]] = field(default_factory=list)

    async def get(self, job_id: str) -> None:
        return None

    async def mark(self, job_id: str, status: JobStatus, **kw: Any) -> None:
        if self.down and status is JobStatus.FAILED:
            raise StoreUnavailable("research_jobs: OperationalError")
        self.marks.append((job_id, status, kw.get("error")))


class Engine:
    async def acquire(self, req: Any, emit: Any) -> Any:
        raise RuntimeError("engine store down")


class Events:
    async def progress(self, cell: Any) -> None: ...

    async def status(self, *a: Any, **kw: Any) -> None: ...


def _service(jobs: Jobs) -> ResearchService:
    ports = SimpleNamespace(jobs=jobs, acquisition=Engine())
    return ResearchService(ports, new_budget("c", "t"), Events(), "c", "t")  # type: ignore[arg-type]


async def test_an_engine_failure_is_the_jobs_failed_result() -> None:
    jobs = Jobs()
    result = await _service(jobs).run_job(JOB, CASE)
    assert result["ok"] is False and result["error"] == "RuntimeError: engine store down"
    assert jobs.marks[-1] == ("j1", JobStatus.FAILED, "RuntimeError: engine store down")


async def test_the_job_store_failing_still_fails_the_turn() -> None:
    with pytest.raises(StoreUnavailable):
        await _service(Jobs(down=True)).run_job(JOB, CASE)
