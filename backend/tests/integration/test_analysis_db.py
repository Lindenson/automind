"""Deterministic pipeline on the real DB with seeded claims: reselect -> blocks (no LLM, no web)."""

import json

import pytest

from automind.acquisition.pipeline.infrastructure.wiring import value_selection
from automind.chat.application.services.identification import catalogue as catalog
from automind.chat.application.services.identification.contracts import VariantIdentity
from automind.chat.application.services.report.blocks.criteria import criteria_block
from automind.chat.application.services.report.blocks.metric_bars import metric_bars
from automind.chat.application.services.report.blocks.race import race_block
from automind.chat.application.services.report.blocks.sources import sources_block
from automind.chat.application.services.report.blocks.spec_table import spec_table
from automind.chat.application.services.report.facts.car import load_car
from automind.chat.application.services.report.facts.race import run_race
from automind.chat.application.services.report.facts.scoring_inputs import car_facts
from automind.chat.dialog.guard import check_numbers
from automind.chat.dialog.guard import numbers_in as _numbers_in
from automind.chat.domain.assessment.criteria import CriteriaModel, score
from automind.delivery.bootstrap import reference
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.loader import load_yaml

MODEL = CriteriaModel.from_config(load_yaml("criteria.yaml"))

DOC = (
    "Golf GTI: 180 kW (245 PS), 370 Nm, kerb weight 1.429 kg, 0-100 km/h 6,2 s, top speed 250 km/h, "
    "front-wheel drive, 7-speed DSG. Precio oficial: 47.500 €. Boot 374 litres, 5 seats."
)


async def _seed():
    await db.init_db()
    ident = VariantIdentity(
        make="TestMake",
        model="Golf",
        generation="Mk8",
        variant_name="GTI test",
        powertrain="ICE",
        body_class="HATCHBACK",
        generation_years_from=2021,
        generation_years_to=None,
        certainty="exact",
    )
    v = await catalog.upsert_variant(ident, reference({}))
    async with db.sessionmaker()() as s:
        doc = db.Document(url="https://www.volkswagen.es/golf-gti", title="VW", text=DOC)
        s.add(doc)
        await s.flush()
        e = db.Evidence(
            variant_id=v.id,
            document_id=doc.id,
            url=doc.url,
            source_name="Volkswagen ES",
            domain="volkswagen.es",
            source_type="MANUFACTURER",
        )
        s.add(e)
        await s.flush()
        for attr, num, txt, raw in [
            ("max_power", 180.0, None, "180 kW"),
            ("max_torque", 370.0, None, "370 Nm"),
            ("curb_mass", 1429.0, None, "1.429"),
            ("claimed_0_100", 6.2, None, "6,2"),
            ("top_speed", 250.0, None, "250"),
            ("drivetrain", None, "FWD", "front-wheel drive"),
            ("official_price_es", 47500.0, None, "47.500"),
            ("boot_volume", 374.0, None, "374"),
            ("seats", 5.0, None, "5"),
        ]:
            s.add(
                db.Claim(
                    variant_id=v.id,
                    evidence_id=e.id,
                    attribute=attr,
                    raw_value=raw,
                    value_num=num,
                    value_text=txt,
                    excerpt=raw,
                    provenance="MANUFACTURER_CLAIM",
                    status="ACCEPTED",
                )
            )
        await s.commit()
    await value_selection().reselect(v.id)
    return v


@pytest.mark.asyncio
async def test_blocks_from_seeded_claims():
    v = await _seed()
    car = await load_car(v.id)
    race = run_race([car])
    blocks = [
        spec_table([car], {v.id: True}),
        metric_bars([car]),
        race_block(race),
        criteria_block(
            score([car_facts(car, race.results[0])], {"performance": 60, "efficiency": 40}, MODEL), MODEL, []
        ),
        sources_block([car]),
    ]
    json.dumps(blocks)  # serializable
    table = blocks[0]
    power = next(r for r in table["rows"] if r["key"] == "max_power")["values"][0]
    assert power["confidence"] == "HIGH" and power["provenance"] == "MANUFACTURER_CLAIM" and power["sources"]
    assert not any(r["key"] == "consumption" for r in table["rows"])  # spec 004 FR-016: no empty rows
    assert blocks[2]["results"][0]["t_0_100"] > 5
    crit = blocks[3]["cars"][0]["parts"]
    assert crit["performance"]["score"] is not None and crit["efficiency"]["insufficient"]
    assert await catalog.stale_areas(v.id) == ["specs", "price", "maintenance"]


def test_number_check():
    allowed = _numbers_in({"t": 6.58, "p": "180 kW (245 PS)"})
    text, dropped = check_numbers("The Golf does 0-100 in 6.58 s. It has 300 PS.", allowed)
    assert "6.58" in text and "300" not in text and dropped == 1
    assert check_numbers("Rounded: 6.6 s and 245 PS.", allowed)[1] == 0
