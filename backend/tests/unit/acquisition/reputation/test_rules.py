"""The reputation's pure rules: the components' fading weights, the roll-up's rows and KPIs, and the signal rules
over a version's facts (gold right/wrong, fusion, agreement once per family, replacement never disputed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from automind.acquisition.reputation.domain import findings
from automind.acquisition.reputation.domain.components import Weights, credited, faded, mean_lb_by_kind
from automind.acquisition.reputation.domain.rollup import (
    ANY_MARKET,
    AreaTotals,
    AttemptCounts,
    SearchCounts,
    SignalCounts,
    daily_rows,
    kpis_of,
)
from automind.acquisition.reputation.domain.signal_facts import ClaimFact, GoldFact, SelectedValue, VariantFacts

T0 = datetime(2026, 11, 1, tzinfo=UTC)
TOLS = {"max_power": ("rel", 0.02), "curb_mass": ("rel", 0.02)}


def _claim(cid: str, value: float, domain: str, family: str, minutes: int = 0) -> ClaimFact:
    return ClaimFact(cid, "max_power", value, "specs", domain, family, T0 + timedelta(minutes=minutes))


def _facts(claims: list[ClaimFact], selected: float | None = None, gold: float | None = None,
           done: frozenset[tuple[str | None, str]] = frozenset()) -> VariantFacts:  # fmt: skip
    behind = tuple(c.id for c in claims if c.value_num == selected)
    sel = {} if selected is None else {"max_power": SelectedValue("max_power", selected, None, True, "HIGH", behind)}
    g = {} if gold is None else {"max_power": GoldFact("g1", gold, None, "exact", "HIGH")}
    return VariantFacts("v1", "petrol", "ICE", None, tuple(claims), sel, g, done=done)


def test_weights_fade_with_the_half_life_and_credit_after_fading() -> None:
    w = Weights(4.0, 2.0, T0)
    f = faded(w, T0 + timedelta(days=30), half_life_days=30)
    assert (f.right_w, f.wrong_w) == pytest.approx((2.0, 1.0))
    c = credited(w, "wrong", 1.0, T0 + timedelta(days=30), half_life_days=30)
    assert (c.right_w, c.wrong_w) == pytest.approx((2.0, 2.0)) and c.acc_lb < f.acc_lb
    assert mean_lb_by_kind([("parser", Weights(1, 0, T0, 0.8)), ("parser", Weights(3, 0, T0, 0.4))]) == {
        "parser": pytest.approx(0.5)}  # fmt: skip


def test_daily_rows_put_searches_under_any_market_and_kpis_skip_areas_without_values() -> None:
    rows = daily_rows([AttemptCounts("specs", "ES", 5, 20, 0, 0.1, 0.05)], [SearchCounts("specs", 10, 0.2)],
                      [SignalCounts("specs", "ES", 2, 3, 2)])  # fmt: skip
    assert rows[("specs", ANY_MARKET)]["searches"] == 10 and rows[("specs", "ES")]["wrong_values"] == 2
    assert rows[("specs", "ES")]["cost_eur"] == pytest.approx(0.1)
    k = kpis_of([AreaTotals("specs", 10, 20, 2), AreaTotals("price", 5, 0, 0)])
    assert k == {"searches_per_value": {"specs": 0.5}, "wrong_share": {"specs": 0.1}}


def test_gold_right_and_wrong_and_what_was_signalled_is_skipped() -> None:
    claims = [_claim("c1", 150, "a.com", "a"), _claim("c2", 190, "b.com", "b")]
    found = findings.gold_findings(_facts(claims, gold=150), TOLS)
    assert [(x.claim.id if x.claim else None, x.verdict, x.counter) for x in found] == [
        ("c1", "right", "gold_right"), ("c2", "wrong", "gold_wrong")]  # fmt: skip
    assert found[1].blame is not None and found[1].blame.truth == 150
    assert (
        findings.gold_findings(_facts(claims, gold=150, done=frozenset({("c2", "gold")})), TOLS)[-1].claim == claims[0]
    )


def test_fusion_when_the_selection_is_wrong_though_a_claim_was_right() -> None:
    claims = [_claim("c1", 150, "a.com", "a"), _claim("c2", 190, "b.com", "b")]
    (x,) = findings.fusion_findings(_facts(claims, selected=190, gold=150), TOLS)
    assert (x.kind, x.verdict, x.counter, x.domain, x.fixed_blame) == (
        "gold", "wrong", "fusion", "a.com", ({"fusion": 1.0}, {"fusion": "merge@1"}))  # fmt: skip


def test_agreement_once_per_family() -> None:
    claims = [_claim("c1", 150, "a.com", "a"), _claim("c2", 150.5, "b.com", "b"), _claim("c3", 150, "a2.com", "a")]
    found = findings.agreement_findings(_facts(claims), TOLS)
    assert sorted(x.details["family"] for x in found) == ["a", "b"]
    assert all(x.verdict == "right" and x.counter == "agreement" for x in found)
