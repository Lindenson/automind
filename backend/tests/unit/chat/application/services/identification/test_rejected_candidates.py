"""Spec 013 S2 (T022–T024): a rejected candidate is never proposed or offered — by sourced versions, catalogue rows,
the open world, the ladder's options or the line-up — a version that contradicts the person's words is asked, not
proposed, and after a rejection a dead end widens. The owner's chat d170b861 (C-Class rejected, E-Class proposed)
is replayed at the service level. Test-only makes ("S2…") keep the shared catalogue rows away from the goldens."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete

from automind.acquisition.api import CatalogueVariant
from automind.chat.application.services.identification import IdentificationService, IdentifyRequest, catalogue
from automind.chat.application.services.identification import versions as versions_module
from automind.chat.application.services.identification.contracts import KnownModels, Lineup, Placed, VariantIdentity
from automind.chat.application.services.identification.stages.ask_model import ask_model
from automind.chat.application.services.identification.stages.narrow_ladder import asked
from automind.chat.application.services.identification.stages.offer_engines import close_lineup
from automind.chat.application.services.identification.stages.verify_proposal import verify_proposal
from automind.chat.application.services.identification.strategies.sourced_versions import SourcedVersions
from automind.chat.application.services.interpretation.contracts import Interpretation
from automind.chat.application.services.interpretation.stages.heard_rejections import heard_rejections
from automind.chat.dialog.prompts import load_all
from automind.chat.domain.case import CaseCar, CaseFile, IdentifyOutcome, apply
from automind.chat.domain.identification import ladder
from automind.chat.domain.identification.rejection import Rejection, RejectLevel
from automind.chat.domain.intake import LineupModel
from automind.delivery.bootstrap import reference
from automind.shared.infrastructure import db

NOW = 2026


class LLM:
    """The resolver's answers in order."""

    def __init__(self, *answers: VariantIdentity) -> None:
        self.answers = list(answers)

    async def structured(self, name: str, schema: Any, prompt: str, user: str) -> VariantIdentity:
        return self.answers.pop(0)


@pytest.fixture(autouse=True)
async def _db() -> None:
    await db.init_db()
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.Variant).where(db.Variant.make.like("S2%")))
        await s.commit()


def _ref(make: str, model: str = "Rav") -> Any:
    ref = reference(load_all())
    gens = {**ref.generations, f"{make}|{model}": [("G1", 2015, None)]}
    return dataclasses.replace(ref, makes=None, generations=gens)


def _ident(make: str, **kw: Any) -> VariantIdentity:
    base: dict[str, Any] = dict(make=make, model="Rav", generation="G1", generation_years_from=2015,
                                generation_years_to=None, variant_name="2.0 diesel 150 CV", powertrain="ICE",
                                certainty="exact", engine_cc=1998, power_kw=110, fuel="diesel")  # fmt: skip
    return VariantIdentity(**{**base, **kw})


def _ports(ref: Any, *answers: VariantIdentity) -> SimpleNamespace:
    return SimpleNamespace(ref=ref, llm=LLM(*answers), acquisition=None, versions=None)


def _car(make: str, *rejected: Rejection, model: str | None = "Rav", **kw: Any) -> CaseCar:
    return CaseCar(key="car#1", request_text=f"{make} {model or ''}", make=make, model=model,
                   identity_rejected=list(rejected), **kw)  # fmt: skip


async def _identify(ports: Any, car: CaseCar) -> IdentifyOutcome:
    return await IdentificationService(ports).run(IdentifyRequest(CaseFile(cars=[car]), car, NOW))


async def _seed(make: str, model: str = "Rav") -> None:
    ref = _ref(make, model)
    for name, cc, kw in (("1.0 TSI 110 CV", 999, 81), ("2.0 TSI 190 CV", 1984, 140)):
        await catalogue.upsert_variant(_ident(make, model=model, variant_name=name, engine_cc=cc, power_kw=kw,
                                              fuel="petrol"), ref)  # fmt: skip


# --- each strategy (T022) --------------------------------------------------------------------------------------


async def test_catalogue_rows_never_propose_the_rejected_row() -> None:
    make = "S2Rows"
    await _seed(make)
    o = await _identify(_ports(_ref(make)), _car(make, condition="NEW"))
    assert (o.outcome, o.need) == ("CHOICES", "ENGINE")  # two rows the words do not tell apart: asked
    no_small = Rejection(level=RejectLevel.VERSION, value=f"{make} Rav G1 1.0 TSI 110 CV", evidence="не 1.0")
    car = _car(make, no_small, condition="NEW")
    o = await _identify(_ports(_ref(make)), car)
    assert o.outcome == "IDENTIFIED" and car.label == f"{make} Rav G1 2.0 TSI 190 CV"


async def test_the_open_world_never_proposes_a_rejected_answer() -> None:
    make = "S2Open"
    rejected = Rejection(level=RejectLevel.VERSION, value="2.0 diesel 150 CV", evidence="не этот")
    car = _car(make, rejected, condition="USED", year=2018)
    o = await _identify(_ports(_ref(make), _ident(make)), car)
    assert car.variant_id is None and car.label is None and o.outcome == "NOT_FOUND"
    assert [e["kind"] for e in o.events][-1] == "version_not_found"  # T024: said, a link or the engine asked


