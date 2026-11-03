# ruff: noqa: E501
"""Spec 005 R13: intake metrics (SC-002, SC-003, SC-004)."""

from automind.domain.metrics import intake_summary


def test_intake_summary() -> None:
    ev = [
        ("a", "ASKED", {}), ("a", "ANSWERED", {}), ("a", "ASKED", {"repeat": True}), ("a", "ANSWERED", {}),
        ("a", "CONFIRMED", {}), ("a", "RESEARCH_STARTED", {"all_confirmed": True}),
        ("b", "CONFIRMED", {}), ("b", "CORRECTED", {}),
        ("c", "ANSWERED", {}), ("c", "ANSWERED", {}), ("c", "ANSWERED", {}), ("c", "ANSWERED", {}), ("c", "CONFIRMED", {}),
        ("d", "RESEARCH_STARTED", {"all_confirmed": False}),
    ]  # fmt: skip
    s = intake_summary(ev)
    assert s["chats_confirmed"] == 3 and s["replies_to_confirmed_median"] == 2
    assert s["confirmed_within_3"] == round(2 / 3, 3)
    assert (s["repeated_questions"], s["corrections"], s["research_unconfirmed"]) == (1, 1, 1)
