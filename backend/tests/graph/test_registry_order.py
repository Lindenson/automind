"""Spec 010 US6 (T061): sources are ordered by measured quality per kind of data; a "wrong?" lowers the source
unless our own reading was wrong."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from automind.acquisition.registry.api import Attempt, TruthSignalIn
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.wiring import registry_service
from automind.chat.application.usecases import challenge
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker

from .conftest import open_web_reference
from .test_challenge import _claims
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)


async def _clear() -> None:
    async with sessionmaker()() as s:
        for t in (m.RegistryAttempt, m.RegistryChange, m.TruthSignal, m.CapabilityRow, m.SourceRow):
            await s.execute(delete(t))
        await s.commit()


def _svc(autonomy: bool = True) -> RegistryService:
    cfg = {**load_yaml("registry.yaml"), "autonomy": autonomy}
    return registry_service(cfg)


async def test_confirmed_source_ranks_before_corrected_one_per_area():
    await _clear()
    svc = _svc()
    for dom in ("good.example", "bad.example"):
        await svc.record(
            [
                Attempt(domain=dom, area="specs", market="ES", url=f"https://{dom}/{i}", outcome="accepted", values=2)
                for i in range(10)
            ]
        )
        await svc.record(
            [Attempt(domain=dom, area="used_price", market="ES", url=f"https://{dom}/p", outcome="accepted")]
        )
    for _ in range(4):
        await svc.signal(TruthSignalIn(kind="challenge", verdict="right", domain="good.example", area="specs"))
        await svc.signal(TruthSignalIn(kind="challenge", verdict="wrong", domain="bad.example", area="specs"))
    async with sessionmaker()() as s:  # discovered sites are made active here only to look at the order
        for c in (await s.execute(select(m.CapabilityRow))).scalars():
            c.status = "active"
        await s.commit()
    plan = await svc.plan("specs", ["ES"], None)
    assert [p.domain for p in plan.sources] == ["good.example", "bad.example"]
    async with sessionmaker()() as s:
        bad = (
            await s.execute(
                select(m.CapabilityRow).where(m.CapabilityRow.domain == "bad.example", m.CapabilityRow.area == "specs")
            )
        ).scalar_one()
        bad_price = (
            await s.execute(
                select(m.CapabilityRow).where(
                    m.CapabilityRow.domain == "bad.example", m.CapabilityRow.area == "used_price"
                )
            )
        ).scalar_one()
    assert bad.wrong_w == pytest.approx(4.0, rel=1e-3) and bad.acc_mean < 0.5
    assert bad_price.wrong_w == 0  # the price capability is scored on its own


@pytest.mark.usefixtures("fresh_variant")
async def test_challenge_blames_extractor_when_the_excerpt_is_not_on_the_page():
    await _clear()
    svc = _svc()
    vid = await _claims(("1580", "Maletero 1580 litros", "Maletero 580 litros"))
    r = await challenge.recheck(open_web_reference(), "chat-x", vid, "boot_volume", "wrong", registry=svc)
    assert r["outcome"] == "REMOVED"
    async with sessionmaker()() as s:
        sig = (await s.execute(select(m.TruthSignal))).scalars().all()
    assert [(x.verdict, x.blame) for x in sig] == [("wrong", "extractor")]  # the source is not punished
    assert sig[0].capability_id is None
