"""ASK, CONFIRM_VARIANTS and CONFIRM_COST nodes (FR-005, FR-006, FR-041).

Interrupts re-run their node on resume, so each confirmation is split into
prepare (side effects, once) → wait (only `interrupt`) → apply (record the answer).
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from automind.application import ask as asking
from automind.application import candidates, car_view, intake_card, resolve
from automind.config import settings
from automind.domain import intake
from automind.domain.casefile import Choice, Pending
from automind.orchestration import phrases
from automind.orchestration.phrases import PHRASES, t
from automind.orchestration.runner import TurnContext
from automind.orchestration.state import TurnState

from .common import ctx, current_year, load_case, notice, record_intake, save_case


async def ask_node(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Questions in the conversation language with concrete options (spec 005 R6, R9): code writes them, the
    asker adds one sentence of acknowledgement; a question asked before uses other words."""
    c = ctx(runtime)
    _, case = await load_case(c)
    decision = state["decision"]
    gens = {k: a.get("generations", []) for k, a in state.get("assessments", {}).items()}
    lang = state.get("language", "en")
    ref = c.ports.ref
    gearboxes = {"automatic": t("gb_automatic", lang), "manual": t("gb_manual", lang)}
    items = asking.intake_questions(decision["questions"], case, ref.questions_i18n or {}, gens, decision["cars"], lang,
                                    gearboxes)  # fmt: skip
    if not items:  # nothing concrete to ask: fall back to the v1 templates (English, phrased by the asker)
        items = asking.fill_questions(decision["questions"], case, ref.questions, gens, decision["cars"])
    await c.status("asking", "Asking what I need to know")
    ack = await asking.acknowledge(c.ports.llm, ref.prompts["asker"], lang, asking.understood_summary(case), case.cars)
    if lang in ("ru", "es", "en") and ack and phrases.guess_language([ack]) != lang:
        ack = ""  # FR-023: a sentence in another language is dropped; the questions are templates in `lang`
    questions = [q["text"] for q in items]
    body = questions[0] if len(questions) == 1 else "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    lead = _not_understood_lead(case, state, lang)
    found = _market_lines(case, lang)
    text = "\n\n".join(x for x in (lead, ack, "\n".join(found), body) if x)
    case = asking.record(case, items)
    for q in items:
        if q.get("kind") == "PROPOSE" and q.get("choices"):
            case.intake.proposed[q["car"]] = Choice.model_validate(q["choices"][0])
    asked = [(intake.StepItem(q["item"], q.get("car")), q["text"]) for q in items if q.get("item")]
    for it, q_text in asked:
        await record_intake(c, "ASKED", it.car_key, it.item, repeat=intake.is_repeat(case, it.car_key, it.item, q_text),
                            text_hash=intake.question_hash(it.car_key, it.item, q_text))  # fmt: skip
    case = intake.record_asked(case, asked)
    version = await save_case(c, case, [f"asked: {', '.join(q['kind'] for q in items)}"])
    labels = {"new": t("cond_new", lang), "used": t("cond_used", lang), "yes": t("yes", lang),
              "no": t("no_other", lang), "choose": t("choose_for_me", lang),
              "other": t("other_type", lang), "remove": t("remove_car", lang, car="{car}"), **gearboxes}  # fmt: skip
    for q in items:  # machine reasons of suggested models → the conversation language
        for ch in q.get("choices") or []:
            if ch.get("reason"):
                ch["reason"] = "; ".join(
                    t(f"why_{k}", lang) for k in str(ch["reason"]).split(",") if f"why_{k}" in PHRASES
                )
    replies = asking.intake_quick_replies(items, case, labels)
    notices = [n for n in state.get("notices", []) if n.get("text") not in found]  # said in the reply already
    blocks = [*notices, *([{"type": "quick_replies", "items": replies}] if replies else [])]
    return {"reply_text": text, "blocks": blocks, "action": "ASK", "case_version": version}


def _not_understood_lead(case: Any, state: TurnState, lang: str | None) -> str:
    """ "I did not understand <answer> for <car>." when the last message left a car question open (FR-031)."""
    keys = state.get("not_understood") or []
    if not keys:
        return ""
    answer = " ".join(str(state.get("user_text") or "").split())[:60]
    names = ", ".join(case.car(k).display_name for k in keys if any(x.key == k for x in case.cars))
    return t("not_understood", lang, answer=answer, car=names or "the car")


