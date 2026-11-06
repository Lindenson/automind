"""Spec 008 US6: the shared cache of the versions of model generations (table model_versions)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from automind.chat.domain.identification.ladder import Generation, Version
from automind.chat.infrastructure.persistence.repositories import ModelVersionsRepo
from automind.shared.infrastructure import db

V = [
    Version("2.0 TDI 116 CV", "diesel", 1968, 85, ("manual", "dct"), ("FWD",), 2020, None, "https://a", "116 CV"),
    Version("2.0 TDI 150 CV", "diesel", 1968, 110, ("dct",), ("FWD", "AWD"), 2020, None, "https://a", "150 CV"),
]


async def test_put_get_by_generation_year_and_new_with_ttl() -> None:
    repo = ModelVersionsRepo()
    await repo.put(Generation("SkodaT", "OctaviaT", "NX", 2020, None, "WAGON", V, [{"url": "https://a", "name": "a"}]))
    await repo.put(Generation("SkodaT", "OctaviaT", "Mk3", 2013, 2019, "WAGON", V[:1], []))
    g = await repo.get("SkodaT", "OctaviaT", "NX", None, True, 60)
    assert g is not None and g.versions == V and g.body_class == "WAGON"
    assert (await repo.get("skodat", "octaviat", None, None, True, 60)).generation == "NX"  # type: ignore[union-attr]
    assert (await repo.get("SkodaT", "OctaviaT", None, 2016, False, 60)).generation == "Mk3"  # type: ignore[union-attr]
    assert await repo.get("SkodaT", "OctaviaT", "B9", None, False, 60) is None
    # the same generation again: one row, replaced
    await repo.put(Generation("SkodaT", "OctaviaT", "NX", 2020, None, "WAGON", V[1:], []))
    g = await repo.get("SkodaT", "OctaviaT", "NX", None, True, 60)
    assert g is not None and [v.engine for v in g.versions] == ["2.0 TDI 150 CV"]
    # stale after the TTL
    async with db.sessionmaker()() as s:
        await s.execute(
            update(db.ModelVersions)
            .where(db.ModelVersions.make == "SkodaT")
            .values(fetched_at=datetime.now(UTC) - timedelta(days=61))
        )
        await s.commit()
    assert await repo.get("SkodaT", "OctaviaT", "NX", None, True, 60) is None
