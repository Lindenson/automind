"""The battery and CLTC range for the EREV kWh/100 km estimate come from one page (chat 2026-11-06)."""

from types import SimpleNamespace as NS

from automind.chat.application.services.report.facts.car import cltc_pair


def _row(attr: str, value: float, url: str) -> tuple[NS, NS]:
    return NS(attribute=attr, value_num=value), NS(url=url)


def test_pair_only_from_one_page_the_selected_range_first():
    rows = [
        _row("battery_kwh", 53.49, "a"),  # the larger-battery version, no range on its page
        _row("battery_kwh", 40.18, "b"),
        _row("range_cltc", 220, "b"),
        _row("battery_kwh", 60, "c"),
        _row("range_cltc", 300, "c"),
    ]
    assert cltc_pair(rows, NS(value_num=220, available=True)) == (40.18, 220, "b")
    assert cltc_pair(rows, NS(value_num=300, available=True)) == (60, 300, "c")


def test_no_pair_across_pages():
    rows = [_row("battery_kwh", 42.8, "x"), _row("range_cltc", 420, "y")]
    assert cltc_pair(rows, None) is None
