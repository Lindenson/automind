"""Reliability and reviews of a car from its stored issues and review items (severity rules from
config/severity.yaml, installed at startup), and how complete its engineering data is."""

from __future__ import annotations

from automind.chat.application.services.report.contracts import LoadedCar
from automind.chat.domain.assessment import reliability, reviews
from automind.chat.domain.assessment.metrics import ReliabilitySummary, ReviewSummary
from automind.shared.vehicle import specs

ENGINEERING_ATTRS = [k for k, a in specs.ATTRS.items() if a.category == "engineering"]


def configure_severity(rules: reliability.SeverityRules) -> None:
    """Install the severity rules of issues (config/severity.yaml; delivery.bootstrap.configure_domain)."""
    _SEVERITY[:] = [rules]


def severity_rules() -> reliability.SeverityRules:
    """The severity rules installed at startup (`configure_severity`)."""
    return _SEVERITY[0]


def merged_issues(car: LoadedCar) -> list[reliability.MergedIssue]:
    """The car's sourced issues merged across sources, with their severity (config/severity.yaml)."""
    items = [
        reliability.IssueIn(
            component=i.component,
            description=i.description,
            domain=e.domain,
            severity_hint=i.severity_hint,
            age_from=i.age_from,
            age_to=i.age_to,
            mileage_from=i.mileage_from,
            mileage_to=i.mileage_to,
            evidence_id=e.id,
        )
        for i, e in car.get("issues", [])
    ]
    return reliability.merge_issues(items, severity_rules())


def reliability_summary(car: LoadedCar) -> ReliabilitySummary | None:
    """The reliability summary of the car, None when reliability was never researched."""
    run = car.get("runs", {}).get("reliability")
    if run is None:
        return None
    return reliability.summarize(merged_issues(car), minimum_met=bool(run.minimum_met))


def review_items(car: LoadedCar) -> list[reviews.ReviewIn]:
    """The car's sourced review points as the review summary reads them."""
    return [
        reviews.ReviewIn(
            tag=r.tag, polarity=r.polarity, text=r.text, domain=e.domain, reviewer=r.reviewer, evidence_id=e.id
        )
        for r, e in car.get("reviews", [])
    ]


def review_summary(car: LoadedCar) -> ReviewSummary | None:
    """The review summary of the car, None when reviews were never researched."""
    if car.get("runs", {}).get("reviews") is None:
        return None
    return reviews.summarize_reviews(review_items(car))


def engineering_completeness(car: LoadedCar) -> float | None:
    """The share of engineering facts known (0–1), None when engineering was never researched."""
    if "engineering" not in car.get("runs", {}):
        return None
    vals = car["values"]
    return sum(1 for k in ENGINEERING_ATTRS if vals.get(k) is not None and vals[k].available) / len(ENGINEERING_ATTRS)


_SEVERITY: list[reliability.SeverityRules] = []  # config/severity.yaml, installed at startup
