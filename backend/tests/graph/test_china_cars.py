"""Live chat 2026-11-06: "я вот выбираю между Deepal S09 и Lixiang L9 и хочу сделать однозначный выбор".

The reply was "Вы ищете информацию о кроссоверах Deepal S07 и Lixiang L9. 1. Я не нашёл «Deepal S09» в продаже в
Испании. Ближайшие: Deepal S09. Какую из них? 2. Новые или подержанные?" — three defects:
1. the asker's sentence renamed the user's S09 to S07 (a sibling the model knew better);
2. the "not found; nearest" question offered the very model asked;
3. both cars are sold in China only, but identification looked in Spain only.
Now a car not on the Spanish line-up is looked up where it is sold (Europe first, then its home market), identified
there, and the user is told its data come from that market and its price only from Europe (spec 009 FR-009)."""

import uuid
from dataclasses import replace

from sqlalchemy import select

from automind.application import lineup
from automind.infrastructure import db
from automind.infrastructure.db.repositories import MessageRepo
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, engine, forget_make, make_ports

FIRST = "я вот выбираю между Deepal S09 и Lixiang L9 и хочу сделать однозначный выбор"
CARS = [{"request_text": "Deepal S09", "make": "Deepal", "model": "S09"},
        {"request_text": "Lixiang L9", "make": "Li Auto", "model": "L9"}]  # fmt: skip
LIVE_ASKER = "Вы ищете информацию о кроссоверах Deepal S07 и Lixiang L9."  # what the asker wrote in the live chat

LINEUPS = {
    ("Deepal", "EU"): [{"model": "S07", "body": "suv", "powertrains": ["bev"], "price_from_eur": 39990,
                        "excerpt": "The Deepal S07 costs from 39.990 €",
                        "source_url": "https://www.autonews.example/deepal-europe-range"}],
    ("Deepal", "CN"): [{"model": "S07", "body": "suv", "powertrains": ["bev"], "source_url": "https://www.deepal.com.cn"},
                       {"model": "S09", "body": "suv", "powertrains": ["phev", "bev"], "price_from_eur": 219900,
                        "excerpt": "深蓝S09 指导价 21.99-29.99万元", "source_url": "https://www.deepal.com.cn"}],
    ("Li Auto", "CN"): [{"model": "L9", "body": "suv", "powertrains": ["phev"], "price_from_eur": 409800,
                         "excerpt": "理想L9 指导价 40.98-43.98万元", "source_url": "https://www.lixiang.com"},
                        {"model": "L6", "body": "suv", "powertrains": ["phev"], "source_url": "https://www.lixiang.com"}],
}  # fmt: skip
S09 = {"make": "Deepal", "model": "S09", "generation": None, "generation_years_from": 2025,
       "generation_years_to": None, "variant_name": "1.5T EREV 380 kW AWD", "powertrain": "PHEV", "body_class": "SUV",
       "engine_cc": 1494, "power_kw": 380, "fuel": "phev", "price_eur": 30000, "drive": "AWD", "known_model": True,
       "certainty": "likely", "note": "Sold in China."}  # fmt: skip
L9 = {"make": "Li Auto", "model": "L9", "generation": "1st Gen", "generation_years_from": 2022,
      "generation_years_to": None, "variant_name": "Pro 1.5T EREV AWD", "powertrain": "PHEV", "body_class": "SUV",
      "engine_cc": 1496, "power_kw": 330, "fuel": "phev", "price_eur": 52000, "drive": "AWD", "known_model": True,
      "certainty": "likely", "note": "Sold officially in China; not distributed in Spain."}  # fmt: skip


def _lineup(system: str, user: str) -> dict:
    make = user.split("\n", 1)[0].removeprefix("Make: ").strip()
    market = next((ln.split()[1] for ln in user.splitlines() if ln.startswith("Market: ")), "ES")
    return {"models": LINEUPS.get((make, market), [])}


def _resolver(system: str, user: str) -> dict:
    return S09 if "Model asked: Deepal S09" in user else L9


async def _runner(saver, llm, scenario: str = "china"):
    for make in ("Deepal", "Li Auto"):
        await forget_make(make)
    ports = replace(make_ports(llm=llm, search=FixtureSearch(scenario)), lineup=lineup.get_lineup)
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


def _llm() -> FakeLLM:
    llm = FakeLLM().queue("interpreter", {"request": "compare", "language": "ru", "delta": {"add_cars": CARS}})
    llm.responders["asker"] = lambda s, u: LIVE_ASKER
    llm.responders["lineup"] = _lineup
    llm.responders["resolver"] = _resolver
    return llm


def _abroad_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if "не продаётся — нашёл на рынке" in ln]


