"""Make registry and transliteration (spec 005 R3, FR-010)."""

from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.vehicle.identity import transliterate_ru
from automind.shared.vehicle.makes import MakeRegistry

REG = MakeRegistry.from_config(load_yaml("makes.yaml"))


def test_transliterate_ru() -> None:
    assert transliterate_ru("атека") == "ateka"
    assert transliterate_ru("туссан") == "tussan"
    assert transliterate_ru("Seal U") == "Seal U"


def test_match_make_aliases_translit_fuzzy() -> None:
    assert REG.match_make("byd") == "BYD"
    assert REG.match_make("BYD это Build Your Dream, китайская") == "BYD"
    assert REG.match_make("сеат атека") == "SEAT"
    assert REG.match_make("хендай туссан") == "Hyundai"
    assert REG.match_make("биад сил ю") == "BYD"
    assert REG.match_make("шкода карок") == "Skoda"
    assert REG.match_make("Mercedez GLC") == "Mercedes-Benz"  # fuzzy
    assert REG.match_make("для семьи на юге") is None


def test_match_by_url_domain() -> None:
    assert REG.match_make("https://www.byd.com/ вот он!") == "BYD"
    assert REG.make_of_url("https://www.byd.com/es/coches/seal-u-dm-i") == "BYD"
    assert REG.make_of_url("https://www.km77.com/coches/seat/ateca") is None


def test_home_page() -> None:
    assert REG.is_home_page("https://www.byd.com/")
    assert REG.is_home_page("https://www.byd.com/es")
    assert not REG.is_home_page("https://www.byd.com/es/coches/seal-u-dm-i")


def test_make_site() -> None:
    assert REG.site("BYD") == "byd.com/es"
    assert REG.site("Unknown") is None


def test_model_translit_against_known() -> None:
    assert REG.match_model("атека", ["Ateca", "Arona", "Ibiza"]) == "Ateca"
    assert REG.match_model("туссан", ["Tucson", "Kona", "i30"]) == "Tucson"
    assert REG.match_model("сил ю", ["Seal", "Seal U", "Atto 3", "Dolphin"]) == "Seal U"
    assert REG.match_model("спортейдж", ["Sportage", "Ceed", "Niro"]) == "Sportage"
    assert REG.match_model("квадрат", ["Sportage", "Ceed"]) is None