# --- variants ------------------------------------------------------------------------------------


def _years(o: dict[str, Any]) -> str:
    lo, hi = o.get("generation_years_from"), o.get("generation_years_to")
    return f" ({lo}–{hi or 'now'})" if lo else ""


async def prepare_variants(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Resolve each car to confirm (catalog first, then the resolver) and propose the best match."""
    c = ctx(runtime)
    _, case = await load_case(c)
    year = current_year(c)
    await c.status("resolving", "Identifying the exact variants")
    options: list[dict[str, Any]] = []
    notices: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    unknown: list[str] = []
    lang = state.get("language")
    # cars with a named version first: their level sets the level of the others (spec 004 FR-029)
    keys = sorted(state["decision"]["cars"], key=lambda k: not case.car(k).constraints.trim_hint)
    for key in keys:
        car = case.car(key)
        cands = list(state.get("assessments", {}).get(key, {}).get("candidates", []))
        if car.resolution == "PROPOSED" and car.variant_id and not any(o["id"] == car.variant_id for o in cands):
            v = await resolve.get_variant(car.variant_id)  # asked again: keep the proposal, no new lookup
            if v is not None:
                cands = [resolve.variant_dict(v), *cands]
        if not cands:
            try:
                v, ident = await resolve.resolve_with_llm(c.ports, car, year, case.compare_level)
                cands = [resolve.variant_dict(v)]
                if ident.note:
                    notices.append(notice(f"{v.label}: {ident.note}"))
            except resolve.GenerationMismatch as e:
                notices.append(notice(f"{car.request_text}: {e}. Please tell me the generation or year.", "warning"))
                continue
            except resolve.UnknownModel as e:
                car.resolution, car.alternatives = "UNKNOWN_MODEL", [{"model": m} for m in e.closest]
                unknown.append(key)
                continue
        best = cands[0]
        car.variant_id, car.label, car.resolution = best["id"], best["label"], "PROPOSED"
        if car.constraints.trim_hint and best.get("trim_level") and case.compare_level_source == "DEFAULT":
            case.compare_level, case.compare_level_source = best["trim_level"], "USER_TRIM"
        detail = ", ".join(x for x in (car.condition.lower() if car.condition != "UNKNOWN" else "",
                                       f"~{car.year}" if car.year else "") if x)  # fmt: skip
        car_opts = [
            {"id": f"option:{key}:{o['id']}", "label": f"{o['label']}{_years(o)}", "detail": detail or None, "car": key}
            for o in cands[:3]
        ]
        car_opts.append({"id": f"remove:{key}", "label": t("remove_car", lang, car=car.request_text), "detail": None,
                         "car": key})  # fmt: skip
        options += car_opts
        items.append({"car": key, "options": car_opts})
        await c.status("resolving", f"{car.request_text} → {best['label']}{_years(best)}", car=best["label"])
    if not items:  # every car to confirm is unknown: ask about it instead (the policy asks UNKNOWN_MODEL)
        await save_case(c, case, [f"{k}: unknown model" for k in unknown])
        return {"route": "assess", "confirm_payload": None, "notices": [*state.get("notices", []), *notices]}
    case.pending = Pending(kind="CONFIRM_VARIANTS", items=items)
    await save_case(c, case, [f"{i['car']} proposed: {i['options'][0]['label']}" for i in items])
    lines = [f"- **{i['car']}**: {i['options'][0]['label']}" for i in items]
    lead = _not_understood_lead(case, state, lang)
    options.append({"id": "choose", "label": t("choose_for_me", lang), "detail": None, "car": None})
    text = (f"{lead}\n\n" if lead else "") + t("confirm_variants", lang) + "\n" + "\n".join(lines)
    payload = {
        "kind": "variants",
        "action": "CONFIRM_VARIANTS",
        "request_id": str(uuid.uuid4()),
        "text": text,
        "options": options,
    }
    return {"confirm_payload": payload, "notices": [*state.get("notices", []), *notices]}


def wait_confirm(state: TurnState) -> dict[str, Any]:
    answer = interrupt(state["confirm_payload"])
    return {"resume": answer if isinstance(answer, dict) else {"choice": "text", "text": str(answer)}}


async def apply_variants(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Button choice → confirm; free text → interpret it (it may be a correction, R2)."""
    c = ctx(runtime)
    _, case = await load_case(c)
    answer = state.get("resume") or {}
    choice = str(answer.get("choice") or "")
    if choice in ("text", "edit") or (not choice and answer.get("text")):
        return {"user_text": answer.get("text") or "", "confirm_payload": None, "resume": None, "route": "interpret"}
    if choice == "skip":
        for car in case.cars:
            if car.resolution == "PROPOSED":
                car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
        case.pending = None
        await save_case(c, case, ["variant confirmation skipped"])
        return {
            "route": "end",
            "action": "CONFIRM_VARIANTS",
            "reply_text": t("variants_skipped", state.get("language")),
        }
    if choice.startswith("remove:"):
        key = choice.split(":", 1)[1]
        case.cars = [x for x in case.cars if x.key != key]
        case.pending = None
        version = await save_case(c, case, [f"{key} removed"])
        return {"route": "assess", "confirm_payload": None, "resume": None, "case_version": version}
    if choice.startswith("option:"):
        _, key, vid = choice.split(":", 2)
        car = case.car(key)
        v = await resolve.get_variant(vid)
        if v is not None:
            car.variant_id, car.label = v.id, v.label
    changes = _confirm_proposed(case)
    case.pending = None
    version = await save_case(c, case, changes)
    if changes:
        await agreed(c, case, state.get("language"))
    return {"route": "assess", "confirm_payload": None, "resume": None, "case_version": version}


def _confirm_proposed(case: Any) -> list[str]:
    changes = []
    for car in case.cars:
        if car.resolution == "PROPOSED" and car.variant_id:
            car.resolution = "CONFIRMED"
            changes.append(f"{car.key} confirmed: {car.label}")
    return changes


# --- cost ----------------------------------------------------------------------------------------


async def prepare_cost(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    d = state["decision"]
    eur = float(state.get("cost_estimate") or 0)
    await c.status("estimating", f"Estimated research cost €{eur:.2f}")
    lang = state.get("language")
    cap = t("over_cap", lang, cap=f"{settings().cost_hard_cap_eur:.2f}") if d.get("over_cap") else ""
    labels = [case.car(k).label or case.car(k).request_text for k in d["cars"]]
    payload = {
        "kind": "cost",
        "action": "CONFIRM_COST",
        "request_id": str(uuid.uuid4()),
        "text": t("confirm_cost", lang, cars=", ".join(labels), depth=case.depth.lower(), eur=f"{eur:.2f}", cap=cap),
        "options": [],
        "estimate": {"eur": eur, "cars": len(d["cars"]), "areas": _areas(state), "depth": case.depth},
    }
    case.pending = Pending(kind="CONFIRM_COST", items=[{"eur": eur, "cars": d["cars"]}])
    await save_case(c, case, [], publish=False)
    return {"confirm_payload": payload}


async def apply_cost(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    answer = state.get("resume") or {}
    choice = str(answer.get("choice") or "")
    case.pending = None
    await save_case(c, case, [], publish=False)
    if choice in ("text", "edit") or (not choice and answer.get("text")):
        return {"user_text": answer.get("text") or "", "confirm_payload": None, "resume": None, "route": "interpret"}
    approved = choice in ("run", "yes", "confirm")
    if not approved:  # remember the refusal for this plan, so the same offer is not repeated every turn
        case.declined_plan = (state.get("research_plan") or {}).get("key")
        await save_case(c, case, ["research declined"], publish=False)
    return {
        "route": "assess",
        "cost_approved": approved,
        "research_declined": not approved,
        "confirm_payload": None,
        "resume": None,
    }


def route_after_prepare(state: TurnState) -> str:
    return "wait" if state.get("confirm_payload") else "assess"


def route_after_apply(state: TurnState) -> str:
    return str(state.get("route") or "assess")


def _areas(state: TurnState) -> list[str]:
    return sorted({j[2] for j in (state.get("research_plan") or {}).get("jobs", [])})


# --- the intake card (spec 005 US5) -------------------------------------------------------------------------


async def select_candidates(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """Spec 007 US7: no car named, a need and a budget → 2–3 candidates become the case's cars."""
    c = ctx(runtime)
    _, case = await load_case(c)
    await c.status("resolving", "Choosing candidates for you")
    proposed = await candidates.propose(c.ports, case)
    if not proposed:
        if (note := candidates.ask_the_model(case)) is not None:  # 009 FR-022: a make with nothing to propose
            return {"route": "identify", "case_version": await save_case(c, case, [note])}
        return {"route": "general"}
    names = ", ".join(f"{x['make']} {x['model']}" for x in proposed)
    version = await save_case(c, case, [f"candidates: {names}"])
    return {"route": "identify", "case_version": version}


def route_after_candidates(state: TurnState) -> str:
    return "identify" if state.get("route") == "identify" else "general"


def _candidate_lines(case: Any, lang: str) -> str:
    """One line per proposed candidate still in the case: the reason by code, the price or "price to check"."""
    keys = {x.key for x in case.cars}
    lines = []
    for x in case.candidates:
        if x.get("key") not in keys:
            continue
        why = "; ".join(t(f"why_{k}", lang) for k in x.get("why") or [] if f"why_{k}" in PHRASES)
        price = x.get("price_from_eur")
        cost = t("cand_price", lang, eur=f"{int(price):,}".replace(",", " ")) if price else t("cand_price_check", lang)
        lines.append(f"• {x['make']} {x['model']} — {why or t('cand_fits', lang)}; {cost}")
    if not lines:
        return ""
    make = getattr(case, "wanted_make", None)
    if not make:
        return t("cand_intro", lang) + "\n" + "\n".join(lines)
    # 009 FR-022: "a Kia to replace my Prado": the make's candidates, compared with the user's own car
    own = [x.display_name + (f" (~{x.year})" if x.year else "") for x in case.cars if getattr(x, "replaced", False)]
    replaces = t("cand_replaces", lang, car=", ".join(own)) if own else ""
    return t("cand_intro_make", lang, make=make, replaces=replaces) + "\n" + "\n".join(lines)


def _market_lines(case: Any, lang: str | None) -> list[str]:
    """Cars not sold in Spain (chat 2026-11-06, owner): where each was found — a European country, else its home
    market — and where its data and prices come from; said in the reply, not only in a notice."""
    return [t(intake.market_note(x.market), lang, car=f"{x.make} {x.model}",
              market=phrases.market_name(x.market, lang))
            for x in case.cars if x.market is not None and x.variant_id]  # fmt: skip


async def prepare_intake(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    """One card: the cars as resolved, the person, the research cost; edited by chips, confirmed by one "yes"."""
    c = ctx(runtime)
    _, case = await load_case(c)
    lang = state.get("language") or "en"
    variants: dict[str, Any] = {}
    options: dict[str, list[str]] = {}
    for car in case.cars:
        v = await resolve.get_variant(car.variant_id or "")
        if v is None:
            continue
        variants[v.id] = v
        others = await resolve.catalog_for(v.make, v.model)
        options[car.key] = [x.label for x in others if x.id != v.id][:4]
    eur = float(state.get("cost_estimate") or 0)
    estimate = {"eur": eur, "cars": len(case.cars), "areas": _areas(state), "depth": case.depth}
    card = intake_card.build_card(case, variants, options, estimate, lang)
    case.intake.card = {"values": card.pop("values")}
    case.pending = Pending(kind="CONFIRM_INTAKE", items=[{"car": x.key} for x in case.cars])
    await save_case(c, case, ["confirmation card shown"])
    await record_intake(c, "CARD_SHOWN")
    over = t("over_cap", lang, cap=f"{settings().cost_hard_cap_eur:.2f}") if state["decision"].get("over_cap") else ""
    await c.status("estimating", f"Confirm the cars and the research (≈ €{eur:.2f})")
    payload = {
        "kind": "intake",
        "action": "CONFIRM_INTAKE",
        "request_id": str(uuid.uuid4()),
        "text": "\n\n".join(
            x
            for x in (
                _candidate_lines(case, lang),
                "\n".join(_market_lines(case, lang)),
                t("intake_card", lang, eur=f"{eur:.2f}") + (f" {over}" if over else ""),
            )
            if x
        ),
        "options": [{"id": "yes", "label": t("card_yes", lang)}, {"id": "stop", "label": t("card_stop", lang)}],
        "estimate": estimate,
        "card": card,
    }
    return {"confirm_payload": payload}


async def _card_edit(c: TurnContext, case: Any, answer: dict[str, Any]) -> None:
    changes = intake_card.apply_edit(case, answer.get("car_key"), str(answer.get("field") or ""),
                                     str(answer.get("value") or ""), current_year(c))  # fmt: skip
    if answer.get("field") == "variant" and (v := await resolve.get_variant(str(answer.get("value") or ""))):
        case.car(str(answer.get("car_key"))).label = v.label
    case.pending = None
    await save_case(c, case, changes or ["card edit not applied"])


async def _pick_option(case: Any, choice: str) -> None:
    _, key, vid = choice.split(":", 2)
    if (v := await resolve.get_variant(vid)) is not None and any(x.key == key for x in case.cars):
        case.car(key).variant_id, case.car(key).label = v.id, v.label


async def apply_intake(state: TurnState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    c = ctx(runtime)
    _, case = await load_case(c)
    answer = state.get("resume") or {}
    choice = str(answer.get("choice") or "")
    done = {"confirm_payload": None, "resume": None}
    if choice == "edit_field":  # a chip on the card: code applies it, the car is identified again
        await _card_edit(c, case, answer)
        await record_intake(c, "CARD_EDITED", answer.get("car_key"), str(answer.get("field") or ""))
        return {**done, "route": "identify"}
    if choice in ("text", "edit") or (not choice and answer.get("text")):
        raw = str(answer.get("text") or "")
        bare = len(raw.split()) <= 3 and not any(ch.isdigit() for ch in raw)  # "нет, 1.5" is a correction, not a no
        typed = "yes" if phrases.choose_for_me(raw) else (phrases.yes_or_no(raw) if bare else None)
        if typed is None:
            case.pending = None
            await save_case(c, case, [], publish=False)
            return {**done, "user_text": answer.get("text") or "", "route": "interpret"}
        choice = "yes" if typed == "yes" else "stop"
    if choice.startswith("option:"):  # a version picked from the options (old clients): that version, and yes
        await _pick_option(case, choice)
        choice = "yes"
    if choice.startswith("remove:"):
        key = choice.split(":", 1)[1]
        case.cars = [x for x in case.cars if x.key != key]
        case.pending = None
        await save_case(c, case, [f"{key} removed"])
        return {**done, "route": "assess"}
    for car in case.cars:
        if car.variant_id and car.resolution in ("PROPOSED", "AUTO_OK", "UNRESOLVED"):
            car.resolution = "CONFIRMED"
    case.intake.card_confirmed = True
    case.pending = None
    await record_intake(c, "CONFIRMED")
    if choice in ("yes", "run", "confirm", "continue"):
        await save_case(c, case, ["cars and research confirmed"])
        await agreed(c, case, state.get("language"))
        return {**done, "route": "assess", "cost_approved": True}
    case.declined_plan = (state.get("research_plan") or {}).get("key")  # "not now": the cars stay, no research
    await save_case(c, case, ["cars confirmed, research declined"])
    await agreed(c, case, state.get("language"))
    return {**done, "route": "assess", "research_declined": True}


# --- the "Agreed" entry (spec 010 FR-035) ---------------------------------------------------------------------


def _basis(car: Any) -> str:
    """How the version was settled: the user's words, chosen by me, or looked up."""
    origin = car.ladder.origin if car.ladder else {}
    if car.chosen_for_me or any(v in ("CHOSEN", "LIMIT") for v in origin.values()):
        return "ASSUMED"
    k = car.constraints
    if (k.engine_hint and not k.engine_hint.empty()) or k.trim_hint or k.gearbox_hint or k.version_hint:
        return "STATED"
    return "LOOKED_UP"


async def agreed(c: TurnContext, case: Any, lang: str | None) -> None:
    """After a confirmation, a read-only "Agreed" message with each car's version line and its basis stays in the
    chat (persisted, so it survives a reload). Never fails the turn."""
    try:
        views = await car_view.view(case)
        cars = [{"key": x.key, "label": x.label or x.request_text,
                 "variant_label": (views.get(x.key) or {}).get("variant_label"), "basis": _basis(x)}
                for x in case.cars if x.variant_id]  # fmt: skip
        if not cars:
            return
        names = "; ".join(f"{x['label']}" + (f" ({x['variant_label']})" if x["variant_label"] else "") for x in cars)
        text = t("agreed", lang, cars=names)
        blocks = [{"type": "agreed", "cars": cars}]
        msg = await c.ports.messages.save(c.chat_id, "assistant", text, blocks, turn_id=c.turn_id)
        await c.emit("agreed", {"message_id": msg.id, "created_at": msg.created_at.isoformat(), "text": text,
                                "blocks": blocks, "role": "assistant"})  # fmt: skip
    except Exception:  # noqa: BLE001 - the entry is a trace, the turn goes on
        return
