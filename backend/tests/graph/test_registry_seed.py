"""Spec 010 US8 (T054): the registry is seeded once with evidence; with autonomy off it only skips blocked sites
and records attempts; unknown sites met in searches become discovered."""

from __future__ import annotations

from sqlalchemy import delete, select

from automind.acquisition.registry.api import Attempt
from automind.acquisition.registry.application.seed import seed, seed_if_empty
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.infrastructure.db import models as m
from automind.infrastructure.db.session import sessionmaker


async def _clear() -> None:
    async with sessionmaker()() as s:
        for t in (m.RegistryAttempt, m.RegistryChange, m.TruthSignal, m.CapabilityRow, m.SourceRow):
            await s.execute(delete(t))
        await s.commit()


async def test_seed_is_idempotent_and_keeps_evidence():
    await _clear()
    first = await seed_if_empty()
    assert first is not None and first["favourites"] > 50 and first["survey"] > 100
    assert await seed_if_empty() is None
    again = await seed()
    assert again == {"favourites": 0, "survey": 0, "learned": 0}
    async with sessionmaker()() as s:
        forbid = (await s.execute(select(m.SourceRow).where(m.SourceRow.access == "terms_forbid"))).scalars().all()
        alv = await s.get(m.SourceRow, "alvolante.it")
        km = (
            await s.execute(
                select(m.CapabilityRow).where(m.CapabilityRow.domain == "km77.com", m.CapabilityRow.area == "specs")
            )
        ).scalar_one()
        changes = (await s.execute(select(m.RegistryChange).where(m.RegistryChange.domain == "alvolante.it"))).scalars()
    assert forbid and all(f.access_evidence.get("clause") for f in forbid)  # the deciding clause is quoted
    assert alv is not None and alv.access in ("terms_forbid", "classifieds")  # blocked either way
    assert km.status == "active" and km.priority_seed == 1
    assert all(c.reason.startswith("seed") for c in changes)


async def test_autonomy_off_plans_only_the_skip_list_and_records_attempts():
    await _clear()
    await seed()
    svc = RegistryService(RegistryRepo(), {"autonomy": False})
    plan = await svc.plan("used_price", ["ES", "EN", "IT"], "Toyota")
    assert plan.autonomy is False and plan.sources == [] and "alvolante.it" in plan.skip
    await svc.record(
        [
            Attempt(
                domain="km77.com", area="specs", market="ES", url="https://km77.com/a", outcome="accepted", values=3
            ),
            Attempt(
                domain="new-site.example",
                area="specs",
                market="ES",
                url="https://new-site.example/x",
                outcome="rejected",
                reason="other_variant",
            ),
        ]
    )
    async with sessionmaker()() as s:
        km = (
            await s.execute(
                select(m.CapabilityRow).where(
                    m.CapabilityRow.domain == "km77.com",
                    m.CapabilityRow.area == "specs",
                    m.CapabilityRow.market == "ES",
                )
            )
        ).scalar_one()
        new = (
            await s.execute(select(m.CapabilityRow).where(m.CapabilityRow.domain == "new-site.example"))
        ).scalar_one()
        n_att = len((await s.execute(select(m.RegistryAttempt))).all())
    assert km.attempts == 1 and km.accepted == 1 and km.recent == [True]
    assert new.status == "discovered" and new.rejected == {"other_variant": 1.0}
    assert n_att == 2
