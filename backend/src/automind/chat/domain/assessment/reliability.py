"""Known technical issues: merge, recurrence, severity, used-car emphasis (FR-036; research R8). Pure.

"Recurring" needs ≥2 independent sources (domains). Severity comes from versioned keyword rules
(config/severity.yaml), never from a model. Subjective opinions are not issues.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from automind.chat.domain.assessment.metrics import ReliabilitySummary

Severity = Literal["LOW", "MEDIUM", "HIGH"]
SUBJECTIVE = ("boring", "ugly", "design", "looks", "styling", "bland", "character", "dull", "fun to drive", "opinion")


@dataclass(frozen=True)
class SeverityRules:
    high: tuple[str, ...]
    medium: tuple[str, ...]
    low: tuple[str, ...]

    @classmethod
    def from_config(cls, d: Mapping[str, Any]) -> SeverityRules:
        return cls(tuple(d.get("HIGH", [])), tuple(d.get("MEDIUM", [])), tuple(d.get("LOW", [])))

    def severity(self, component: str, description: str, hint: str) -> Severity:
        text = f"{component} {description} {hint}".lower()
        if any(k in text for k in self.high):
            return "HIGH"
        if any(k in text for k in self.medium):
            return "MEDIUM"
        return "LOW"


@dataclass(frozen=True)
class IssueIn:
    component: str
    description: str
    domain: str
    severity_hint: str = ""
    age_from: int | None = None
    age_to: int | None = None
    mileage_from: int | None = None
    mileage_to: int | None = None
    evidence_id: str = ""


@dataclass(frozen=True)
class MergedIssue:
    component: str
    description: str
    recurrence: Literal["RECURRING", "ISOLATED"]
    severity: Severity
    age_from: int | None
    age_to: int | None
    domains: tuple[str, ...]
    evidence_ids: list[str] = field(default_factory=list)

    @property
    def age_window(self) -> str | None:
        if self.age_from is None and self.age_to is None:
            return None
        return f"{self.age_from or 0}–{self.age_to if self.age_to is not None else ''} years".replace(
            "– years", "+ years"
        )


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def is_subjective(i: IssueIn) -> bool:
    return any(w in _norm(i.component) for w in SUBJECTIVE)


_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def merge_issues(items: list[IssueIn], rules: SeverityRules) -> list[MergedIssue]:
    """Group the same component (one name contained in the other) across sources."""
    groups: list[list[IssueIn]] = []
    for it in sorted((x for x in items if not is_subjective(x)), key=lambda x: len(_norm(x.component))):
        key = _norm(it.component)
        for g in groups:
            gk = _norm(g[0].component)
            if gk in key or key in gk:
                g.append(it)
                break
        else:
            groups.append([it])
    out = []
    for g in groups:
        domains = tuple(sorted({x.domain for x in g}))
        sev = max((rules.severity(x.component, x.description, x.severity_hint) for x in g), key=lambda s: _RANK[s])
        froms = [x.age_from for x in g if x.age_from is not None]
        tos = [x.age_to for x in g if x.age_to is not None]
        first_per_domain = {x.domain: x.evidence_id for x in reversed(g)}
        out.append(
            MergedIssue(
                component=g[0].component.strip(),
                description=g[0].description,
                recurrence="RECURRING" if len(domains) >= 2 else "ISOLATED",
                severity=sev,
                age_from=min(froms) if froms else None,
                age_to=max(tos) if tos else None,
                domains=domains,
                evidence_ids=[first_per_domain[d] for d in domains if first_per_domain[d]],
            )
        )
    return out


def summarize(merged: list[MergedIssue], *, minimum_met: bool) -> ReliabilitySummary:
    return ReliabilitySummary(
        minimum_met=minimum_met,
        recurring=sum(1 for m in merged if m.recurrence == "RECURRING"),
        isolated=sum(1 for m in merged if m.recurrence == "ISOLATED"),
        high=sum(1 for m in merged if m.severity == "HIGH"),
    )


def order_for_age(merged: list[MergedIssue], age_years: int | None, horizon: int = 5) -> list[MergedIssue]:
    """Used cars: issues whose age window overlaps the coming years first; then recurring, then severity."""

    def relevant(m: MergedIssue) -> bool:
        if age_years is None or m.age_from is None:
            return False
        hi = m.age_to if m.age_to is not None else m.age_from
        return hi >= age_years - 1 and m.age_from <= age_years + horizon

    return sorted(
        merged,
        key=lambda m: (not relevant(m), m.recurrence != "RECURRING", -_RANK[m.severity], m.component.lower()),
    )
