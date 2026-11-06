"""Spec 011 T064: agreement of independent families counts once per family (research R7, US3 AS-3). Pure."""

from __future__ import annotations

from automind.acquisition.domain.agreement import FamilyValue, agreements
from automind.acquisition.domain.replacement import Seen, replaced

TOL = ("rel", 0.02)


def fv(claim: str, domain: str, value: float, family: str | None = None) -> FamilyValue:
    return FamilyValue(claim, domain, family or domain, value)


def test_k_families_agree_one_signal_each() -> None:
    vals = [fv("a", "km77.com", 1615), fv("b", "honest.example", 1610), fv("c", "third.example", 1620),
            fv("d", "liar.example", 1450)]  # fmt: skip
    out = agreements(vals, TOL)
    assert sorted(a.family for a in out) == ["honest.example", "km77.com", "third.example"]
    assert all(a.families == 3 for a in out)


def test_mirrors_in_one_family_give_nothing_to_each_other() -> None:
    vals = [fv("a", "auto-data.net", 1615, "autodata"), fv("b", "ultimatespecs.com", 1615, "autodata")]
    assert agreements(vals, TOL) == []


def test_a_family_with_two_domains_counts_once() -> None:
    vals = [fv("a", "auto-data.net", 1615, "autodata"), fv("b", "ultimatespecs.com", 1612, "autodata"),
            fv("c", "km77.com", 1616)]  # fmt: skip
    out = agreements(vals, TOL)
    assert len(out) == 2 and sorted(a.family for a in out) == ["autodata", "km77.com"]
    assert next(a for a in out if a.family == "autodata").claim_id == "a"  # the closest member speaks for it


def test_two_equal_clusters_are_no_agreement() -> None:
    vals = [fv("a", "x.example", 100), fv("b", "y.example", 100), fv("c", "z.example", 120), fv("d", "w.example", 120)]
    assert agreements(vals, TOL) == []


def test_replacement_of_a_value_that_was_shown_alone() -> None:
    hist = [Seen("old", "liar.example", 1450.0, 1), Seen("new", "honest.example", 1615.0, 2)]
    assert [r.claim_id for r in replaced(hist, selected_ids={"new"}, selected=1615.0, tol=TOL)] == ["old"]
    # the old value agrees with the new selection: nothing was replaced
    assert replaced([Seen("old", "a", 1612.0, 1), Seen("new", "b", 1615.0, 2)], {"new"}, 1615.0, TOL) == []
    # never shown alone (another claim existed before the selected one): not a replacement
    hist3 = [Seen("x", "a", 1615.0, 0), Seen("old", "liar.example", 1450.0, 1), Seen("new", "b", 1615.0, 2)]
    assert replaced(hist3, {"x", "new"}, 1615.0, TOL) == []
