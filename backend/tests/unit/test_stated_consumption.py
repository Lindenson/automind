"""The user's own consumption figures (spec 006 follow-up). The live check of 2026-11-04 left the BYD Seal U DM-i
without an energy line: no source publishes its charge-sustaining consumption. The owner knows it ("в гибридном
режиме 5,5 л"): such a figure is read from the words, tied to the right car and replaces the missing or estimated
value, labelled as the user's."""

from pathlib import Path

import pytest
import yaml

from automind.chat.dialog.nodes.understand import _energy_from_text
from automind.chat.domain.case.casefile import CaseCar, CaseFile, StatedEnergy
from automind.chat.domain.cost import energy as en
from automind.chat.domain.intake.intake import energy_figures_of, stated_for_cars
from automind.shared.vehicle.makes import MakeRegistry

REG = MakeRegistry.from_config(yaml.safe_load((Path(__file__).parents[2] / "config" / "makes.yaml").read_text()))


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("BYD в гибридном режиме 5,5 л", [("CS", 5.5)]),
        ("with an empty battery it uses 6.1 l/100km", [("CS", 6.1)]),
        ("El BYD gasta 5,5 litros con la batería descargada y recorre 70 km en eléctrico", [("CS", 5.5),
                                                                                            ("RANGE", 70.0)]),
        ("расход Атеки 7 л, а у BYD в гибридном режиме 5,5 л", [("FUEL", 7.0), ("CS", 5.5)]),
        ("Ateca gasta 7,5 l/100 km", [("FUEL", 7.5)]),
        ("у меня 1.5 л двигатель, расход 7 л", [("FUEL", 7.0)]),  # the engine size is not a consumption
        ("18 кВт·ч на 100", [("KWH", 18.0)]),
        ("на электричестве проезжаю 70 км", [("RANGE", 70.0)]),
        # not consumption figures
        ("батарея 18,3 кВт·ч", []),
        ("езжу 40 км в день на электричестве", []),
        ("скорость 120 км/ч на электричестве", []),
        ("плачу 12 центов за кВт·ч", []),
        ("бюджет 35 тысяч, двигатель 2.0 л", []),
        ("расход 0,9 л", []),  # the weighted WLTP figure of a plug-in is not a real consumption
    ],
)  # fmt: skip
def test_figures_from_words(text, want):
    assert [(f.kind, f.value) for f in energy_figures_of(text)] == want


def _case() -> CaseFile:
    return CaseFile(cars=[CaseCar(key="car#1", request_text="BYD Seal U DM-i", make="BYD", model="Seal U DM-i"),
                          CaseCar(key="car#2", request_text="SEAT Ateca", make="SEAT", model="Ateca")])  # fmt: skip


def test_figures_go_to_the_car_named_before_them():
    case = _case()
    log = _energy_from_text(case, "У Атеки реальный расход 8 л, а BYD в гибридном режиме ест 5,5 л.", REG)
    got = {(s.kind, s.car_key, s.value) for s in case.stated_energy}
    assert got == {("FUEL", "car#2", 8.0), ("CS", "car#1", 5.5)}
    assert len(log) == 2 and "your figure for car#1: 5.5" in log[1]
    # a newer figure replaces the older one for the same car and kind
    _energy_from_text(case, "Нет, у BYD в гибридном режиме скорее 6 л", REG)
    assert sorted((s.kind, s.value) for s in case.stated_energy) == [("CS", 6.0), ("FUEL", 8.0)]


def test_unnamed_figure_goes_to_the_only_car_it_fits():
    pts = [("car#1", "PHEV"), ("car#2", "ICE")]
    cs = StatedEnergy(kind="CS", value=5.5, words="в гибридном режиме 5,5 л")
    assert stated_for_cars([cs], pts) == {"car#1": {"CS": (5.5, "в гибридном режиме 5,5 л")}}
    # named the wrong car ("Ateca, 5,5 л в гибридном режиме"): the plug-in is the only car with a hybrid mode
    assert stated_for_cars([cs.model_copy(update={"car_key": "car#2"})], pts) == stated_for_cars([cs], pts)
    fuel = StatedEnergy(kind="FUEL", value=7.0, words="расход 7 л")
    assert stated_for_cars([fuel], pts) == {"car#2": {"FUEL": (7.0, "расход 7 л")}}
    # two combustion cars, no name: whose figure it is cannot be told, so it is not used
    assert stated_for_cars([fuel], [("a", "ICE"), ("b", "HEV")]) == {}


RWF = {"ICE": 1.15, "HEV": 1.15, "BEV": 1.2}
R = en.Rates(en.Price(1.60, "l", "petrol"), en.Price(1.50, "l", "diesel"), RWF, en.EnergyConfig())
# the BYD as the catalog holds it after the live check: no charge-sustaining figure anywhere
BYD = en.EnergyCar("PHEV", "petrol", consumption=0.9, consumption_ev=21.0, battery_kwh=18.3, range_wltp=80)


def test_the_users_figure_closes_the_missing_input():
    use = en.UsageContext(18000, home_charging="YES")
    assert en.estimate(BYD, R, use).missing == [en.CS_MISSING]
    said = "в гибридном режиме 5,5 л"
    e = en.estimate(BYD.__class__(**{**BYD.__dict__, "stated": {"CS": (5.5, said)}}), R, use)
    assert not e.missing and [p.energy for p in e.parts] == ["electricity", "petrol"]
    assert e.parts[1].per_100km == 5.5  # real use already: no allowance on top
    assert any("your figure 5.5 l/100 km" in i and said in i for i in e.inputs)


def test_users_figures_replace_estimates():
    use = en.UsageContext(15000, home_charging="YES")
    ice = en.EnergyCar("ICE", "petrol", consumption=6.3, stated={"FUEL": (8.0, "реально 8 л")})
    e = en.estimate(ice, R, use)
    assert e.parts[0].per_100km == 8.0 and "your figure" in e.inputs[0]
    bev = en.EnergyCar("BEV", consumption_ev=15.0, stated={"KWH": (18.0, "18 кВт·ч на 100")})
    b = en.estimate(bev, R, use)
    assert b.parts[0].per_100km > 18.0  # the car's display: charging losses are added once
    phev = en.EnergyCar("PHEV", "petrol", consumption_cs=5.3, consumption_ev=21.0, range_wltp=80,
                        stated={"RANGE": (50.0, "на электричестве 50 км")})  # fmt: skip
    rng, how = en.electric_range(phev, R, use)
    assert rng == 50.0 and "your figure" in how


def test_the_figure_reaches_the_ownership_cost():
    from automind.chat.domain.cost import tco

    rates = tco.TcoRates.from_config({
        **yaml.safe_load((Path(__file__).parents[2] / "config" / "rates.yaml").read_text()),
        "energy": yaml.safe_load((Path(__file__).parents[2] / "config" / "energy.yaml").read_text()),
    })  # fmt: skip
    car = tco.TcoCar("byd", "BYD", "PHEV", "petrol", consumption=0.9, consumption_ev=21.0, battery_kwh=18.3,
                     range_wltp=80, stated={"CS": (5.5, "в гибридном режиме 5,5 л")})  # fmt: skip
    energy = next(i for i in tco.compute(car, rates, 18000).items if i.kind == "ENERGY")
    assert energy.annual_eur and not energy.missing
