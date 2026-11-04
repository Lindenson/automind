"""Catalog clean-up: rows that are one car under two names fold into the row with the evidence; chats follow."""

from sqlalchemy import select

from automind.application import repair
from automind.infrastructure import db

ENGINE = {"model": "320d", "generation": "G20", "powertrain": "MHEV", "engine_cc": 1995, "power_kw": 140,
          "transmission": "automatic", "body_class": "SEDAN"}  # fmt: skip


async def _seed(make: str) -> tuple[str, str, str, str]:
    async with db.sessionmaker()() as s:
        rich = db.Variant(canonical_key=f"{make}|a", make=make, variant_name="320d M Sport 8-speed automatic",
                          **ENGINE)  # fmt: skip
        bare = db.Variant(canonical_key=f"{make}|b", make=make, variant_name="320d M Sport", drive="RWD", **ENGINE)
        other = db.Variant(canonical_key=f"{make}|c", make=make, variant_name="320d xDrive",
                           **{**ENGINE, "drive": "AWD", "power_kw": 140})  # fmt: skip
        s.add_all([rich, bare, other])
        await s.flush()
        doc = db.Document(url=f"https://example.com/{make}", text="Maletero 480 litros")
        s.add(doc)
        await s.flush()
        e1 = db.Evidence(variant_id=rich.id, document_id=doc.id, url=doc.url, source_name="x", domain="example.com",
                         source_type="PUBLICATION")  # fmt: skip
        e2 = db.Evidence(variant_id=bare.id, document_id=doc.id, url=doc.url, source_name="x", domain="example.com",
                         source_type="PUBLICATION")  # fmt: skip
        s.add_all([e1, e2])
        await s.flush()
        s.add(
            db.Claim(
                variant_id=rich.id,
                evidence_id=e1.id,
                attribute="boot_volume",
                raw_value="480",
                value_num=480,
                excerpt="Maletero 480 litros",
                provenance="SOURCED_FACT",
                status="ACCEPTED",
            )
        )
        s.add(db.SpecValue(variant_id=bare.id, attribute="boot_volume", available=True, value_num=470))
        chat = db.uid()
        s.add(db.CaseFileRow(chat_id=chat, version=1, data={"cars": [{"variant_id": bare.id}]}, changed_by="USER",
                             change_log=[]))  # fmt: skip
        await s.commit()
        return rich.id, bare.id, other.id, chat


async def test_dry_run_changes_nothing_and_apply_folds_the_duplicate():
    await db.init_db()
    make = f"T{db.uid()[:8]}"
    rich, bare, other, chat = await _seed(make)

    plan = await repair.merge_duplicates(apply=False, make=make)
    assert [(g["keep"], g["fold"]) for g in plan["groups"]] == [(rich, [bare])]  # xDrive (AWD) is another car
    async with db.sessionmaker()() as s:
        assert await s.get(db.Variant, bare) is not None

    await repair.merge_duplicates(apply=True, make=make)
    async with db.sessionmaker()() as s:
        assert await s.get(db.Variant, bare) is None and await s.get(db.Variant, other) is not None
        kept = await s.get(db.Variant, rich)
        assert kept is not None and kept.drive == "RWD"  # a field only the folded row knew
        case = (await s.execute(select(db.CaseFileRow).where(db.CaseFileRow.chat_id == chat))).scalar_one()
        assert case.data["cars"][0]["variant_id"] == rich
        values = {v.attribute: v for v in (await s.execute(
            select(db.SpecValue).where(db.SpecValue.variant_id == rich))).scalars()}  # fmt: skip
        assert values["boot_volume"].value_num == 480  # selected again from all claims, not the folded row's 470
        ev = (await s.execute(select(db.Evidence).where(db.Evidence.variant_id == bare))).all()
        assert ev == []
    assert (await repair.merge_duplicates(apply=False, make=make))["groups"] == []
