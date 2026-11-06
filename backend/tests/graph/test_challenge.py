"""spec 004 FR-022: "this is wrong" re-checks a value against its sources."""

import pytest
from sqlalchemy import select

from automind.acquisition.pipeline import merge
from automind.chat.application.usecases import challenge
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker

from .conftest import open_web_reference
from .test_research_flow import MAKE
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")


async def _claims(*rows: tuple[str, str, str]) -> str:
    """(raw value, excerpt, document text) per source."""
    async with sessionmaker()() as s:
        v = (await s.execute(select(m.Variant).where(m.Variant.make == MAKE))).scalar_one()
        for i, (raw, excerpt, text) in enumerate(rows):
            d = m.Document(url=f"https://src{i}.es/racer", title="Racer", text=text, content_sha256=f"c{i}{raw}")
            s.add(d)
            await s.flush()
            e = m.Evidence(variant_id=v.id, document_id=d.id, url=d.url, source_name="x", domain=f"src{i}.es",
                           source_type="PUBLICATION")  # fmt: skip
            s.add(e)
            await s.flush()
            s.add(m.Claim(variant_id=v.id, evidence_id=e.id, attribute="boot_volume", raw_value=raw,
                          raw_unit="L", value_num=float(raw), excerpt=excerpt, provenance="SOURCED_FACT",
                          status="ACCEPTED"))  # fmt: skip
        await s.commit()
        await merge.reselect(v.id)
        return v.id


async def test_value_backed_by_two_sources_is_confirmed():
    vid = await _claims(("580", "Maletero 580 litros", "Maletero 580 litros"),
                        ("580", "Boot 580 litres", "The boot holds: Boot 580 litres"))  # fmt: skip
    r = await challenge.recheck(open_web_reference(), "chat-x", vid, "boot_volume", "this is wrong")
    assert r["outcome"] == "CONFIRMED" and r["after"] == "580.0"


async def test_value_whose_excerpt_is_not_in_the_page_is_removed():
    vid = await _claims(("1580", "Maletero 1580 litros", "Maletero 580 litros"))
    r = await challenge.recheck(open_web_reference(), "chat-x", vid, "boot_volume")
    assert r["outcome"] == "REMOVED" and r["after"] is None and r["rejected"]
