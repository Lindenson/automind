"""ASK, CONFIRM_VARIANTS and CONFIRM_COST nodes (FR-005, FR-006, FR-041).

Interrupts re-run their node on resume, so each confirmation is split into
prepare (side effects, once) → wait (only `interrupt`) → apply (record the answer).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from langgraph.types import interrupt

from automind.chat.application.services.identification import candidates, catalogue, resolver
from automind.chat.application.services.identification.contracts import GenerationMismatch, UnknownModel
from automind.chat.application.services.interpretation import ask as asking
from automind.chat.application.services.report.blocks import car_view, intake_card
from automind.chat.application.services.report.blocks.notice import Notice, notice
from automind.chat.application.services.research.contracts import PlanState
from automind.chat.dialog import phrases
from automind.chat.dialog.context import current_year, record_intake
from automind.chat.dialog.contract import Node, node
from automind.chat.dialog.nodes.confirm_io import (
    AskIn,
    AskOut,
    ConfirmOut,
    CostIn,
    CostResumeIn,
    PlanResumeIn,
    PrepareVariantsIn,
    PrepareVariantsOut,
    QuestionsIn,
    ResearchAnsweredOut,
    ResumeIn,
    SelectCandidatesIn,
    SelectCandidatesOut,
    VariantsAppliedOut,
    WaitIn,
    WaitOut,
)
from automind.chat.dialog.phrases import PHRASES, t
from automind.chat.dialog.state import TurnState
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain import intake
from automind.chat.domain.case import Choice, Pending
from automind.chat.domain.turn import Role
from automind.shared.contracts.json import JsonObject
from automind.shared.vehicle import markets


@node("ask", reads=AskIn, writes=AskOut)
async def ask_node(inp: AskIn, c: TurnContext) -> AskOut:
    """Questions in the conversation language with concrete options (spec 005 R6, R9): code writes them, the
    asker adds one sentence of acknowledgement; a question asked before uses other words."""
    case = await c.case()
    decision = inp.decision
    gens = {k: a.get("generations", []) for k, a in inp.assessments.items()}
    lang = inp.language
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
    lead = _not_understood_lead(case, inp, lang)
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
    await c.save_case(case, [f"asked: {', '.join(q['kind'] for q in items)}"])
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
    notices = [n for n in inp.notices if n.get("text") not in found]  # said in the reply already
    blocks = cast(list[JsonObject], [*notices, *([{"type": "quick_replies", "items": replies}] if replies else [])])
    return AskOut(reply_text=text, blocks=blocks, action="ASK")


def wait_node(kind: str) -> Node[WaitIn, WaitOut]:
    """The wait of the confirmation `kind` (node id `wait_<kind>`): the turn pauses on the prepared question (a
    LangGraph interrupt; re-run on resume, so nothing else happens here) and records the person's answer."""
    return node(f"wait_{kind}", reads=WaitIn, writes=WaitOut)(wait_confirm)


def _not_understood_lead(case: Any, inp: QuestionsIn, lang: str | None) -> str:
    """ "I did not understand <answer> for <car>." when the last message left a car question open (FR-031)."""
    keys = inp.not_understood or []
    if not keys:
        return ""
    answer = " ".join(str(inp.user_text or "").split())[:60]
    names = ", ".join(case.car(k).display_name for k in keys if any(x.key == k for x in case.cars))
    return t("not_understood", lang, answer=answer, car=names or "the car")


# --- variants ------------------------------------------------------------------------------------


def _years(o: dict[str, Any]) -> str:
    lo, hi = o.get("generation_years_from"), o.get("generation_years_to")
    return f" ({lo}–{hi or 'now'})" if lo else ""


