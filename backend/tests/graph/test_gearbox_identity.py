"""spec 004 FR-028: a variant with accepted values of two gearboxes is asked about and split; unanimous claims
give a variant its gearbox."""

import pytest
from sqlalchemy import select

from automind.acquisition.pipeline import merge
from automind.chat.application.services.identification import resolve
from automind.chat.domain.case import CaseCar, Constraints
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker

from .conftest import open_web_reference
from .test_research_flow import MAKE
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")


async def _variant_with(*gearboxes: str) -> str:
    async with sessionmaker()() as s:
        v = (await s.execute(select(m.Variant).where(m.Variant.make == MAKE))).scalar_one()
        for i, g in enumerate(gearboxes):
            d = m.Document(url=f"https://x{i}.es/racer", title="Racer", text=f"Cambio {g}", content_sha256=f"g{i}")
            s.add(d)
            await s.flush()
            e = m.Evidence(variant_id=v.id, document_id=d.id, url=d.url, source_name="x", domain=f"x{i}.es",
                           source_type="PUBLICATION")  # fmt: skip
            s.add(e)
            await s.flush()
            s.add(m.Claim(variant_id=v.id, evidence_id=e.id, attribute="transmission", raw_value=g, value_text=g,
                          excerpt=f"Cambio {g}", provenance="SOURCED_FACT", status="ACCEPTED"))  # fmt: skip
        await s.commit()
        return v.id


async def test_mixed_gearboxes_are_asked_and_split():
    vid = await _variant_with("manual 6-speed", "automatic 6-speed")
    assert await resolve.gearbox_mixed(vid)
    car = CaseCar(key="car#1", request_text="Racer", make=MAKE, model="Racer", variant_id=vid, resolution="AUTO_OK",
                  constraints=Constraints(gearbox_hint="automatic"))  # fmt: skip
    note = await resolve.split_by_gearbox(car, open_web_reference())
    assert note and car.variant_id != vid and car.resolution == "CONFIRMED"
    new = await resolve.get_variant(car.variant_id or "")
    assert new is not None and new.transmission == "automatic" and "automatic" in new.variant_name


async def test_unanimous_claims_fill_the_gearbox():
    vid = await _variant_with("automatic 6-speed", "Skyactiv-Drive automatic")
    await merge.reselect(vid)
    v = await resolve.get_variant(vid)
    assert v is not None and v.transmission == "automatic"
    assert not await resolve.gearbox_mixed(vid)
