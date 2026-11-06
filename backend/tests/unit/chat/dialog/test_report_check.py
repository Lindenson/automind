"""Report check: text vs blocks (spec 004 FR-012, SC-003; research R3)."""

from automind.chat.application.services.report.contracts import CheckInput
from automind.chat.dialog.guard import drop_sentences, report_violations, violations_prompt

CI = CheckInput(
    has_data=frozenset({"tco", "price", "consumption"}),
    ties=frozenset({"boot_volume"}),
    tie=True,
    car_names=("RAV4", "CX-5", "CR-V"),
)


def test_no_data_claim_next_to_a_block_with_data() -> None:
    """2026-11-02: "no ownership cost data" next to a TCO block."""
    v = report_violations("There is no data on ownership cost for these cars. The RAV4 is a hybrid.", CI)
    assert [x.rule for x in v] == ["absence"] and v[0].topic == "tco"
    ru = report_violations("По стоимости владения нет данных.", CI)
    assert ru and ru[0].rule == "absence"
    assert not report_violations("There is no data on reliability yet.", CI)  # really missing: allowed


def test_advantage_below_the_threshold() -> None:
    """ "Mazda wins on practicality": 583 L vs 580 L."""
    v = report_violations("The CX-5 has a bigger boot than the RAV4.", CI)
    assert v and v[0].rule == "sub_threshold" and v[0].topic == "boot_volume"
    assert report_violations("У Mazda багажник больше.", CI)[0].rule == "sub_threshold"
    assert not report_violations("The boots are about the same size.", CI)


def test_no_winner_in_a_tie() -> None:
    v = report_violations("The RAV4 is the best choice for you.", CI)
    assert v and v[0].rule == "tie_winner"
    calm = CheckInput(CI.has_data, CI.ties, False, CI.car_names)
    assert not report_violations("The RAV4 is the best choice for you.", calm)


def test_offending_sentences_are_removed_and_explained() -> None:
    text = "The CX-5 has a bigger boot. The RAV4 uses less fuel."
    v = report_violations(text, CI)
    assert drop_sentences(text, v) == "The RAV4 uses less fuel."
    assert "about the same" in violations_prompt(v)
