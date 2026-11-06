"""Validation gaps from the review (spec 007 FR-030..FR-034, SC-009), each with the review's own example."""

import pytest

from automind.chat.application.services.report.contracts import CheckInput
from automind.chat.dialog.guard import check_numbers, numbers_in, report_violations
from automind.shared import evidence
from automind.shared.evidence import ClaimIn

GOLF_PAGE = "Golf 1.0 TSI 110 CV, ficha técnica. " + "Texto de relleno sin cifras. " * 220 + "Peso: 1.500 kg."


def test_fr030_an_ellipsis_never_skips_half_a_page():
    assert len(GOLF_PAGE) > 6000
    assert not evidence.validate_excerpt("Golf 1.0 TSI ... 1.500 kg", "1.500 kg", GOLF_PAGE)
    near = "Golf 1.0 TSI 110 CV, ficha técnica. Peso en orden de marcha: 1.500 kg."
    assert evidence.validate_excerpt("Golf 1.0 TSI ... 1.500 kg", "1.500 kg", near)


@pytest.mark.parametrize(("value", "excerpt", "ok"), [
    ("150", "par máximo a 1500 rpm", False),
    ("150", "potencia 150 CV a 5000 rpm", True),
    ("1,5", "consumo 11,5 l/100 km", False),
    ("1,5", "motor 1,5 litros", True),
    ("110 CV", "Golf 1.0 TSI 110 CV", True),
])  # fmt: skip
def test_fr031_numbers_match_whole(value, excerpt, ok):
    assert evidence.validate_excerpt(excerpt, value, excerpt) is ok


def _c(i, v, dom, attr):
    return ClaimIn(str(i), attr, v, "PUBLICATION", dom)


@pytest.mark.parametrize(("attr", "a", "b", "agree"), [
    ("transmission", "DSG 7 velocidades", "manual de 6 velocidades", False),
    ("transmission", "automatic", "DSG", True),
    ("drivetrain", "4x4", "AWD", True),
    ("drivetrain", "FWD", "tracción delantera", True),
    ("drivetrain", "FWD", "AWD", False),
    ("engine", "2.0 TDI diesel", "2.0 TSI gasolina", False),
    ("engine", "2.0 TDI", "2.0 diesel 150 CV", True),
])  # fmt: skip
def test_fr032_text_values_are_compared(attr, a, b, agree):
    s = evidence.select_value(attr, [_c(1, a, "a.com", attr), _c(2, b, "b.com", attr)])
    assert s.conflict is not agree


@pytest.mark.parametrize("sentence", ["Расход 10 л/100 км, гарантия 7 лет.", "2019 год, 5 звёзд NCAP."])
def test_fr033_small_numbers_and_years_need_the_facts(sentence):
    text, dropped = check_numbers(sentence, numbers_in({"consumption": 6.7, "price": 45545}), cars=2)
    assert dropped == 1 and text == ""
    kept, dropped = check_numbers(sentence, numbers_in({"c": 10, "w": 7, "y": 2019, "n": 5}), cars=2)
    assert dropped == 0 and kept == sentence


def test_fr033_car_count_and_list_numbers_are_not_figures():
    text, dropped = check_numbers("1. Обе 2 машины семейные.\n2. Honda тише.", set(), cars=2)
    assert dropped == 0 and text.startswith("1. Обе 2 машины")


CI = CheckInput(has_data=frozenset({"price"}), ties=frozenset({"official_price_es", "boot_volume"}), tie=False,
                car_names=("Golf", "León"))  # fmt: skip


def test_fr034_words_match_at_boundaries():
    assert not report_violations("Además, el precio del Golf es razonable.", CI)
    assert not report_violations("Moreover, the boot of the Golf is practical.", CI)
    assert [v.rule for v in report_violations("El maletero del Golf es más grande.", CI)] == ["sub_threshold"]
    assert [v.rule for v in report_violations("The Golf has more boot space.", CI)] == ["sub_threshold"]
    assert [v.rule for v in report_violations("Багажник у Golf вместительнее.", CI)] == ["sub_threshold"]


def test_fr031_a_price_with_thousands_and_cents_is_one_number():
    assert evidence.validate_excerpt("Style | 28.810,00 €", "28.810,00", "1.5 EcoTSI DSG-7 Style | 28.810,00 €")
    assert evidence.validate_excerpt("44.250,00 €", "44.250,00", "Precio: 44.250,00 €")
