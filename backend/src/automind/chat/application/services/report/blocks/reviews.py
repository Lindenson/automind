"""Block reviews: what reviewers praise and criticise, with sources."""

from __future__ import annotations

from automind.chat.application.services.report.contracts import LoadedCar
from automind.chat.application.services.report.facts.car import evidence_sources
from automind.chat.application.services.report.facts.quality import review_items
from automind.chat.domain.assessment import reviews
from automind.shared.contracts.json import JsonObject


def reviews_block(cars: list[LoadedCar]) -> JsonObject | None:
    """The reviews block: per researched car its pros and cons (a recurring point once), with the summary; None when
    no car was researched for reviews."""
    out = []
    for c in cars:
        v = c["variant"]
        if c.get("runs", {}).get("reviews") is None:
            continue
        items = review_items(c)
        summary = reviews.summarize_reviews(items)
        points: dict[str, list[JsonObject]] = {"PRO": [], "CON": []}
        seen: set[tuple[str, str]] = set()
        for r in items:
            rec_pc = summary.recurring.get(r.tag)
            recurring = bool(rec_pc and (rec_pc[0] if r.polarity == "PRO" else rec_pc[1]))
            key = (r.tag, r.polarity) if recurring else (r.tag + r.text, r.polarity)
            if key in seen:
                continue
            seen.add(key)
            points[r.polarity].append(
                {"tag": r.tag, "text": r.text, "recurring": recurring, "sources": evidence_sources(c, [r.evidence_id])}
            )
        for k in points:
            points[k].sort(key=lambda p: (not p["recurring"], p["tag"]))
        out.append(
            {
                "car_id": v.id,
                "label": v.label,
                "minimum_met": summary.minimum_met,
                "review_count": summary.review_count,
                "source_count": summary.source_count,
                "pros": points["PRO"][:6],
                "cons": points["CON"][:6],
            }
        )
    if not out:
        return None
    return {"type": "reviews", "title": "What reviewers and owners say", "cars": out}
