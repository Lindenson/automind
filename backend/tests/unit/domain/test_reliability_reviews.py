"""Reliability issues and review summaries (FR-036, FR-037; research R8)."""

from pathlib import Path

import yaml

from automind.chat.domain.assessment.reliability import IssueIn, SeverityRules, merge_issues, summarize
from automind.chat.domain.assessment.reviews import ReviewIn, summarize_reviews

RULES = SeverityRules.from_config(yaml.safe_load((Path(__file__).parents[3] / "config" / "severity.yaml").read_text()))


def issue(component, domain, desc="", hint="", age=(None, None)):
    return IssueIn(
        component=component,
        description=desc or component,
        domain=domain,
        severity_hint=hint,
        age_from=age[0],
        age_to=age[1],
        evidence_id=f"e-{domain}",
    )


def test_recurring_requires_two_independent_sources():
    merged = merge_issues(
        [
            issue("DPF", "a.com"),
            issue("dpf ", "a.com"),
            issue("Timing chain", "b.com"),
            issue("timing chain stretch", "c.com"),
        ],
        RULES,
    )
    by = {m.component.lower(): m for m in merged}
    assert by["dpf"].recurrence == "ISOLATED"  # same domain twice is one source
    assert by["timing chain"].recurrence == "RECURRING" and len(by["timing chain"].evidence_ids) == 2


def test_severity_from_keyword_rules():
    assert RULES.severity("Timing chain", "stretches at 120,000 km", "") == "HIGH"
    assert RULES.severity("DPF", "clogs on short trips", "") == "MEDIUM"
    assert RULES.severity("Infotainment", "screen freezes", "") == "LOW"
    assert RULES.severity("Unknown part", "something", "can lead to engine failure") == "HIGH"


def test_summary_counts_and_none_found():
    merged = merge_issues(
        [issue("Timing chain", "a.com"), issue("timing chain", "b.com"), issue("DPF", "c.com")], RULES
    )
    s = summarize(merged, minimum_met=True)
    assert (s.recurring, s.isolated, s.high) == (1, 1, 1)
    empty = summarize([], minimum_met=True)
    assert empty.recurring == 0 and empty.isolated == 0  # "no documented issues found", not "none"


def test_used_car_emphasis_orders_issues_by_age_window():
    merged = merge_issues([issue("Paint", "a.com", age=(2, 4)), issue("Rust", "b.com", age=(9, 14))], RULES)
    from automind.chat.domain.assessment.reliability import order_for_age

    assert [m.component for m in order_for_age(merged, age_years=10)][0] == "Rust"


def test_subjective_opinions_are_never_issues():
    merged = merge_issues(
        [issue("boring to drive", "a.com"), issue("ugly design", "b.com"), issue("EGR valve", "c.com")], RULES
    )
    assert [m.component for m in merged] == ["EGR valve"]


def review(tag, pol, domain, text="x"):
    return ReviewIn(tag=tag, polarity=pol, text=text, domain=domain, reviewer="EXPERT", evidence_id=f"e-{domain}")


def test_review_minimum_and_recurring_points():
    items = [
        review("comfort", "CON", "a.com"),
        review("comfort", "CON", "b.com"),
        review("handling", "PRO", "a.com"),
        review("handling", "PRO", "a.com"),
        review("value", "PRO", "c.com"),
    ]
    s = summarize_reviews(items)
    assert s.minimum_met and s.review_count == 5 and s.source_count == 3
    assert s.recurring == {"comfort": (0, 2)} and s.isolated["handling"] == (2, 0)
    few = summarize_reviews(items[:4])
    assert not few.minimum_met
    one_source = summarize_reviews([review("comfort", "PRO", "a.com")] * 6)
    assert not one_source.minimum_met
