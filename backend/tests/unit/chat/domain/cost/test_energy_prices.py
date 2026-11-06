"""Spanish prices, the user's charging situation and prices, and the home-charging question (spec 006 US3)."""

from pathlib import Path

import pytest
import yaml

from automind.chat.domain import understanding
from automind.chat.domain.assessment import ask_value
from automind.chat.domain.case import CaseFile
from automind.chat.domain.cost import tco

CONFIG = Path(__file__).parents[5] / "config"
RATES = {
    **yaml.safe_load((CONFIG / "rates.yaml").read_text()),
    "energy": yaml.safe_load((CONFIG / "energy.yaml").read_text()),
}


def rates(today: str | None = "2026-11-04", **override) -> tco.TcoRates:
    return tco.TcoRates.from_config({**RATES, "today": today}, override)


def bev(home: str) -> tco.TcoCar:
    from automind.chat.domain.cost.energy import UsageContext

    return tco.TcoCar("e", "EV", "BEV", consumption_ev=16.0, vehicle_class="compact",
                      use=UsageContext(18000, home_charging=home))  # fmt: skip


def energy(car: tco.TcoCar, r: tco.TcoRates) -> tco.TcoItem:
    return next(i for i in tco.compute(car, r, 18000).items if i.kind == "ENERGY")


def test_prices_have_dates_and_sources():
    r = rates()
    assert r.fuel_eur_per_l == 1.78 and r.diesel_eur_per_l == 1.89  # sourced, not the old 1.60 / 1.50
    lines = " ".join(energy(tco.TcoCar("a", "Ateca", "ICE", "petrol", consumption=6.3), r).inputs)
    assert "sourced, 2026-10-10" in lines


def test_bev_costs_far_more_without_home_charging_than_at_night():
    night = energy(bev("YES"), rates(night_tariff=True))
    street = energy(bev("NO"), rates())
    assert street.annual_eur > 3 * night.annual_eur
    assert any("night tariff" in i for i in night.inputs) and any("no home charging" in i for i in street.inputs)


def test_user_price_and_free_work_charging():
    mine = energy(bev("YES"), rates(home_electricity_eur_per_kwh=0.12))
    assert any("your price" in i for i in mine.inputs)
    free = energy(bev("WORK"), rates(home_electricity_eur_per_kwh=0.0))
    assert free.annual_eur < mine.annual_eur


def test_outdated_price_is_labelled():
    lines = " ".join(energy(tco.TcoCar("a", "Ateca", "ICE", "petrol", consumption=6.3), rates("2027-03-01")).inputs)
    assert "outdated" in lines


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("у меня гараж с розеткой", "YES"),
        ("нет гаража, паркуюсь на улице", "NO"),
        ("tengo plaza de garaje", "YES"),
        ("no tengo garaje", "NO"),
        ("I can charge at work", "WORK"),
        ("I have a wallbox", "YES"),
        ("хочу семейный кроссовер", None),
    ],
)
def test_charging_from_words(text, want):
    got = understanding.charging_of(text)
    assert (got[0] if got else None) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("плачу 12 центов за кВт·ч ночью", (0.12, True)),
        ("pago 0,09 €/kWh en valle", (0.09, True)),
        ("electricity is 0.21 EUR per kWh", (0.21, False)),
        ("cargo gratis en el trabajo", (0.0, False)),
        ("плачу 12 евро за кВт·ч", None),  # a unit error, not a price
        ("бюджет 30 тысяч евро", None),
    ],
)
def test_electricity_price_from_words(text, want):
    assert understanding.electricity_price_of(text) == want


def test_home_charging_asked_only_when_it_flips_the_winner():
    case = CaseFile()

    def flips(c: CaseFile):
        return ("bev" if c.profile.home_charging in ("YES", "UNKNOWN") else "ice", False)

    def same(c: CaseFile):
        return ("ice", False)

    probes = {"home_charging": ["YES", "NO"]}
    assert ask_value.questions(case, flips, probes) == ["HOME_CHARGING"]
    assert ask_value.questions(case, same, probes) == []
    asked = case.model_copy(update={"asked": ["HOME_CHARGING"]})
    assert ask_value.questions(asked, flips, probes) == []
    stated = case.model_copy(update={"basis": {"home_charging": "STATED"}})
    assert ask_value.questions(stated, flips, probes) == []
