"""Spec 009 FR-014 / chat fcf5b3b8: a PHEV without a charge-sustaining figure gets an estimate, labelled."""

from automind.chat.domain.cost.energy import estimate_cs, utility_factor


def test_sorento_phev_estimate_is_realistic():
    assert 0.78 < utility_factor(57) < 0.80
    assert 7.0 < (estimate_cs(1.6, 57) or 0) < 8.0  # Kia Sorento PHEV: 1.6 l/100 km weighted, 57 km


def test_no_estimate_when_unsupported():
    assert estimate_cs(None, 57) is None and estimate_cs(1.6, None) is None
    assert estimate_cs(0.8, 100) is None  # long range: the inverse is too sensitive
    assert estimate_cs(0.3, 20) is None  # implausible result
