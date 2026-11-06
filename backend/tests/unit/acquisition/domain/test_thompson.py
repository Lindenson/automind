"""Spec 011 T062: Thompson sampling for exploration (research R7). Pure."""

from __future__ import annotations

from automind.acquisition.domain.thompson import Arm, explore, seed_of

SURE = Arm("sure.example", "candidate", right_w=28, wrong_w=2, prior_r=2, prior_w=1, accepted=50, attempts=50)
UNSURE = Arm("unsure.example", "candidate", right_w=1, wrong_w=2, prior_r=2, prior_w=1, accepted=50, attempts=50)


def test_same_seed_same_order() -> None:
    arms = [SURE, UNSURE, Arm("third.example", "candidate", 3, 3, 2, 1, 10, 20)]
    s = seed_of("job-1", "specs")
    assert s == seed_of("job-1", "specs") and s != seed_of("job-2", "specs")
    assert explore(arms, s, slots=3, budget_eur=1.0) == explore(list(reversed(arms)), s, slots=3, budget_eur=1.0)


def test_the_certain_good_source_wins_most_but_the_uncertain_one_gets_some_slots() -> None:
    picks = [explore([SURE, UNSURE], seed, slots=1, budget_eur=1.0)[0].domain for seed in range(10_000)]
    share = picks.count("unsure.example") / len(picks)
    assert 0.001 < share < 0.15


def test_budget_stops_exploration() -> None:
    priced = [Arm(a.domain, a.status, a.right_w, a.wrong_w, a.prior_r, a.prior_w, a.accepted, a.attempts,
                  cost_per_attempt=0.04) for a in (SURE, UNSURE)]  # fmt: skip
    assert explore(priced, 7, slots=2, budget_eur=0.0) == []
    assert len(explore(priced, 7, slots=2, budget_eur=0.05)) == 1  # the second slot would overspend
    assert len(explore(priced, 7, slots=2, budget_eur=0.10)) == 2


def test_blocked_and_denied_are_never_sampled() -> None:
    arms = [
        Arm("blocked.example", "blocked", 30, 0, 2, 1, 50, 50),
        Arm("terms.example", "candidate", 30, 0, 2, 1, 50, 50, access="terms_forbid"),
        Arm("coches.net", "candidate", 30, 0, 2, 1, 50, 50),
        UNSURE,
    ]
    for seed in range(200):
        assert [a.domain for a in explore(arms, seed, slots=4, budget_eur=1.0, deny=("coches.net",))] == [
            "unsure.example"
        ]
