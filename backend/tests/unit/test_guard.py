"""Number guard (FR-031)."""

from automind.orchestration.guard import check_numbers, numbers_in


def test_unknown_figures_are_removed_and_counted():
    text, dropped = check_numbers("It has 180 kW. It weighs 1529 kg. Nice car.", numbers_in({"p": 180}))
    assert text == "It has 180 kW. Nice car." and dropped == 1


def test_model_codes_are_names_not_figures():
    text, dropped = check_numbers("Not the J250 but the Prado J150 3.0 D-4D, nor a Golf Mk8 or i30 N.", {3.0})
    assert dropped == 0 and "J250" in text


def test_units_glued_to_numbers_are_still_checked():
    _, dropped = check_numbers("0-100 in 4.9s.", set())
    assert dropped == 1


def test_thousands_as_written_in_ru_es_en():
    """Reviewer 2026-11-03: "25 000 €" was read as 25 and 000; "25.000" as 25.0."""
    allowed = numbers_in({"price": 25000, "tco": 2580.0, "acc": 6.58})
    for s in (
        "Цена 25 000 €.",
        "Cuesta 25.000 euros.",
        "It costs €25,000.",
        "Около 25k в год.",
        "Это 25 тыс.",
        "Gasto 2.580 € al año.",
        "Разгон за 6,58 с.",
    ):
        assert check_numbers(s, allowed) == (s, 0), s
    assert check_numbers("Cuesta 31.000 euros.", allowed)[1] == 1
    assert check_numbers("Цена 31 000 €.", allowed)[1] == 1


def test_numbers_in_formatted_block_strings():
    allowed = numbers_in({"text": "€36 075", "b": "1.430 kg", "c": "20к"})
    assert {36075.0, 1430.0, 20000.0} <= allowed
    assert 1.43 in allowed  # "1.430" may be English decimals too


def test_km_is_not_thousand():
    allowed = numbers_in({"d": 20})
    assert check_numbers("Хватит на 20 км.", allowed)[1] == 0


def test_language_hysteresis():
    from automind.orchestration.phrases import stable_language

    ru = ["Сравни BYD Seal U и Ateca", "семья, юг Испании"]
    assert stable_language("en", "Seal U DM-i", ru) == "ru"  # a model name does not switch the chat
    assert stable_language("en", "please answer in English from now on", ru) == "en"
    assert stable_language("es", "hola", []) == "es"
