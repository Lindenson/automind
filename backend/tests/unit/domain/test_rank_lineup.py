"""Spec 005 R12 (FR-008): 1–3 models of a make that fit the person, with machine reasons. Deterministic."""

from automind.domain.intake import Fit, LineupModel, rank_lineup

BYD = [
    LineupModel("Dolphin", "hatchback", ("bev",), 29990),
    LineupModel("Atto 3", "suv", ("bev",), 37990),
    LineupModel("Seal U DM-i", "suv", ("phev",), 35990),
    LineupModel("Seal", "sedan", ("bev",), 46990),
    LineupModel("Sealion 7", "suv", ("bev",), 49990),
]


def test_family_and_high_km_prefer_suvs_with_low_running_cost() -> None:
    fit = Fit(family=True, annual_km=18000, priorities=("efficiency", "ownership_cost"), reference_price_eur=32000)
    top = rank_lineup(BYD, fit)
    assert [m.model for m, _ in top] == ["Seal U DM-i", "Atto 3", "Sealion 7"]
    assert top[0][1] == ["family_body", "phev_low_running_cost", "price_close"]
    assert "family_body" in top[1][1] and "bev_low_running_cost" in top[1][1]


def test_deterministic_and_bounded() -> None:
    fit = Fit(family=True, annual_km=18000)
    assert rank_lineup(BYD, fit) == rank_lineup(list(reversed(BYD)), fit)
    assert len(rank_lineup(BYD, fit, limit=2)) == 2


def test_far_above_the_budget_is_dropped() -> None:
    top = rank_lineup(BYD, Fit(family=True, budget_eur=25000))
    assert "Sealion 7" not in [m.model for m, _ in top]
