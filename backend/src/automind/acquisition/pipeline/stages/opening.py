"""The job's scope: the gated rule, prompt and model overrides refreshed (spec 011 T104, cached 60 s), the job named
for metering, the registry's plan and an empty set of registry candidates in the context the other stages read
(`pipeline/scope.py`); all reset when the job ends, however it ends.

Errors: a registry failure while planning propagates (the job does not start; the caller's job runner decides)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from automind.acquisition.infrastructure import overrides
from automind.acquisition.pipeline.contracts import JobSpec
from automind.acquisition.pipeline.plan import registry_plan
from automind.acquisition.pipeline.scope import current_candidates, current_plan
from automind.acquisition.ports import AcqPorts
from automind.acquisition.registry.api import Plan
from automind.acquisition.registry.domain.model import CapabilityStatus
from automind.shared.metering.usage import current_job


@asynccontextmanager
async def opened(ports: AcqPorts, job: JobSpec) -> AsyncIterator[Plan | None]:
    """The job's scope for its duration; yields the registry's plan (None without the registry)."""
    await overrides.refresh()
    job_token = current_job.set((job.job_id, job.area))
    try:
        the_plan = await registry_plan(ports, job)
        plan_token = current_plan.set(the_plan)
        candidates_token = current_candidates.set(set())
        try:
            yield the_plan
        finally:
            current_candidates.reset(candidates_token)
            current_plan.reset(plan_token)
    finally:
        current_job.reset(job_token)


def active_sources(the_plan: Plan | None) -> list[str]:
    """The domains of the plan's active sources, in its order (what the job should have reached)."""
    if the_plan is None:
        return []
    return list(dict.fromkeys(x.domain for x in the_plan.sources if x.status == CapabilityStatus.ACTIVE))