async def test_sourced_versions_skip_the_rejected_version_and_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    make = "S2Sourced"
    gen = ladder.Generation(make=make, model="Rav", generation="G1", years_from=2015, years_to=None, versions=[
        ladder.Version(engine="1.5 TSI 150 CV", fuel="petrol", engine_cc=1498, power_kw=110, gearboxes=("dct",)),
        ladder.Version(engine="2.0 TDI 150 CV", fuel="diesel", engine_cc=1968, power_kw=110, gearboxes=("dct",)),
    ])  # fmt: skip

    async def lookup(*_: Any, **__: Any) -> ladder.Generation:
        return gen

    monkeypatch.setattr(versions_module, "lookup", lookup)
    ports = SimpleNamespace(ref=_ref(make), llm=LLM(), acquisition=None, versions=object())
    car = _car(make, Rejection(level=RejectLevel.ENGINE, value="1.5 TSI 150 CV"), condition="NEW")
    o = await SourcedVersions(ports).identify(Placed(CaseFile(cars=[car]), car, NOW, None))
    assert o is not None and o.outcome == "IDENTIFIED" and "2.0 TDI" in (car.label or "")
    other = _car(make, Rejection(level=RejectLevel.GENERATION, value="G1"), condition="NEW")
    assert await SourcedVersions(ports).identify(Placed(CaseFile(cars=[other]), other, NOW, None)) is None


def test_the_ladder_never_offers_a_rejected_option() -> None:
    car = _car("S2Ladder", Rejection(level=RejectLevel.GEARBOX, value="manual"))
    options = [ladder.Option(level="GEARBOX", label="manual", gearbox="manual"),
               ladder.Option(level="GEARBOX", label="DSG", gearbox="dct")]  # fmt: skip
    step = ladder.Step(kind="GEARBOX", options=options)
    o = asked(car, ladder.Decision(step=step, wanted=ladder.Wanted()), [])
    assert [c.label for c in o.choices] == ["DSG"]


def test_the_line_up_never_offers_a_rejected_model() -> None:
    make = "S2Lineup"
    lineup = Lineup(make=make, models=[LineupModel(model="E-Class"), LineupModel(model="C-Class")])
    car = _car(make, Rejection(level=RejectLevel.MODEL, value="E-Class"), model=None)
    o = ask_model(car, CaseFile(cars=[car]), KnownModels(lineup, set(), {"E-Class", "C-Class"}), None)
    assert [c.model for c in o.choices] == ["C-Class"]
    car.model = "CLS"
    assert [c.model for c in close_lineup(lineup, car)] == ["C-Class"]


# --- verification before a proposal (T023) ---------------------------------------------------------------------


async def test_a_version_of_another_model_is_asked_with_the_contradiction_named() -> None:
    row = CatalogueVariant(id="v1", make="Mercedes-Benz", model="E-Class", generation="W214",
                           variant_name="E 200 automatic", powertrain="MHEV")  # fmt: skip

    async def by_id(_: str) -> CatalogueVariant:
        return row

    car = _car("Mercedes-Benz", model="C-Class", variant_id="v1", label=row.label, resolution="PROPOSED")
    o = await verify_proposal(car, IdentifyOutcome(outcome="IDENTIFIED"), by_id)
    assert (o.outcome, o.need, car.variant_id, car.resolution) == ("CHOICES", "MODEL", None, "UNRESOLVED")
    assert [c.model for c in o.choices] == ["C-Class", "E-Class"] and o.choices[0].reason == "your_words"
    assert o.events[-1] == {"kind": "contradiction", "fact": "model", "said": "C-Class", "found": "E-Class"}
    no_e = _car("Mercedes-Benz", Rejection(level=RejectLevel.MODEL, value="E-Class"), model="C-Class",
                variant_id="v1", label=row.label, resolution="PROPOSED")  # fmt: skip
    o = await verify_proposal(no_e, IdentifyOutcome(outcome="IDENTIFIED"), by_id)
    assert [c.model for c in o.choices] == ["C-Class"]  # the rejected one is not offered back


# --- the owner's chat d170b861, turn 2 (T021 → T024) -----------------------------------------------------------


async def test_c_class_rejected_e_class_never_proposed_again() -> None:
    make = "S2Benz"
    await _seed(make, "E-Class")
    await _seed(make, "GLC")
    shown = CaseCar(key="car#1", request_text="Clase C Berlina мерседесом", make=make, model="E-Class",
                    label=f"{make} E-Class G1 1.0 TSI 110 CV", variant_id="v-e", resolution="PROPOSED")  # fmt: skip
    case = CaseFile(cars=[shown], next_car_no=2)
    text = "ты не нашел мерседес класс C. отменяй поиск. пошел в жопу"
    read = Interpretation.model_validate({"request": "correction", "language": "ru", "delta": {
        "replace_cars": [{"target_key": "car#1", "make": make, "model": "C-Class"}],
        "rejections": [{"target_key": "car#1", "level": "MODEL", "value": "E-Class", "wanted": "C-Class",
                        "evidence": "ты не нашел мерседес класс C"}]}})  # fmt: skip
    case, _ = apply(case, heard_rejections(case, read, text).delta, current_year=NOW)
    car = case.cars[0]
    assert car.model == "C-Class" and car.variant_id is None
    e_class = _ident(make, model="E-Class", variant_name="1.0 TSI 110 CV", engine_cc=999, power_kw=81)
    ports = _ports(_ref(make, "C-Class"), e_class, e_class)  # the resolver insists on the E-Class
    o = await IdentificationService(ports).run(IdentifyRequest(case, car, NOW))
    assert car.model == "C-Class" and car.label is None
    assert "E-Class" not in " ".join(c.label for c in o.choices)
    assert [c.model for c in o.choices] == ["GLC"]  # widened: the make's other models, not the rejected one
    assert o.events[-1]["kind"] in ("not_found_checked", "not_found_wider") and o.events[-1]["wanted"] == "C-Class"
