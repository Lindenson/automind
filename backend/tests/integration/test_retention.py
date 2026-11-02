"""Retention (spec 003 T054): expired cache rows and unreferenced expired pages go; referenced pages stay."""

from datetime import timedelta

from sqlalchemy import select

from automind.infrastructure import db
from automind.infrastructure.db.models import now
from automind.infrastructure.retention import run_retention


async def test_retention_removes_only_expired_unreferenced():
    await db.init_db()
    past, future = now() - timedelta(days=1), now() + timedelta(days=1)
    async with db.sessionmaker()() as s:
        v = db.Variant(
            canonical_key=f"retmake|{db.uid()}", make="RetMake", model="R", variant_name="x", powertrain="ICE"
        )
        s.add(v)
        old_free = db.Document(url="https://ret.example/a", url_hash=db.uid(), text="a", expires_at=past)
        old_used = db.Document(url="https://ret.example/b", url_hash=db.uid(), text="b", expires_at=past)
        fresh = db.Document(url="https://ret.example/c", url_hash=db.uid(), text="c", expires_at=future)
        s.add_all([old_free, old_used, fresh])
        await s.flush()
        s.add(db.Evidence(variant_id=v.id, document_id=old_used.id, url=old_used.url, source_name="b",
                          domain="ret.example", source_type="PUBLICATION"))  # fmt: skip
        s.add(db.SearchCache(key=db.uid()[:32] + "x" * 32, provider="serper", query="ret", gl="es", hl="es", hits=[],
                             expires_at=past))  # fmt: skip
        await s.commit()
        ids = (old_free.id, old_used.id, fresh.id)
    counts = await run_retention()
    assert counts["documents"] >= 1 and counts["search_cache"] >= 1
    async with db.sessionmaker()() as s:
        left = set((await s.execute(select(db.Document.id).where(db.Document.id.in_(ids)))).scalars())
    assert left == {ids[1], ids[2]}
