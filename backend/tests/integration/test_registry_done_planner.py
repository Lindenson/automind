"""A run planned by an older planner does not count as having tried the registry (chat 2026-11-06).

Deepal S09 / Li L9: an area left below its minimum by a run before the home-market research (plan@1, European
queries only) blocked the Chinese search for the retry window. `registry_done` drops such runs, so the planner
retries the unmet area at once, escalated; a run by the current planner still counts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from automind.acquisition import api as acquisition
from automind.acquisition.pipeline import job, plan
from automind.shared.infrastructure import db
from automind.shared.infrastructure.db import models as m
from automind.shared.research_order import plan as research_plan


@pytest.fixture
async def car():
    await db.init_db()
    async with db.sessionmaker()() as s:
        v = m.Variant(canonical_key=f"deepal|s09||erev|phev|rd-{db.uid()}", make="Deepal", model="S09",
                      variant_name="1.5T EREV 210km RWD", powertrain="PHEV", body_class="SUV")  # fmt: skip
        s.add(v)
        await s.commit()
        vid = v.id
    yield vid
    async with db.sessionmaker()() as s:
        await s.execute(delete(m.ResearchRun).where(m.ResearchRun.variant_id == vid))
        await s.execute(delete(m.Variant).where(m.Variant.id == vid))
        await s.commit()


async def _run(vid: str, area: str, planner: str, at: datetime) -> None:
    async with db.sessionmaker()() as s:
        s.add(m.ResearchRun(variant_id=vid, area=area, completed_at=at, registry_at=at, docs_used=1,
                            claims_accepted=0, minimum_met=False,
                            stage_versions={**job.STAGE_VERSIONS, "plan": planner}))  # fmt: skip
        await s.commit()


async def test_unmet_area_of_an_older_planner_is_retried_at_once(car):
    now = datetime.now(UTC)
    await _run(car, "measured", "plan@1", now - timedelta(minutes=30))
    await _run(car, "reliability", plan.VERSION, now - timedelta(minutes=30))
    done = await acquisition.registry_done([car])
    assert "measured" not in done.get(car, {})
    assert "reliability" in done[car]
    unmet = await acquisition.unmet_areas([car])
    rp = research_plan.plan(
        [research_plan.CarToPlan(key="a", variant_id=car, condition="NEW", electrified=True)],
        persona="UNKNOWN", criteria=[], depth="STANDARD", now=now, unmet=unmet, registry_done=done,
        last_done={car: {"measured": now - timedelta(minutes=30), "reliability": now - timedelta(minutes=30)}},
    )  # fmt: skip
    jobs = {j.area: j for j in rp.jobs}
    assert "measured" in jobs and jobs["measured"].escalate
    assert "reliability" not in jobs  # the current planner tried it half an hour ago: the retry window holds
