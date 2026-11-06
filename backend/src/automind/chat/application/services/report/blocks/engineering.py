"""Block engineering: engineering facts per car with their sources and the technology explainers."""

from __future__ import annotations

from automind.chat.application.services.report.facts.car import claim_source, txt
from automind.chat.application.services.report.facts.display import display
from automind.chat.application.services.report.facts.quality import ENGINEERING_ATTRS
from automind.shared.vehicle import specs


def engineering_block(cars: list[dict], explainers: dict | None = None) -> dict | None:
    out = []
    for c in cars:
        items = []
        for k in ENGINEERING_ATTRS:
            sv = c["values"].get(k)
            if sv is None or not sv.available:
                continue
            items.append(
                {
                    "key": k,
                    "label": specs.ATTRS[k].label,
                    "display": display(k, sv) or "",
                    "confidence": sv.confidence or "LOW",
                    "sources": [claim_source(c, cid) for cid in (sv.claim_ids or []) if cid in c["claim_src"]],
                }
            )
        out.append({"car_id": c["variant"].id, "label": c["variant"].label, "items": items,
                    "explainers": tech_explainers(c, explainers or {})})  # fmt: skip
    if not any(x["items"] or x["explainers"] for x in out):
        return None
    return {"type": "engineering", "title": "Engineering", "cars": out}


def tech_explainers(car: dict, cfg: dict) -> list[dict]:
    """What the car's drivetrain technology means (spec 004 FR-004): config text matched on the car's own
    validated gearbox / engine / powertrain, never web text. Most specific match first, at most two."""
    v = car["variant"]
    words = " ".join(
        str(x) for x in (txt(car, "transmission"), txt(car, "engine"), v.variant_name, v.powertrain,
                         v.transmission) if x
    ).lower()  # fmt: skip
    hits = []
    for key, e in (cfg.get("explainers") or {}).items():
        if any(m in words for m in e.get("match", [])):
            hits.append({"key": key, "title": e.get("title", key), "text": e.get("text", ""),
                         "consumption": e.get("consumption"), "reliability": e.get("reliability"),
                         "feel": e.get("feel"), "source": e.get("source", "editorial")})  # fmt: skip
    hybrid = {"power_split_hybrid", "series_hybrid"}
    if any(h["key"] in hybrid for h in hits):  # a hybrid's "automatic" label is not a torque converter
        hits = [h for h in hits if h["key"] not in ("torque_converter", "cvt")]
    return hits[:2]
