"""After the report (spec 007 FR-006/FR-013, J T077; spec 004 FR-015, FR-018): the changed scores are marked, what
was shown is remembered (its fingerprint: an unchanged case is never re-reported, FR-004), and one question about
the person follows — a guessed profile field that decides the winner first, else the field whose answer would
change the winner or the tie on this data. An answer shows only what changed, unless the persona changed."""

from __future__ import annotations

from typing import Any

from automind.chat.application.services.report.contracts import Computed
from automind.chat.application.services.report.facts.car import short_name
from automind.chat.dialog.phrases import t
from automind.chat.dialog.state import TurnState
from automind.chat.domain.assessment import ask_value, profile_gaps
from automind.chat.domain.case import CaseFile, Shown
from automind.chat.domain.fingerprint import fingerprint


def shown_report(case: CaseFile, comp: Computed, lang: str | None, probes: Any) -> tuple[list[dict[str, Any]], str]:
    """The report's blocks with the score changes and one question, remembered on the case; returns its fingerprint."""
    blocks = list(comp.blocks)
    mark_score_changes(case, blocks)  # spec 007 FR-013: changed scores are highlighted
    fp = fingerprint(case)
    case.shown.append(
        Shown(turn_seq=len(case.shown) + 1, fingerprint=fp, blocks=[b["type"] for b in blocks], persona=case.persona)
    )
    case.asked = [q for q in case.asked if q in _ONCE]  # profile questions: once
    confirm = confirm_inferred(case, comp, blocks, lang)  # a guess that decides comes first (one question)
    blocks += profile_question(case, comp, lang, probes) if confirm is None else confirm
    panel = next((b for b in blocks if b.get("type") == "data_panel"), None)
    if panel is not None:  # what the next "find it" is compared against (spec 004 FR-015)
        case.last_values = {x["car_key"]: int(x["values"]) for x in panel["cars"]}
    return blocks, fp


def shown_answer(
    state: TurnState, case: CaseFile, comp: Computed, nothing_new: bool
) -> tuple[list[dict[str, Any]], bool]:
    """The blocks an answer shows; True when the persona changed and the reordered report was remembered."""
    last = case.shown[-1].persona if case.shown else None
    persona_changed = bool(state.get("persona_changed")) or (last is not None and last != case.persona)
    blocks: list[dict[str, Any]] = [] if nothing_new else changed_blocks(state, comp.blocks, persona_changed)
    if persona_changed and not nothing_new:  # the reordered report was shown: later follow-ups are short again
        case.shown.append(Shown(turn_seq=len(case.shown) + 1, fingerprint=fingerprint(case),
                                blocks=[b["type"] for b in blocks], persona=case.persona))  # fmt: skip
        return blocks, True
    return blocks, False


def changed_blocks(state: TurnState, blocks: list[dict[str, Any]], persona_changed: bool) -> list[dict[str, Any]]:
    """For a weights change or a follow-up, show the recomputed scores (and warnings), not the whole report."""
    if persona_changed:
        return blocks  # a new persona sees the whole report in its own order (FR-030)
    keep = {"criteria_scores"} if state.get("request_kind") == "weights_change" else {"criteria_scores", "race_chart"}
    return [b for b in blocks if b.get("type") in keep or (b.get("type") == "notice" and b.get("level") == "warning")]


def confirm_inferred(
    case: CaseFile, comp: Any, blocks: list[dict[str, Any]], lang: str | None
) -> list[dict[str, Any]] | None:  # fmt: skip
    """Spec 007 J (T077): a guessed profile field that decides the winner is never applied silently. The verdict
    says what it assumes and what the result would be without it, and the user is asked to confirm (once; the
    note stays on every report until the field is stated). None when no guess decides the outcome."""
    if comp.outcome is None or len(comp.cars) < 2:
        return None
    flip = ask_value.inferred_flip(case, comp.outcome)
    if flip is None:
        return None
    key, (other_car, other_tie) = flip
    what = _what(case, key, lang)
    names = {car["variant"].id: short_name(car["variant"]) for car in comp.cars}
    other = t("other_tie", lang) if other_tie or not other_car else t("other_wins", lang, car=names.get(other_car, ""))
    note = t("assume_note", lang, what=what, ev=case.profile.evidence.get(key, "…"), other=other)
    verdict = next((b for b in blocks if b.get("type") == "verdict"), None)
    if verdict is not None:
        verdict["profile_notes"] = [note, *verdict.get("profile_notes", [])]
    if "CONFIRM_PROFILE" in case.asked:
        return []
    case.asked.append("CONFIRM_PROFILE")
    if key == "family":
        items = [
            {"label": t(f"family_{x}", lang), "text": t(f"family_{x}", lang)} for x in ("single", "couple", "kids")
        ]
    elif key == "driving_style":
        items = [{"label": t(f"style_{x}", lang), "text": t(f"style_{x}", lang)} for x in ("CALM", "MIXED", "SPORTY")]
    else:
        yes = t("confirm_yes", lang, what=what)
        items = [{"label": yes, "text": yes}, {"label": t("confirm_no", lang), "text": t("confirm_no", lang)}]
    return [{"type": "quick_replies", "question": t("confirm_q", lang, what=what), "items": items}]


