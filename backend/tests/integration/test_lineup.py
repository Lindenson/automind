"""Spec 005 R2 (FR-007, FR-011): brand line-ups are kept only as far as their documents support them; cached."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.graph.conftest import make_ports

from automind.acquisition.api import LineupEntry as _Entry
from automind.application import lineup
from automind.infrastructure import db

DOCS = {"https://www.byd.com/es": ("BYD España", "BYD Seal U DM-i — SUV familiar. Desde 35.990 €. BYD Atto 3.")}


def test_model_not_in_its_document_is_dropped_and_price_needs_its_excerpt() -> None:
    lu = lineup.validate("BYD", [
        _Entry(model="Seal U DM-i", body="SUV", powertrains=["phev"], price_from_eur=35990,
               excerpt="BYD Seal U DM-i — SUV familiar. Desde 35.990 €", source_url="https://www.byd.com/es"),
        _Entry(model="Atto 3", price_from_eur=37990, excerpt="BYD Atto 3", source_url="https://www.byd.com/es"),
        _Entry(model="Han", excerpt="BYD Han", source_url="https://www.byd.com/es"),  # not in the document
    ], DOCS, "byd.com/es")  # fmt: skip
    assert [m.model for m in lu.models] == ["Seal U DM-i", "Atto 3"]
    assert lu.models[0].price_from_eur == 35990 and lu.models[1].price_from_eur is None  # 37.990 is not in its excerpt
    assert lu.sources[0]["type"] == "MANUFACTURER"


def test_no_official_or_priced_source_is_not_kept() -> None:
    docs = {"https://blog.example/byd": ("A blog", "BYD Seal U is nice.")}
    lu = lineup.validate("BYD", [_Entry(model="Seal U", source_url="https://blog.example/byd")], docs, "byd.com/es")
    assert lu.models == []


async def test_lookup_reads_official_site_and_caches() -> None:
    await db.init_db()
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.BrandLineup).where(db.BrandLineup.make == "BYD"))
        await s.commit()
    llm = FakeLLM().queue("lineup", {"models": [
        {"model": "Seal U DM-i", "body": "suv", "powertrains": ["phev"], "price_from_eur": 35990,
         "excerpt": "BYD Seal U DM-i — SUV familiar híbrido enchufable. Desde 35.990 €", "source_url": "https://www.byd.com/es"},
        {"model": "Atto 3", "body": "suv", "powertrains": ["bev"], "price_from_eur": 37990,
         "excerpt": "BYD Atto 3 — SUV compacto eléctrico. Desde 37.990 €", "source_url": "https://www.byd.com/es"},
    ]})  # fmt: skip
    ports = make_ports(llm=llm, search=FixtureSearch("byd"))
    lu = await lineup.get_lineup(ports, "BYD")
    assert lu is not None and {m.model for m in lu.models} == {"Seal U DM-i", "Atto 3"}
    again = await lineup.get_lineup(ports, "BYD")  # cached: no second model call (the queue is empty)
    assert again is not None and len(again.models) == 2
    async with db.sessionmaker()() as s:  # older than the TTL: looked up again
        row = (await s.execute(lineup._row_of("BYD"))).scalar_one()
        row.fetched_at = datetime.now(UTC) - timedelta(days=40)
        await s.commit()
    assert await lineup.cached("BYD", 30) is None
