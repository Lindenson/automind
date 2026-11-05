"""Spec 005 US2 (FR-007–FR-011): a make absent from the catalog is identified from its Spanish line-up with sources;
the models that fit the person come first as suggestions; a model of the line-up is known without the resolver
returning a generation; a classifieds link is never read. Stands in for goldens G22/G24/G26 until recorded live."""

import uuid
from dataclasses import replace

from automind.application import lineup
from automind.infrastructure import db
from automind.infrastructure.db.repositories import MessageRepo
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, engine, forget_make, make_ports

LINEUP = {"models": [
    {"model": "Dolphin", "body": "hatchback", "powertrains": ["bev"], "price_from_eur": 29990,
     "excerpt": "BYD Dolphin — compacto eléctrico. Desde 29.990 €", "source_url": "https://www.byd.com/es"},
    {"model": "Atto 3", "body": "suv", "powertrains": ["bev"], "price_from_eur": 37990,
     "excerpt": "BYD Atto 3 — SUV compacto eléctrico. Desde 37.990 €", "source_url": "https://www.byd.com/es"},
    {"model": "Seal U DM-i", "body": "suv", "powertrains": ["phev"], "price_from_eur": 35990,
     "excerpt": "BYD Seal U DM-i — SUV familiar híbrido enchufable. Desde 35.990 €", "source_url": "https://www.byd.com/es"},
    {"model": "Seal", "body": "sedan", "powertrains": ["bev"], "price_from_eur": 46990,
     "excerpt": "BYD Seal — berlina eléctrica. Desde 46.990 €", "source_url": "https://www.byd.com/es"},
]}  # fmt: skip
SEAL_U = {"make": "BYD", "model": "Seal U DM-i", "generation": None, "generation_years_from": None,
          "generation_years_to": None, "variant_name": "1.5 DM-i 218 CV Comfort", "powertrain": "PHEV",
          "body_class": "SUV", "engine_cc": 1498, "power_kw": 160, "fuel": "phev", "price_eur": 35990,
          "known_model": False, "certainty": "likely"}  # fmt: skip


def _ru(delta: dict, request: str = "compare") -> dict:
    return {"request": request, "language": "ru", "delta": delta}


async def _runner(saver, llm):
    await forget_make("BYD")
    ports = replace(make_ports(llm=llm, search=FixtureSearch("byd")), lineup=lineup.get_lineup)
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


async def test_brand_only_offers_its_spanish_lineup_family_suvs_first(saver):
    llm = FakeLLM().queue("lineup", LINEUP)
    llm.responders["asker"] = lambda s, u: "Понял: BYD для семьи."
    byd = {"request_text": "byd", "make": "BYD", "condition": "NEW"}
    llm.queue("interpreter", _ru({"set_profile": {"family": "FAMILY", "evidence": {"family": "семейной"}},
                                  "add_cars": [byd]}))  # fmt: skip
    rn = await _runner(saver, llm)
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, "насколько хороша byd — найди соответствующую модель — для семейной эксплуатации")
    assert r.action == "ASK", r.reply_text
    assert "Seal U DM-i" in r.reply_text and "Atto 3" in r.reply_text  # real models of the make, from its page
    assert "не знаю" not in r.reply_text.lower() and "make and model" not in r.reply_text
    chips = next(b for b in r.blocks if b["type"] == "quick_replies")["items"]
    assert chips[0]["label"].startswith("BYD Seal U DM-i") and chips[0].get("suggested")  # family SUV, PHEV first
    assert "семейный кузов" in (chips[0].get("reason") or "")
    assert not any(c.get("suggested") for c in chips if "Seal (" in c["label"])  # a sedan is not suggested

    # the user picks it: a model of the line-up exists even without a generation from the resolver
    llm.queue("interpreter", _ru({"set_car_context": [{"target_key": "car#1", "make": "BYD", "model": "Seal U DM-i"}]}))
    llm.queue("resolver", SEAL_U)
    w = await rn.run_turn(chat, "BYD Seal U DM-i")
    assert w.status == "WAITING_CONFIRMATION" and w.confirm["kind"] == "intake", (w.action, w.reply_text)
    assert "Seal U" in w.confirm["card"]["cars"][0]["display_name"]
    async with db.sessionmaker()() as s:
        from sqlalchemy import select

        v = (await s.execute(select(db.Variant).where(db.Variant.make == "BYD"))).scalars().first()
        assert v is not None and v.fuel == "phev" and v.power_kw == 160