@node("prepare_variants", reads=PrepareVariantsIn, writes=PrepareVariantsOut)
async def prepare_variants(inp: PrepareVariantsIn, c: TurnContext) -> PrepareVariantsOut:
    """Resolve each car to confirm (catalog first, then the resolver) and propose the best match."""
    case = await c.case()
    year = current_year(c)
    await c.status("resolving", "Identifying the exact variants")
    options: list[dict[str, Any]] = []
    notices: list[Notice] = []
    items: list[dict[str, Any]] = []
    unknown: list[str] = []
    lang = inp.language
    # cars with a named version first: their level sets the level of the others (spec 004 FR-029)
    keys = sorted(inp.decision["cars"], key=lambda k: not case.car(k).constraints.trim_hint)
    for key in keys:
        car = case.car(key)
        cands = list(inp.assessments.get(key, {}).get("candidates", []))
        if car.resolution == "PROPOSED" and car.variant_id and not any(o["id"] == car.variant_id for o in cands):
            v = await catalogue.get_variant(car.variant_id)  # asked again: keep the proposal, no new lookup
            if v is not None:
                cands = [catalogue.variant_dict(v), *cands]
        if not cands:
            try:
                v, ident = await resolver.resolve_with_llm(c.ports, car, year, case.compare_level)
                cands = [catalogue.variant_dict(v)]
                if ident.note:
                    notices.append(notice(f"{v.label}: {ident.note}"))
            except GenerationMismatch as e:
                notices.append(notice(f"{car.request_text}: {e}. Please tell me the generation or year.", "warning"))
                continue
            except UnknownModel as e:
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
        await c.save_case(case, [f"{k}: unknown model" for k in unknown])
        return PrepareVariantsOut(route="assess", confirm_payload=None, notices=[*inp.notices, *notices])
    case.pending = Pending(kind="CONFIRM_VARIANTS", items=items)
    await c.save_case(case, [f"{i['car']} proposed: {i['options'][0]['label']}" for i in items])
    lines = [f"- **{i['car']}**: {i['options'][0]['label']}" for i in items]
    lead = _not_understood_lead(case, inp, lang)
    options.append({"id": "choose", "label": t("choose_for_me", lang), "detail": None, "car": None})
    text = (f"{lead}\n\n" if lead else "") + t("confirm_variants", lang) + "\n" + "\n".join(lines)
    payload = {
        "kind": "variants",
        "action": "CONFIRM_VARIANTS",
        "request_id": str(uuid.uuid4()),
        "text": text,
        "options": options,
    }
    return PrepareVariantsOut(confirm_payload=payload, notices=[*inp.notices, *notices])


async def wait_confirm(inp: WaitIn, c: TurnContext) -> WaitOut:
    """Pause on `confirm_payload`; the answer is a button's dict, or typed words as a "text" choice."""
    answer = interrupt(inp.confirm_payload)
    return WaitOut(resume=answer if isinstance(answer, dict) else {"choice": "text", "text": str(answer)})


@node("apply_variants", reads=ResumeIn, writes=VariantsAppliedOut)
async def apply_variants(inp: ResumeIn, c: TurnContext) -> VariantsAppliedOut:
    """Only a button confirms the proposal ("confirm"/"run", or a version picked); typed words and any other id are
    read by the interpreter (it may be a correction or a rejection, R2; spec 013 T012)."""
    case = await c.case()
    answer = intake.card_answer(inp.resume or {})
    if answer.kind in (intake.CardChoice.TEXT, intake.CardChoice.OTHER, intake.CardChoice.EDIT_FIELD):
        return VariantsAppliedOut(user_text=answer.text, confirm_payload=None, resume=None, route="interpret")
    if answer.kind in (intake.CardChoice.SKIP, intake.CardChoice.STOP):
        for car in case.cars:
            if car.resolution == "PROPOSED":
                car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
        case.pending = None
        await c.save_case(case, ["variant confirmation skipped"])
        return VariantsAppliedOut(route="end", action="CONFIRM_VARIANTS",
                                  reply_text=t("variants_skipped", inp.language))  # fmt: skip
    if answer.kind is intake.CardChoice.REMOVE:
        case.cars = [x for x in case.cars if x.key != answer.arg]
        case.pending = None
        await c.save_case(case, [f"{answer.arg} removed"])
        return VariantsAppliedOut(route="assess", confirm_payload=None, resume=None)
    if answer.kind is intake.CardChoice.OPTION:
        await _pick_option(case, answer.arg)
    changes = _confirm_proposed(case)
    case.pending = None
    await c.save_case(case, changes)
    if changes:
        await agreed(c, case, inp.language)
    return VariantsAppliedOut(route="assess", confirm_payload=None, resume=None)


def _confirm_proposed(case: Any) -> list[str]:
    changes = []
    for car in case.cars:
        if car.resolution == "PROPOSED" and car.variant_id:
            car.resolution = "CONFIRMED"
            changes.append(f"{car.key} confirmed: {car.label}")
    return changes


# --- cost ----------------------------------------------------------------------------------------


@node("prepare_cost", reads=CostIn, writes=ConfirmOut)
async def prepare_cost(inp: CostIn, c: TurnContext) -> ConfirmOut:
    """The research cost question for the cars the policy chose (over the cap: said)."""
    case = await c.case()
    d = inp.decision
    eur = float(inp.cost_estimate or 0)
    await c.status("estimating", f"Estimated research cost €{eur:.2f}")
    lang = inp.language
    cap = t("over_cap", lang, cap=f"{c.ports.policy.hard_cap_eur:.2f}") if d.get("over_cap") else ""
    labels = [case.car(k).label or case.car(k).request_text for k in d["cars"]]
    payload = {
        "kind": "cost",
        "action": "CONFIRM_COST",
        "request_id": str(uuid.uuid4()),
        "text": t("confirm_cost", lang, cars=", ".join(labels), depth=case.depth.lower(), eur=f"{eur:.2f}", cap=cap),
        "options": [],
        "estimate": {"eur": eur, "cars": len(d["cars"]), "areas": _areas(inp.research_plan), "depth": case.depth},
    }
    case.pending = Pending(kind="CONFIRM_COST", items=[{"eur": eur, "cars": d["cars"]}])
    await c.save_case(case, [], publish=False)
    return ConfirmOut(confirm_payload=payload)


