"""Spec 010 US6 (T055, T056): capability score, decay and blame. Pure."""

from __future__ import annotations

import math

from automind.acquisition.registry.domain.blame import blame
from automind.acquisition.registry.domain.score import Counts, decay, score_of, wilson_lb

CFG = {"half_life_days": 90, "wilson_z": 1.96, "cost_lambda": 2.0,
       "priors": {"MANUFACTURER": [4.0, 0.5], "PUBLICATION": [2.0, 1.0], "OTHER": [1.0, 1.0]}}  # fmt: skip


def test_wilson_lower_bound_grows_with_sample_size():
    assert wilson_lb(3, 0) < wilson_lb(30, 0) < 1
    assert wilson_lb(2, 1) < wilson_lb(20, 10)  # same mean, more evidence ranks higher
    assert wilson_lb(0, 0) == 0.0


def test_decay_halves_at_half_life():
    assert math.isclose(decay(10.0, 90, 90), 5.0)
    assert decay(10.0, 0, 90) == 10.0


def test_score_prefers_proven_sources_and_priors_matter():
    few = score_of(Counts(attempts=3, accepted=3, right_w=2, wrong_w=0), "PUBLICATION", CFG)
    many = score_of(Counts(attempts=30, accepted=24, right_w=20, wrong_w=1), "PUBLICATION", CFG)
    assert many.score > few.score and many.acc_lb > few.acc_lb
    maker = score_of(Counts(), "MANUFACTURER", CFG)
    forum = score_of(Counts(), "OTHER", CFG)
    assert maker.acc_lb > forum.acc_lb
    costly = score_of(Counts(attempts=30, accepted=24, right_w=20, wrong_w=1, cost_eur=3.0), "PUBLICATION", CFG)
    assert costly.score < many.score


def test_wrong_signals_lower_accuracy():
    good = score_of(Counts(attempts=10, accepted=8, right_w=5, wrong_w=0), "PUBLICATION", CFG)
    bad = score_of(Counts(attempts=10, accepted=8, right_w=5, wrong_w=4), "PUBLICATION", CFG)
    assert bad.acc_mean < good.acc_mean and bad.score < good.score


def test_blame_goes_to_our_processing_when_the_page_has_the_right_number():
    assert blame("150 kW", "Leistung: 150 kW (204 PS)", "READER") == "parser"
    assert blame("150", "Potencia 150 kW", "LLM") == "extractor"
    assert blame("150", "Potencia 110 kW", "LLM") == "source"
    assert blame(None, "anything", "LLM") == "source"
    assert blame("1.598", "cilindrada 1598 cc", "LLM") == "extractor"
