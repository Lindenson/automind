"""Spec 012 S7 (T066): characterisation of identification paths the suite did not reach, pinned before the identify
and resolve modules become a service with stages and strategies. Test-only makes ("S7…") keep the shared catalogue
rows away from the goldens; every test's rows are removed before it starts."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete

from automind.chat.application.services.identification import (
    IdentificationService,
    IdentifyRequest,
    catalogue,
    resolver,
    revalidation,
)
from automind.chat.application.services.identification.contracts import GenerationMismatch, NotOnSale, VariantIdentity
from automind.chat.dialog.prompts import load_all
from automind.chat.domain.case import CaseCar, CaseFile, Constraints
from automind.delivery.bootstrap import reference
from automind.shared.infrastructure import db
from automind.shared.vehicle.identity import parse_engine

NOW = 2026


class LLM:
    """The resolver's answers in order; the prompts it was given are kept."""

    def __init__(self, *answers: VariantIdentity) -> None:
        self.answers, self.users = list(answers), []

    async def structured(self, name: str, schema: Any, prompt: str, user: str) -> VariantIdentity:
        self.users.append(user)
        return self.answers.pop(0)


def _ref(make: str, gens: list[tuple[str, int | None, int | None]]) -> Any:
    ref = reference(load_all())
    return dataclasses.replace(ref, makes=None, generations={**ref.generations, f"{make}|Rav": gens})


def _ident(make: str, **kw: Any) -> VariantIdentity:
    base: dict[str, Any] = dict(make=make, model="Rav", generation="G1", generation_years_from=2015,
                                generation_years_to=2024, variant_name="2.0 diesel 150 CV", powertrain="ICE",
                                certainty="exact", engine_cc=1998, power_kw=110, fuel="diesel")  # fmt: skip
    return VariantIdentity(**{**base, **kw})


def _ports(ref: Any, *answers: VariantIdentity) -> SimpleNamespace:
    return SimpleNamespace(ref=ref, llm=LLM(*answers), acquisition=None, versions=None)


async def _identify(ports: Any, case: CaseFile, car: CaseCar) -> Any:
    return await IdentificationService(ports).run(IdentifyRequest(case, car, NOW))


def _car(make: str, **kw: Any) -> CaseCar:
    return CaseCar(key="car#1", request_text=f"{make} Rav", make=make, model="Rav", **kw)


@pytest.fixture(autouse=True)
async def _db() -> None:
    """The test makes' catalogue rows of an earlier run are removed: every test starts from its own seed."""
    await db.init_db()
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.Variant).where(db.Variant.make.like("S7%")))
        await s.commit()


# --- the resolver (resolve_with_llm) ---------------------------------------------------------------------------


async def test_a_new_car_is_asked_again_for_the_generation_on_sale() -> None:
    make = "S7Newgen"
    ref = _ref(make, [("G1", 2015, 2024), ("G2", 2025, None)])
    ports = _ports(ref, _ident(make), _ident(make, generation="G2", generation_years_from=2025,
                                              generation_years_to=None))  # fmt: skip
    v, ident = await resolver.resolve_with_llm(ports, _car(make, condition="NEW"), NOW)
    assert ident.generation == "G2" and v.generation == "G2"
    assert "it is the G2 generation (2025–)" in ports.llm.users[1]


async def test_a_new_car_keeps_the_generation_on_sale_when_the_resolver_insists_on_another() -> None:
    make = "S7Stampgen"
    ref = _ref(make, [("G1", 2015, 2024), ("G2", 2025, None)])
    ports = _ports(ref, _ident(make), _ident(make))
    _, ident = await resolver.resolve_with_llm(ports, _car(make, condition="NEW"), NOW)
    assert (ident.generation, ident.generation_years_from, ident.generation_years_to) == ("G2", 2025, None)
    assert ident.note.endswith("Generation set to G2 (new car).")


async def test_an_engine_named_of_another_generation_is_not_on_sale() -> None:
    make = "S7Oldengine"
    ref = _ref(make, [("G1", 2015, 2024), ("G2", 2025, None)])
    car = _car(make, condition="NEW", constraints=Constraints(engine_hint=parse_engine("2.0 diesel 150 CV")))
    with pytest.raises(NotOnSale):
        await resolver.resolve_with_llm(_ports(ref, _ident(make), _ident(make)), car, NOW)


async def test_a_used_car_of_another_generation_is_a_mismatch() -> None:
    make = "S7Usedyear"
    ref = _ref(make, [("G1", 2015, 2024)])
    with pytest.raises(GenerationMismatch):
        await resolver.resolve_with_llm(_ports(ref, _ident(make)), _car(make, condition="USED", year=2008), NOW)


async def test_a_version_without_an_engine_is_never_stored() -> None:
    make = "S7Noengine"
    ref = _ref(make, [("G1", 2015, None)])
    bare = _ident(make, variant_name="Homura", engine_cc=None, power_kw=None, generation_years_to=None)
    with pytest.raises(NotOnSale, match="no engine named"):
        await resolver.resolve_with_llm(_ports(ref, bare), _car(make, condition="USED", year=2020), NOW)


async def test_no_euro_price_from_a_users_page_or_from_outside_europe() -> None:
    make = "S7Price"
    ref = _ref(make, [("G1", 2015, None)])
    priced = _ident(make, generation_years_to=None, price_eur=30000)
    page = _car(make, condition="USED", year=2020, constraints=Constraints(url="https://dealer.example/rav"))
    _, ident = await resolver.resolve_with_llm(_ports(ref, priced), page, NOW)
    assert ident.price_eur is None
    china = _car(make, condition="USED", year=2020)
    china.market = "CN"
    ports = _ports(ref, priced)
    _, ident = await resolver.resolve_with_llm(ports, china, NOW)
    assert ident.price_eur is None
    assert "market: NOT sold in Spain; sold on the CN market" in ports.llm.users[0]


