"""Block reliability: the merged issues of each car, ordered for its age."""

from __future__ import annotations

from automind.chat.application.services.report.contracts import LoadedCar
from automind.chat.application.services.report.facts.car import evidence_sources
from automind.chat.application.services.report.facts.quality import merged_issues
from automind.chat.domain.assessment import reliability
from automind.shared.contracts.json import JsonObject


def reliability_block(cars: list[LoadedCar], ages: dict[str, int | None]) -> JsonObject | None:
    """The reliability block: per researched car its issues merged and ordered for its age, and the sourced
    statistics; None when no car was researched for reliability."""
    out = []
    for c in cars:
        v = c["variant"]
        run = c.get("runs", {}).get("reliability")
        if run is None:
            continue
        merged = reliability.order_for_age(merged_issues(c), ages.get(v.id))
        stats = []
        for st in c.get("stats", []):
            stats.append({"source": st.source, "metric": st.metric, "value": st.value, "year": st.year, "url": ""})
        out.append(
            {
                "car_id": v.id,
                "label": v.label,
                "minimum_met": bool(run.minimum_met),
                "issues": [
                    {
                        "component": m.component,
                        "description": m.description,
                        "recurrence": m.recurrence,
                        "severity": m.severity,
                        "age_window": m.age_window,
                        "sources": evidence_sources(c, m.evidence_ids),
                    }
                    for m in merged
                ],
                "stats": stats,
                "none_found": not merged,
            }
        )
    if not out:
        return None
    return {"type": "reliability", "title": "Reliability and known issues", "cars": out}
