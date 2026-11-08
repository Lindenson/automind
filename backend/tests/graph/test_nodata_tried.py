"""Spec 011 T121/T123 (closes 010 T067): "no data" names the sources that were tried. `acquire()` lists the domains a
job read with their outcomes, plus the plan's sources it never reached; the report's data panel names the domains
read for an area that gave no accepted value."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from automind.acquisition import api as acquisition
from automind.acquisition.registry.api import Plan, PlannedSource
from automind.acquisition.registry.application.service import RegistryService
from automind.chat.application.services.report.blocks.data_panel import data_panel_block
from automind.chat.application.services.report.facts.car import load_car
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker

from .test_unverified_label import ports_for, registry_rows  # noqa: F401 (fixture)


async def _setup() -> str:
    async with sessionmaker()() as s:
        for t in (m.RegistryAttempt, m.RegistryChange, m.TruthSignal, m.CapabilityRow, m.SourceRow):
            await s.execute(delete(t))
        s.add(m.SourceRow(domain="nothing.example", source_type="PUBLICATION", family="nothing.example",
                          markets=["ES"], access="ok"))  # fmt: skip
        await s.flush()
        s.add(m.CapabilityRow(domain="nothing.example", area="used_price", market="ES", status="candidate"))
        v = m.Variant(canonical_key=f"candmake|roadster|r1|{uuid.uuid4().hex}", make="CandMake", model="Roadster",
                      generation="R1", variant_name="2.0 T 190", powertrain="ICE", generation_years_from=2019,
                      generation_years_to=2024)  # fmt: skip
        s.add(v)
        await s.commit()
        return v.id


class _PlanWithUnreached(RegistryService):
    """The registry's plan names one more active source that the job's searches never reach."""

    async def plan(self, area: str, markets: list[str], make: str | None, seed: int | None = None) -> Plan:
        p = await super().plan(area, markets, make, seed)
        return p.model_copy(update={"sources": [
            *p.sources, PlannedSource(domain="unreached.example", market="ES", priority=0, status="active")
        ]})  # fmt: skip


@pytest.mark.usefixtures("registry_rows")
async def test_no_data_lists_the_tried_sources():
    vid = await _setup()
    ports, search = ports_for("unverified")
    ports.llm.responders["extractor"] = lambda s, u: {"is_about_variant": True, "ranges": []}
    ports.registry = _PlanWithUnreached(
        ports.registry.capabilities, ports.registry.signals, ports.registry.pages, ports.registry.cfg
    )
    req = acquisition.AcquireRequest(job_id=str(uuid.uuid4()), variant_id=vid, kinds=["used_price"], car_year=2020)
    res = await acquisition.acquire(req, None, ports=ports)
    (k,) = res.kinds
    assert k.ok, k.error
    assert k.accepted == 0 and not k.minimum_met
    assert "CandMake Roadster 2020 site:nothing.example" in search.queries, search.queries
    assert {t.domain: t.outcome for t in k.tried} == {"nothing.example": "empty", "unreached.example": "not_reached"}

    # the report: the area's row in the data panel names what was read and how it went
    car = await load_car(vid)
    panel = data_panel_block([("car#1", "Roadster", car)], {"car#1": {"used_price"}}, datetime.now(UTC))
    assert panel is not None
    (row,) = panel["cars"][0]["areas"]
    assert row["status"] in ("MISSING", "UNAVAILABLE", "PARTIAL")
    assert row["tried"] == [{"domain": "nothing.example", "outcome": "empty", "reason": None}]