def profile_question(case: CaseFile, comp: Any, lang: str | None, probes: Any = None) -> list[dict[str, Any]]:
    """One question about the user, under the report and never blocking it, and only when the answer would change
    the winner or the tie on this data (spec 007 FR-006; spec 004 FR-018). The answer recomputes the report."""
    variants = [car["variant"] for car in comp.cars]
    if len(variants) < 2:
        return []
    kinds: list[str] = []
    if comp.outcome is not None:
        kinds = list(ask_value.questions(case, comp.outcome, probes or {}))
    if not kinds:
        gaps = profile_gaps.questions(case, [v.powertrain for v in variants], [v.vehicle_class for v in variants])
        kinds = [k for k in gaps if k == "FAMILY_SIZE"]
    if not kinds:
        return []
    kind = kinds[0]
    case.asked.append(kind)  # type: ignore[arg-type]
    if kind == "KM_PER_YEAR":
        items = [{"label": x, "text": x} for x in ("8,000 km", "15,000 km", "25,000 km", "40,000 km")]
    elif kind == "OWNERSHIP_YEARS":
        items = [{"label": t(f"years_{n}", lang), "text": t(f"years_{n}", lang)} for n in (3, 5, 8, 12)]
    elif kind == "PERSONA":
        items = [{"label": t(f"persona_{p}", lang), "text": t(f"persona_{p}", lang)} for p in _PERSONA_CHIPS]
    elif kind == "HOME_CHARGING":
        items = [{"label": t(f"charge_{x}", lang), "text": t(f"charge_{x}", lang)} for x in ("YES", "WORK", "NO")]
    else:
        items = [
            {"label": t(f"family_{x}", lang), "text": t(f"family_{x}", lang)} for x in ("single", "couple", "kids")
        ]
    q = t(f"profile_{kind}", lang, km=f"{case.annual_km:,}", years=case.ownership_years or "")
    return [{"type": "quick_replies", "question": q, "items": items}]


def mark_score_changes(case: CaseFile, blocks: list[dict[str, Any]]) -> None:
    """Annotate the criteria block with the change of each total and criterion score against the previous report,
    and remember these scores for the next one (spec 007 FR-013)."""
    crit = next((b for b in blocks if b.get("type") == "criteria_scores"), None)
    if crit is None:
        return
    now: dict[str, dict[str, float]] = {}
    for car in crit.get("cars", []):
        now[str(car.get("car_id"))] = _mark_car(car, case.last_scores.get(str(car.get("car_id"))))
    prev_weights = case.last_weights
    if prev_weights:
        for row in crit.get("criteria", []):
            row["delta"] = round(float(row["weight"]) - prev_weights.get(row["key"], 0.0), 1)
    case.last_scores = now
    case.last_weights = {row["key"]: float(row["weight"]) for row in crit.get("criteria", [])}


_PERSONA_CHIPS = ("PERFORMANCE", "BUYER", "EXPERT")


_ONCE = ("KM_PER_YEAR", "FAMILY_SIZE", "OWNERSHIP_YEARS", "PERSONA", "CONFIRM_PROFILE", "HOME_CHARGING")


_FAMILY_CHIP = {"SINGLE": "single", "COUPLE": "couple", "FAMILY": "kids"}


def _what(case: CaseFile, key: str, lang: str | None) -> str:
    p = case.profile
    if key == "family" and p.family:
        return t(f"family_{_FAMILY_CHIP[p.family]}", lang)
    if key == "driving_style" and p.driving_style:
        return t(f"style_{p.driving_style}", lang)
    if key == "usage":
        return ", ".join(u.lower() for u in case.usage)
    return str(getattr(p, key, "") or "")


def _mark_car(car: dict[str, Any], before: dict[str, float] | None) -> dict[str, float]:
    parts = car.get("parts") or {}
    scores = {k: float(p["score"]) for k, p in parts.items() if p.get("score") is not None}
    if car.get("total") is not None:
        scores["_total"] = float(car["total"])
    if before is not None:
        if "_total" in scores and "_total" in before:
            car["delta"] = round(scores["_total"] - before["_total"], 1)
        for k, part in parts.items():
            if k in scores and k in before:
                part["delta"] = round(scores[k] - before[k], 1)
    return scores