async def test_classifieds_link_is_refused_and_maker_home_page_names_the_make(saver):
    llm = FakeLLM().queue("lineup", LINEUP)
    llm.responders["asker"] = lambda s, u: "Понял."
    link = {"request_text": "вот эта", "condition": "NEW", "constraints": {"url": "https://www.coches.net/byd-seal-u"}}
    llm.queue("interpreter", _ru({"add_cars": [link]}))
    rn = await _runner(saver, llm)
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, "вот эта https://www.coches.net/byd-seal-u")
    assert any("объявлений" in b.get("text", "") for b in r.blocks if b["type"] == "notice"), r.blocks
    assert "https://www.coches.net/byd-seal-u" not in engine(rn.ports).search.extracted
    llm.queue(
        "interpreter",
        _ru({"set_car_context": [{"target_key": "car#1", "constraints": {"url": "https://www.byd.com/"}}]}),
    )
    r2 = await rn.run_turn(chat, "https://www.byd.com/ вот он!")
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data["cars"][0]["make"] == "BYD" and "Seal U DM-i" in r2.reply_text


DOLPHIN = {"make": "BYD", "model": "Dolphin", "generation": None, "generation_years_from": None,
           "generation_years_to": None, "variant_name": "Active 95 CV 44.9 kWh", "powertrain": "BEV",
           "engine_cc": None, "power_kw": 70, "fuel": "bev", "trim_level": "BASE", "known_model": True,
           "certainty": "likely", "note": "Dolphin is BYD's base model in Spain."}  # fmt: skip


async def test_resolver_answering_another_model_is_never_accepted(saver):
    """Live chat 2026-11-03: "BYD Seal U" became "BYD Dolphin Active" (the cheapest BYD) and stayed on the card."""
    llm = FakeLLM().queue("lineup", LINEUP)
    llm.responders["asker"] = lambda s, u: "Понял."
    llm.queue("interpreter", _ru({"add_cars": [{"request_text": "byd seal u", "make": "BYD", "model": "Seal U",
                                                "condition": "NEW"}]}))  # fmt: skip
    llm.queue("resolver", DOLPHIN, DOLPHIN)  # wrong twice: asked again with "insist", still wrong
    rn = await _runner(saver, llm)
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, "BYD Seal U")
    assert r.action == "ASK", (r.status, r.reply_text)
    assert llm.roles_called().count("resolver") == 2
    assert "Dolphin" not in r.reply_text.split("\n\n")[-1].split(":")[0]
    chips = [c["label"] for c in next(b for b in r.blocks if b["type"] == "quick_replies")["items"]]
    assert chips[0].startswith("BYD Seal U"), chips  # the model the user named comes first
    _, data, _ = await rn.ports.cases.latest(chat)
    assert data["cars"][0]["variant_id"] is None

    # the user insists; this time the resolver returns the right model
    llm.queue("interpreter", _ru({"set_car_context": [{"target_key": "car#1", "make": "BYD", "model": "Seal U"}]}))
    llm.queue("resolver", SEAL_U)
    w = await rn.run_turn(chat, "не правильно. модель SEAL U")
    assert w.confirm is not None and "Seal U" in w.confirm["card"]["cars"][0]["display_name"], (w.status, w.reply_text)


async def test_a_stored_wrong_model_is_dropped_on_the_next_turn(saver):
    llm = FakeLLM().queue("lineup", LINEUP)
    llm.responders["asker"] = lambda s, u: "Понял."
    llm.queue("interpreter", _ru({"add_cars": [{"request_text": "byd", "make": "BYD", "condition": "NEW"}]}))
    rn = await _runner(saver, llm)
    chat = str(uuid.uuid4())
    await rn.run_turn(chat, "byd")
    from automind.application import resolve as rs

    v = await rn.ports.cases.latest(chat)
    dolphin = await rs.upsert_variant(rs.VariantIdentity.model_validate(DOLPHIN), rn.ports.ref)
    _, data, _ = v
    data["cars"][0].update(
        {"model": "Seal U", "variant_id": dolphin.id, "label": dolphin.label, "resolution": "PROPOSED"}
    )
    await rn.ports.cases.save_version(chat, data, "test", ["a wrong proposal from before the fix"])
    llm.queue("interpreter", _ru({}))
    llm.queue("resolver", SEAL_U)
    w = await rn.run_turn(chat, "BYD model Seal U")
    _, data, _ = await rn.ports.cases.latest(chat)
    assert "Dolphin" not in (data["cars"][0]["label"] or ""), data["cars"][0]
    assert "Dolphin" in (data["cars"][0]["previous_label"] or "")
    assert w.status in ("WAITING_CONFIRMATION", "DONE")
