"""009 FR-024 (chat 20b5b7f9): the seats and the boot volume of one car differed between two reports of one chat.
The second report re-read the same pages: the same values came back as new claims with new ids, and the claim ids
decided the tie. The values are recomputed from the database (merge.reselect) as each report does."""

import pytest
from sqlalchemy import select

from automind.acquisition.pipeline import merge
from automind.infrastructure.db import models as m
from automind.infrastructure.db.session import sessionmaker

from .test_research_flow import MAKE
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("fresh_variant")

SITES = {"km77.com": ("seats", 5.0, "5 plazas"), "auto-data.net": ("seats", 7.0, "7 seats"),
         "autopista.es": ("boot_volume", 616.0, "maletero 616 litros"),
         "motor.es": ("boot_volume", 604.0, "maletero 604 litros")}  # fmt: skip


async def _read_pages(vid: str, ids: dict[str, str]) -> None:
    """One research run: each site's page read again gives its value as a new claim (with the id given)."""
    async with sessionmaker()() as s:
        for n, (dom, (attr, value, words)) in enumerate(SITES.items()):
            d = m.Document(url=f"https://{dom}/racer", title="Racer", text=words, content_sha256=f"{ids[dom]}{n}")
            s.add(d)
            await s.flush()
            e = m.Evidence(variant_id=vid, document_id=d.id, url=d.url, source_name=dom, domain=dom,
                           source_type="PUBLICATION")  # fmt: skip
            s.add(e)
            await s.flush()
            s.add(m.Claim(id=ids[dom], variant_id=vid, evidence_id=e.id, attribute=attr, raw_value=words,
                          value_num=value, excerpt=words, provenance="SOURCED_FACT", status="ACCEPTED"))  # fmt: skip
        await s.commit()


async def _values(vid: str) -> dict[str, float | None]:
    async with sessionmaker()() as s:
        rows = (await s.execute(select(m.SpecValue).where(m.SpecValue.variant_id == vid))).scalars()
        return {r.attribute: r.value_num for r in rows if r.attribute in ("seats", "boot_volume")}


def _id(prefix: str, n: int) -> str:
    return f"{prefix}{n:07d}-0000-4000-8000-000000000000"


async def test_seats_and_boot_are_the_same_in_the_second_report():
    async with sessionmaker()() as s:
        vid = (await s.execute(select(m.Variant.id).where(m.Variant.make == MAKE))).scalar_one()
    # first report: the 5-seat and the 604-litre claims happen to have the smaller ids
    await _read_pages(vid, {"km77.com": _id("1", 1), "auto-data.net": _id("2", 1), "autopista.es": _id("2", 2),
                            "motor.es": _id("1", 2)})  # fmt: skip
    await merge.reselect(vid)
    first = await _values(vid)
    # second report of the same chat, the same car: the same pages again, new ids in the other order
    await _read_pages(vid, {"km77.com": _id("3", 1), "auto-data.net": _id("0", 1), "autopista.es": _id("0", 2),
                            "motor.es": _id("3", 2)})  # fmt: skip
    await merge.reselect(vid)
    second = await _values(vid)
    assert first == second, (first, second)
    assert first == {"seats": 5.0, "boot_volume": 604.0}
