"""Turn cost estimate before research (FR-041, R12): deterministic and monotonic."""

import pytest

from automind.domain.cost import AreaAverage, CostPrices, estimate

PRICES = CostPrices(eur_per_m_in=2.3, eur_per_m_out=13.8, eur_per_search=0.0148)
AVG = {"specs": AreaAverage(llm_in=20_000, llm_out=1_500, searches=3)}
DEFAULT = AreaAverage(llm_in=10_000, llm_out=800, searches=2)


def test_formula():
    eur = estimate([("v1", "specs")], rounds=0, averages=AVG, default=DEFAULT, prices=PRICES)
    expected = (20_000 * 2.3 + 1_500 * 13.8) / 1e6 + 3 * 0.0148
    assert eur == pytest.approx(expected, abs=1e-4)


def test_unknown_area_uses_default_average():
    a = estimate([("v1", "reviews")], rounds=0, averages=AVG, default=DEFAULT, prices=PRICES)
    b = estimate([("v1", "reviews")], rounds=0, averages={}, default=DEFAULT, prices=PRICES)
    assert a == b > 0


def test_monotonic_in_cars_areas_and_depth():
    one = [("v1", "specs")]
    two = [("v1", "specs"), ("v2", "specs")]
    more = [*two, ("v1", "reviews")]
    e = lambda jobs, r: estimate(jobs, rounds=r, averages=AVG, default=DEFAULT, prices=PRICES)  # noqa: E731
    assert e(one, 0) < e(two, 0) < e(more, 0)
    assert e(two, 0) < e(two, 1) < e(two, 2)
    assert e([], 2) == 0