@node("apply_cost", reads=CostResumeIn, writes=ResearchAnsweredOut)
async def apply_cost(inp: CostResumeIn, c: TurnContext) -> ResearchAnsweredOut:
    """The cost answer: typed words go to the interpreter; a button approves or declines (remembered per plan)."""
    case = await c.case()
    answer = inp.resume or {}
    choice = str(answer.get("choice") or "")
    case.pending = None
    await c.save_case(case, [], publish=False)
    if choice in ("text", "edit") or (not choice and answer.get("text")):
        return ResearchAnsweredOut(user_text=answer.get("text") or "", confirm_payload=None, resume=None,
                                   route="interpret")  # fmt: skip
    approved = choice in ("run", "yes", "confirm")
    if not approved:  # remember the refusal for this plan, so the same offer is not repeated every turn
        case.declined_plan = (inp.research_plan or {}).get("key")
        await c.save_case(case, ["research declined"], publish=False)
    return ResearchAnsweredOut(route="assess", cost_approved=approved, research_declined=not approved,
                               confirm_payload=None, resume=None)  # fmt: skip


def _areas(plan: PlanState | None) -> list[str]:
    return sorted({j[2] for j in (plan or {}).get("jobs", [])})


def route_after_prepare(state: TurnState) -> str:
    return "wait" if state.get("confirm_payload") else "assess"


def route_after_apply(state: TurnState) -> str:
    return str(state.get("route") or "assess")


# --- the intake card (spec 005 US5) -------------------------------------------------------------------------


@node("select_candidates", reads=SelectCandidatesIn, writes=SelectCandidatesOut)
async def select_candidates(inp: SelectCandidatesIn, c: TurnContext) -> SelectCandidatesOut:
    """Spec 007 US7: no car named, a need and a budget → 2–3 candidates become the case's cars."""
    case = await c.case()
    await c.status("resolving", "Choosing candidates for you")
    proposed = await candidates.propose(c.ports, case)
    if not proposed:
        if (note := candidates.ask_the_model(case)) is not None:  # 009 FR-022: a make with nothing to propose
            await c.save_case(case, [note])
            return SelectCandidatesOut(route="identify")
        return SelectCandidatesOut(route="general")
    names = ", ".join(f"{x['make']} {x['model']}" for x in proposed)
    await c.save_case(case, [f"candidates: {names}"])
    return SelectCandidatesOut(route="identify")


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
    return [_market_line(x, lang) for x in case.cars if x.market is not None and x.variant_id]


def _market_line(car: Any, lang: str | None) -> str:
    return t(markets.market_note(car.market), lang, car=f"{car.make} {car.model}",
             market=phrases.market_name(car.market, lang))  # fmt: skip


@node("prepare_intake", reads=CostIn, writes=ConfirmOut)
async def prepare_intake(inp: CostIn, c: TurnContext) -> ConfirmOut:
    """One card: the cars as resolved, the person, the research cost; edited by chips, confirmed by one "yes"."""
    case = await c.case()
    lang = inp.language or "en"
    variants: dict[str, Any] = {}
    options: dict[str, list[str]] = {}
    for car in case.cars:
        v = await catalogue.get_variant(car.variant_id or "")
        if v is None:
            continue
        variants[v.id] = v
        others = await catalogue.find_variants(v.make, v.model)
        options[car.key] = [x.label for x in others if x.id != v.id][:4]
    eur = float(inp.cost_estimate or 0)
    estimate = {"eur": eur, "cars": len(case.cars), "areas": _areas(inp.research_plan), "depth": case.depth}
    card = intake_card.build_card(case, variants, options, estimate, lang)
    case.intake.card = {"values": card.pop("values")}
    case.pending = Pending(kind="CONFIRM_INTAKE", items=[{"car": x.key} for x in case.cars])
    await c.save_case(case, ["confirmation card shown"])
    await record_intake(c, "CARD_SHOWN")
    over = t("over_cap", lang, cap=f"{c.ports.policy.hard_cap_eur:.2f}") if inp.decision.get("over_cap") else ""
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
    return ConfirmOut(confirm_payload=payload)