# --- the open world after a catalogue miss (identify_car → resolver) -------------------------------------------


async def _seed_petrol(make: str) -> None:
    ref = _ref(make, [("G1", 2015, None)])
    for name, cc, kw in (("1.0 TSI 110 CV", 999, 81), ("2.0 TSI 190 CV", 1984, 140)):
        await catalogue.upsert_variant(_ident(make, variant_name=name, engine_cc=cc, power_kw=kw, fuel="petrol",
                                            generation_years_to=None), ref)  # fmt: skip


async def test_a_generation_mismatch_with_the_year_known_offers_the_engines_of_that_year() -> None:
    make = "S7Mismatch"
    await _seed_petrol(make)
    ref = _ref(make, [("G1", 2015, None)])
    car = _car(make, condition="USED", year=2018, constraints=Constraints(engine_hint=parse_engine("3.0 diesel")))
    ports = _ports(ref, _ident(make, generation="G0", generation_years_from=2001, generation_years_to=2006))
    o = await _identify(ports, CaseFile(cars=[car]), car)
    assert (o.outcome, o.need) == ("CHOICES", "ENGINE")
    assert sorted(c.label for c in o.choices) == [f"{make} Rav G1 1.0 TSI 110 CV", f"{make} Rav G1 2.0 TSI 190 CV"]
    assert all(c.variant_id for c in o.choices) and "does not match ~2018" in (o.note or "")


async def test_a_generation_mismatch_without_engines_asks_the_year() -> None:
    make = "S7Mismatchnone"
    ref = _ref(make, [("G1", 2015, None)])
    car = _car(make, condition="USED", year=2018)
    ports = _ports(ref, _ident(make, generation="G0", generation_years_from=2001, generation_years_to=2006))
    o = await _identify(ports, CaseFile(cars=[car]), car)
    assert (o.outcome, o.need) == ("NEED", "YEAR")


async def test_a_version_not_on_sale_offers_the_catalogued_engines() -> None:
    make = "S7Notonsale"
    await _seed_petrol(make)
    ref = _ref(make, [("G1", 2015, None)])
    car = _car(make, condition="USED", year=2018, constraints=Constraints(engine_hint=parse_engine("3.0 diesel")))
    ports = _ports(ref, _ident(make, variant_name="Homura", engine_cc=None, power_kw=None, generation_years_to=None))
    o = await _identify(ports, CaseFile(cars=[car]), car)
    assert (o.outcome, o.need, len(o.choices)) == ("CHOICES", "ENGINE", 2)


async def test_the_resolver_answering_another_model_twice_is_not_found() -> None:
    make = "S7Othermodel"
    ref = _ref(make, [("G1", 2015, None)])
    car = _car(make, condition="USED", year=2018)
    other = _ident(make, model="Zorro", generation_years_to=None)
    ports = _ports(ref, other, other)
    o = await _identify(ports, CaseFile(cars=[car]), car)
    assert (o.outcome, o.need, car.resolution) == ("NOT_FOUND", "MODEL", "UNRESOLVED")
    assert "NOT the model asked (Rav)" in ports.llm.users[1]


# --- the year of a used car ------------------------------------------------------------------------------------


async def test_a_used_car_without_a_year_is_asked_once_then_assumed() -> None:
    make = "S7Noyear"
    ref = _ref(make, [("G1", 2015, None)])
    car = _car(make, condition="USED")
    case = CaseFile(cars=[car])
    o = await _identify(_ports(ref), case, car)
    assert (o.outcome, o.need) == ("NEED", "YEAR")
    case.intake.attempts["car#1"] = {"YEAR": 1}
    car.mileage_km = 60000
    ports = _ports(ref, _ident(make, generation_years_to=None))
    o = await _identify(ports, case, car)
    assert car.year_assumed and car.year is not None and car.age_years == NOW - car.year
    assert o.outcome == "IDENTIFIED"


# --- the gearbox of a catalogued variant -----------------------------------------------------------------------


async def test_a_named_gearbox_of_a_variant_without_one_makes_its_own_variant() -> None:
    make = "S7Gearbox"
    ref = _ref(make, [("G1", 2015, None)])
    v = await catalogue.upsert_variant(_ident(make, generation_years_to=None), ref)
    car = _car(make, condition="USED", year=2020, variant_id=v.id, label=v.label, resolution="PROPOSED",
               constraints=Constraints(gearbox_hint="automatic"))  # fmt: skip
    note = await revalidation.split_by_gearbox(car, ref)
    assert note is not None and note.endswith("(the gearbox you named)")
    new = await catalogue.get_variant(car.variant_id or "")
    assert new is not None and new.id != v.id and new.transmission == "automatic"
    assert car.resolution == "CONFIRMED"
    assert await revalidation.split_by_gearbox(car, ref) is None  # the variant has the gearbox named now


async def test_another_gearbox_than_the_variants_identifies_again() -> None:
    make = "S7Othergearbox"
    ref = _ref(make, [("G1", 2015, None)])
    v = await catalogue.upsert_variant(_ident(make, generation_years_to=None, transmission="manual"), ref)
    car = _car(make, condition="USED", year=2020, variant_id=v.id, label=v.label, resolution="PROPOSED",
               constraints=Constraints(gearbox_hint="automatic"))  # fmt: skip
    note = await revalidation.split_by_gearbox(car, ref)
    assert note == f"car#1: {v.label} is another gearbox or drive; identified again"
    assert (car.variant_id, car.resolution) == (None, "UNRESOLVED")
