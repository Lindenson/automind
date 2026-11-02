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