async def _card_edit(c: TurnContext, case: Any, answer: dict[str, Any]) -> None:
    changes = intake_card.apply_edit(case, answer.get("car_key"), str(answer.get("field") or ""),
                                     str(answer.get("value") or ""), current_year(c))  # fmt: skip
    if answer.get("field") == "variant" and (v := await catalogue.get_variant(str(answer.get("value") or ""))):
        case.car(str(answer.get("car_key"))).label = v.label
    case.pending = None
    await c.save_case(case, changes or ["card edit not applied"])


async def _pick_option(case: Any, arg: str) -> None:
    key, _, vid = arg.partition(":")
    if (v := await catalogue.get_variant(vid)) is not None and any(x.key == key for x in case.cars):
        case.car(key).variant_id, case.car(key).label = v.id, v.label


@node("apply_intake", reads=PlanResumeIn, writes=ResearchAnsweredOut)
async def apply_intake(inp: PlanResumeIn, c: TurnContext) -> ResearchAnsweredOut:
    """The intake card's answer: only a button confirms; typed words (even "нет") are read by the interpreter
    (spec 013 T012), never by a word list."""
    case = await c.case()
    answer = intake.card_answer(inp.resume or {})
    if answer.kind is intake.CardChoice.EDIT_FIELD:  # a chip on the card: code applies it, the car is identified again
        resume = inp.resume or {}
        await _card_edit(c, case, resume)
        await record_intake(c, "CARD_EDITED", resume.get("car_key"), str(resume.get("field") or ""))
        return ResearchAnsweredOut(confirm_payload=None, resume=None, route="identify")
    if answer.kind in (intake.CardChoice.TEXT, intake.CardChoice.OTHER):
        case.pending = None
        await c.save_case(case, [], publish=False)
        return ResearchAnsweredOut(confirm_payload=None, resume=None, user_text=answer.text, route="interpret")
    if answer.kind is intake.CardChoice.REMOVE:
        case.cars = [x for x in case.cars if x.key != answer.arg]
        case.pending = None
        await c.save_case(case, [f"{answer.arg} removed"])
        return ResearchAnsweredOut(confirm_payload=None, resume=None, route="assess")
    if answer.kind is intake.CardChoice.OPTION:  # a version picked from the options (old clients): that version, yes
        await _pick_option(case, answer.arg)
    research = answer.kind in (intake.CardChoice.CONFIRM, intake.CardChoice.OPTION)  # "not now": cars kept only
    return await _card_confirmed(c, case, inp, research=research)


async def _card_confirmed(c: TurnContext, case: Any, inp: PlanResumeIn, *, research: bool) -> ResearchAnsweredOut:
    """The cars of the card confirmed by a button; the research too, unless "not now" (`research` False)."""
    for car in case.cars:
        if car.variant_id and car.resolution in ("PROPOSED", "AUTO_OK", "UNRESOLVED"):
            car.resolution = "CONFIRMED"
    case.intake.card_confirmed = True
    case.pending = None
    await record_intake(c, "CONFIRMED")
    if research:
        await c.save_case(case, ["cars and research confirmed"])
        await agreed(c, case, inp.language)
        return ResearchAnsweredOut(confirm_payload=None, resume=None, route="assess", cost_approved=True)
    case.declined_plan = (inp.research_plan or {}).get("key")  # "not now": the cars stay, no research
    await c.save_case(case, ["cars confirmed, research declined"])
    await agreed(c, case, inp.language)
    return ResearchAnsweredOut(confirm_payload=None, resume=None, route="assess", research_declined=True)


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
                 "variant_label": (views.get(x.key) or {}).get("variant_label"), "basis": _basis(x),
                 **({"note": _market_line(x, lang)} if x.market is not None else {})}
                for x in case.cars if x.variant_id]  # fmt: skip
        if not cars:
            return
        names = "; ".join(f"{x['label']}" + (f" ({x['variant_label']})" if x["variant_label"] else "") for x in cars)
        # chat 2026-11-06 (owner): a car not sold in Spain says where it was found here too, not only in the report
        text = "\n".join([t("agreed", lang, cars=names), *(str(x["note"]) for x in cars if x.get("note"))])
        blocks = [{"type": "agreed", "cars": cars}]
        msg = await c.ports.messages.save(c.chat_id, Role.ASSISTANT, text, blocks, turn_id=c.turn_id)
        await c.emit("agreed", {"message_id": msg.id, "created_at": msg.created_at.isoformat(), "text": text,
                                "blocks": blocks, "role": "assistant"})  # fmt: skip
    except Exception:  # noqa: BLE001 - the entry is a trace, the turn goes on
        return
