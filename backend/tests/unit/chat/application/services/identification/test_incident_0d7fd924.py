"""Chat 0d7fd924 (2026-11-03, Mazda CX-5 vs Honda CR-V, family, new 2025): the Mazda was asked five times.

- the gearbox question offered the car's versions as chips; a tapped version did not answer it ("not understood");
- a tapped option went through the interpreter, which kept the generation of an earlier option ("KF" + 3rd gen);
- the Mazda added again was asked "new or used?" and became the old generation (KF) for a new purchase;
- the resolver stamped the current generation on an engine of the previous one ("3rd gen 2.0 165 CV");
- names repeated the make ("Mazda CX-5 Mazda CX-5 …"), a version without an engine became a variant;
- "find the missing data" was offered again after a deeper search found nothing; "pays back in 77 years".
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from automind.chat.application.services.identification.resolve import (
    _fits,
    _strip_prefix,
    bought_now,
    current_generation,
)
from automind.chat.application.services.interpretation import ask
from automind.chat.application.services.report.compose import data_panel_block
from automind.chat.dialog import phrases
from automind.chat.dialog.prompts import load_all
from automind.chat.domain.case.casefile import CaseCar, CaseFile, Choice, Constraints, IdentifyOutcome, Pending
from automind.chat.domain.intake import intake
from automind.delivery.bootstrap import reference
from automind.shared.infrastructure import db
from automind.shared.vehicle import identity
from automind.shared.vehicle.engine import EngineHint

KF_VERSION = "Mazda CX-5 KF 2.0 e-Skyactiv G 165 PS"


def _case(pending_items, cars):
    return CaseFile(cars=cars, pending=Pending(kind="QUESTIONS", items=pending_items))


def _mazda(**kw):
    return CaseCar(key="car#3", request_text="Mazda", make="Mazda", model="CX-5", **kw)


def _pick(case, text):
    return intake.pick(case, text, gearbox_words=phrases.GEARBOX_WORDS, yes=phrases.yes_or_no(text) == "yes",
                       choose=phrases.choose_for_me(text))  # fmt: skip


def test_gearbox_question_offers_gearboxes_not_versions():
    car = _mazda(identify=IdentifyOutcome(outcome="IDENTIFIED", choices=[Choice(label=KF_VERSION, variant_id="v1")]))
    case = CaseFile(cars=[car])
    q = ask.intake_questions(["GEARBOX"], case, reference(load_all()).questions_i18n, {}, ["car#3"],
                                          "ru", {"automatic": "Автомат", "manual": "Механика"})  # fmt: skip
    assert q and q[0]["choices"] == [] and "Автомат" in q[0]["text"] and KF_VERSION not in q[0]["text"]
    labels = {"new": "Новые", "used": "Б/у", "yes": "Да", "no": "Нет", "choose": "Выбери сам",
              "remove": "Убрать {car}", "automatic": "Автомат", "manual": "Механика"}  # fmt: skip
    chips = [c["label"] for c in ask.intake_quick_replies(q, case, labels)]
    assert chips[:2] == ["Автомат", "Механика"] and "Выбери сам" in chips and KF_VERSION not in chips


def test_a_tapped_gearbox_or_choose_for_me_answers_by_code():
    case = _case([{"kind": "GEARBOX", "car": "car#3", "item": "GEARBOX", "text": "?"}], [_mazda()])
    new, log = _pick(case, "Автомат")
    assert new.car("car#3").constraints.gearbox_hint == "automatic" and log
    new, _ = _pick(case, "Выбери сам")
    assert new.car("car#3").constraints.gearbox_hint == "automatic"
    assert _pick(case, "а какая надёжнее?") is None  # not an option: the interpreter reads it


def test_a_tapped_version_replaces_the_hints_of_an_earlier_option():
    stale = _mazda(constraints=Constraints(generation_hint="KF", trim_hint="Exclusive-Line",
                                           engine_hint=EngineHint(displacement_l=2.0, power_kw=121)))  # fmt: skip
    choices = [Choice(label="Mazda CX-5 3rd gen 2.5 e-Skyactiv G 141 CV", make="Mazda", model="CX-5", variant_id="v3"),
               Choice(label="Mazda CX-5 2.5 e-Skyactiv G 141 CV", make="Mazda", model="CX-5")]  # fmt: skip
    items = [{"kind": "ENGINE", "car": "car#3", "item": "ENGINE", "text": "?",
              "choices": [c.model_dump(mode="json") for c in choices]}]  # fmt: skip
    new, _ = _pick(_case(items, [stale]), "Mazda CX-5 3rd gen 2.5 e-Skyactiv G 141 CV")
    car = new.car("car#3")
    assert (car.variant_id, car.resolution) == ("v3", "CONFIRMED")
    assert car.constraints.generation_hint is None and car.constraints.trim_hint is None
    new, _ = _pick(_case(items, [stale]), "mazda cx-5 2.5 e-skyactiv g 141 cv")  # typed, other case
    car = new.car("car#3")
    assert car.variant_id is None and car.constraints.generation_hint is None
    assert car.constraints.engine_hint is not None and car.constraints.engine_hint.power_kw == 104


def test_yes_to_a_proposal_takes_the_proposed_version():
    ch = Choice(label="Mazda CX-5 3rd gen 2.5 e-Skyactiv G 141 CV", make="Mazda", model="CX-5", variant_id="v3")
    items = [{"kind": "PROPOSE", "car": "car#3", "item": "CHOICE", "text": "?", "choices": [ch.model_dump()]}]
    new, _ = _pick(_case(items, [_mazda()]), "Да")
    assert new.car("car#3").variant_id == "v3"


def test_a_car_added_later_is_bought_like_the_others():
    honda = CaseCar(key="car#2", request_text="Honda CR-V", make="Honda", model="CR-V", condition="NEW", year=2025)
    before = CaseFile(cars=[honda])
    after = CaseFile(cars=[honda, _mazda()])
    assert intake.inherit_condition(before, after) == ["car#3: new like the other cars"]
    assert (after.car("car#3").condition, after.car("car#3").year) == ("NEW", 2025)
    mixed = CaseFile(cars=[honda, honda.model_copy(update={"key": "car#4", "condition": "USED"})])
    later = CaseFile(cars=[*mixed.cars, _mazda()])
    assert intake.inherit_condition(mixed, later) == [] and later.car("car#3").condition == "UNKNOWN"


def test_a_new_2025_car_is_the_generation_on_sale_now():
    ref = reference(load_all())
    kf = db.Variant(make="Mazda", model="CX-5", generation="KF", variant_name="2.0 e-Skyactiv G 165 PS",
                    powertrain="MHEV", generation_years_from=2017, generation_years_to=None)  # fmt: skip
    new25 = _mazda(condition="NEW", year=2025)
    assert bought_now(new25, 2026) and not _fits(kf, new25, None, 2026, ref)  # config: KF ended 2025
    assert current_generation(ref, new25, 2026) == ("3rd gen", 2026)
    used = _mazda(condition="USED", year=2021)
    assert not bought_now(used, 2026) and _fits(kf, used, None, 2026, ref)


def test_names_never_repeat_the_make_and_model():
    assert identity.normalize_make_model("Mazda", "Mazda CX-5") == ("Mazda", "CX-5")
    assert identity.normalize_make_model("Mazda", "CX-5") == ("Mazda", "CX-5")
    assert _strip_prefix("Mazda CX-5 2.0 e-Skyactiv G 165 CV MHEV Homura", "Mazda", "CX-5", "3rd gen") == (
        "2.0 e-Skyactiv G 165 CV MHEV Homura"
    )
    assert _strip_prefix("3rd gen Mazda CX-5 2.5 e-Skyactiv G", "Mazda", "CX-5", "3rd gen") == "2.5 e-Skyactiv G"
    assert _strip_prefix("2.5 e-Skyactiv G", "Mazda", "CX-5", None) == "2.5 e-Skyactiv G"


def test_the_generation_gearbox_from_config():
    ref = reference(load_all())
    assert ref.gearboxes["Mazda|CX-5|3rd gen"] == ["automatic"]
    assert sorted(ref.gearboxes["Mazda|CX-5|kf"]) == ["automatic", "manual"]


def test_find_it_is_not_offered_again_after_a_deeper_search_found_nothing():
    now = datetime(2026, 11, 3, 20, tzinfo=UTC)
    run = SimpleNamespace(minimum_met=False, claims_accepted=1, docs_used=2, completed_at=now - timedelta(minutes=5))
    car = {"variant": SimpleNamespace(id="v1"), "runs": {"price": run}, "values": {}}
    first = data_panel_block([("car#3", "CX-5", car)], {"car#3": {"price"}}, now)
    again = data_panel_block([("car#3", "CX-5", car)], {"car#3": {"price"}}, now, tried={"v1": ["price"]})
    assert first and first["cars"][0]["areas"][0]["findable"] is True
    area = again and again["cars"][0]["areas"][0]
    assert area and area["findable"] is False and area["status"] == "PARTIAL" and "deeper" in area["reason"]