async def test_china_only_cars_are_identified_where_they_are_sold(saver):
    llm = _llm()
    rn = await _runner(saver, llm)
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, FIRST)
    # both identified: the confirmation card (new or used is a chip on it), never "not found; nearest: Deepal S09"
    assert r.status == "WAITING_CONFIRMATION" and r.confirm["kind"] == "intake", (r.status, r.reply_text)
    text = r.confirm["text"]
    assert "Ближайшие" not in text and "не нашёл" not in text, text
    names = [c["display_name"] for c in r.confirm["card"]["cars"]]
    assert names[0].startswith("Deepal S09") and names[1].startswith("Li Auto L9"), names
    # Europe first, then the make's home market (China); Spain is not searched for a make not sold here
    se = engine(rn.ports).search
    assert "CN" in se.markets and not any("España" in q for q in se.queries), se.queries
    eu = next(i for i, q in enumerate(se.queries) if "Deepal" in q and "Europe" in q)
    cn = next(i for i, q in enumerate(se.queries) if "Deepal" in q and "车型" in q)
    assert eu < cn
    assert any("Deepal S09" in q and "参数" in q for q in se.queries)  # the resolver read Chinese spec pages
    _, data, _ = await rn.ports.cases.latest(chat)
    cars = {c["key"]: c for c in data["cars"]}
    assert cars["car#1"]["market"] == "CN" and cars["car#2"]["market"] == "CN", cars
    assert cars["car#1"]["identify"]["outcome"] == "IDENTIFIED" and cars["car#1"]["variant_id"]
    async with db.sessionmaker()() as s:
        rows = (await s.execute(select(db.Variant).where(db.Variant.make.in_(["Deepal", "Li Auto"])))).scalars().all()
        assert {v.model for v in rows} == {"S09", "L9"}
        assert all(v.price_eur is None for v in rows)  # no euro price from outside Europe (spec 009 FR-009)
        lu = (await s.execute(select(db.BrandLineup).where(db.BrandLineup.make == "Deepal"))).scalars().all()
        cn_row = next(x for x in lu if x.market == "CN")
        assert all(m["price_from_eur"] is None for m in cn_row.models)  # a CNY price is never a euro price
    # the user is told where it was found: not in Europe, on the Chinese market; prices from Europe only
    lines = _abroad_lines(text)
    assert [ln.split(":")[0] for ln in lines] == [
        "Deepal S09 в Европе не продаётся — нашёл на рынке Китая",
        "Li Auto L9 в Европе не продаётся — нашёл на рынке Китая",
    ], text
    assert all("цены — только с европейских рынков" in ln for ln in lines), text
    print("\n--- reply (confirmation card) ---\n" + text + "\n" + "\n".join(names))


async def test_nearest_is_never_the_model_asked(saver):
    """No line-up anywhere names it, but the resolver knows the very model: it exists (not in Spain), so it is
    identified on its make's home market instead of "not found «Deepal S09»; nearest: Deepal S09"."""
    llm = _llm()
    llm.responders["lineup"] = lambda s, u: {"models": []}
    rn = await _runner(saver, llm, scenario="empty")
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, FIRST)
    assert r.status == "WAITING_CONFIRMATION", (r.status, r.reply_text)
    assert "Ближайшие" not in r.confirm["text"]
    _, data, _ = await rn.ports.cases.latest(chat)
    car = data["cars"][0]
    assert car["identify"]["outcome"] == "IDENTIFIED" and car["market"] == "CN", car
    assert len(_abroad_lines(r.confirm["text"])) == 2


async def test_unknown_model_question_keeps_the_users_name_and_never_offers_it_back(saver):
    """The model is listed nowhere and the resolver does not know it: asked, with the make's other models as the
    nearest ones (never the name asked), and the asker's lead keeps the user's "Deepal S09" (it wrote S07 live)."""
    llm = _llm()
    unknown = {**S09, "known_model": False, "certainty": "ambiguous"}
    llm.responders["resolver"] = lambda s, u: unknown if "Model asked: Deepal S09" in u else L9
    llm.responders["lineup"] = lambda s, u: {"models": []} if "Market: CN" in u and "Deepal" in u else _lineup(s, u)
    rn = await _runner(saver, llm)
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, FIRST)
    assert r.action == "ASK", (r.status, r.reply_text)
    lead = r.reply_text.split("\n\n")[0]
    assert lead == "Вы ищете информацию о кроссоверах Deepal S09 и Lixiang L9.", r.reply_text
    assert "Ближайшие: Deepal S09" not in r.reply_text and "Deepal S07" in r.reply_text, r.reply_text
    chips = [c["label"] for b in r.blocks if b["type"] == "quick_replies" for c in b["items"]]
    assert not any(c.startswith("Deepal S09") for c in chips), chips
    assert "Подержанные" in chips  # new or used is still asked with the identity question
    assert "Li Auto L9 в Европе не продаётся — нашёл на рынке Китая" in r.reply_text, r.reply_text
    print("\n--- reply ---\n" + r.reply_text)


async def test_found_on_a_european_market_the_reply_names_the_country(saver):
    """Owner 2026-11-06: "Deepal S09 в Испании не продаётся — нашёл на рынке Польши"; Europe is searched first (one
    market, no country preferred), and only a car no European market sells is named on its home market (China)."""
    llm = _llm()
    pl = {"model": "S09", "body": "suv", "powertrains": ["phev"], "source_url": "https://www.deepal.pl/modele"}
    llm.responders["lineup"] = lambda s, u: (
        {"models": [*LINEUPS[("Deepal", "EU")], pl]} if u.startswith("Make: Deepal") and "Market: EU" in u
        else _lineup(s, u))  # fmt: skip
    rn = await _runner(saver, llm)
    chat = str(uuid.uuid4())
    r = await rn.run_turn(chat, FIRST)
    text = r.confirm["text"] if r.confirm else r.reply_text
    lines = [ln.split(":")[0] for ln in _abroad_lines(text)]
    assert lines == ["Deepal S09 в Испании не продаётся — нашёл на рынке Польши",
                     "Li Auto L9 в Европе не продаётся — нашёл на рынке Китая"], text  # fmt: skip
    assert "Ближайшие" not in text and "не нашёл" not in text, text
    se = engine(rn.ports).search
    assert not any("Deepal" in q and "车型" in q for q in se.queries)  # found in Europe: China not searched for it
    _, data, _ = await rn.ports.cases.latest(chat)
    assert [c["market"] for c in data["cars"]] == ["PL", "CN"]
    print("\n--- reply (confirmation card) ---\n" + text)
