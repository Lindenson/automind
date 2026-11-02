"""Persona block order (FR-030, contracts/chat-protocol.md)."""

import pytest

from automind.domain.report_layout import ORDER, order_blocks

ALL = [
    "sources",
    "race_chart",
    "tco",
    "spec_table",
    "engineering",
    "criteria_scores",
    "reliability",
    "metric_bars",
    "reviews",
    "manufacturer",
    "case_summary",
]


def blocks(*types):
    return [{"type": t} for t in types]


@pytest.mark.parametrize(
    ("persona", "expected"),
    [
        ("BUYER", ["case_summary", "criteria_scores", "tco", "reliability", "reviews", "spec_table", "sources"]),
        (
            "PERFORMANCE",
            [
                "case_summary",
                "race_chart",
                "metric_bars",
                "criteria_scores",
                "spec_table",
                "reliability",
                "tco",
                "sources",
            ],
        ),
        (
            "EXPERT",
            [
                "case_summary",
                "engineering",
                "spec_table",
                "metric_bars",
                "criteria_scores",
                "reliability",
                "manufacturer",
                "tco",
                "race_chart",
                "sources",
            ],
        ),
        ("UNKNOWN", ["case_summary", "criteria_scores", "spec_table", "tco", "reliability", "race_chart", "sources"]),
    ],
)
def test_exact_orders(persona, expected):
    assert ORDER[persona] == expected
    got = [b["type"] for b in order_blocks(persona, blocks(*ALL), cars=2)]
    assert got == expected


def test_warning_notices_first_info_notices_last():
    out = order_blocks(
        "BUYER",
        [
            {"type": "notice", "level": "info", "text": "i"},
            {"type": "tco"},
            {"type": "notice", "level": "warning", "text": "w"},
        ],
        cars=2,
    )
    assert [b.get("level", b["type"]) for b in out] == ["warning", "tco", "info"]


def test_single_car_profile_has_no_race_and_no_winner():
    out = order_blocks(
        "PERFORMANCE",
        [{"type": "race_chart"}, {"type": "criteria_scores", "winner_car_id": "x"}, {"type": "spec_table"}],
        cars=1,
    )
    assert [b["type"] for b in out] == ["criteria_scores", "spec_table"]
    assert out[0]["winner_car_id"] is None


def test_unknown_block_types_are_kept_at_the_end():
    assert [b["type"] for b in order_blocks("BUYER", blocks("future_block", "tco"), cars=2)] == ["tco", "future_block"]
