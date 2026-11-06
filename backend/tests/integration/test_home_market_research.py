"""Chat 2026-11-06 ("я вот выбираю между Deepal S09 и Lixiang L9"): both cars were identified on the Chinese market,
but research read European sites only — no spec, no consumption, and the report said for both "стоимость энергии не
посчитать — нет данных: расход электричества, запас хода на электричестве, расход топлива с разряженной батареей".

A car sold only in China is now researched there too: Chinese queries with its Chinese name, `site:` queries to the
registry's Chinese sources (never pcauto / autohome, whose terms forbid commercial use) and to English sites that
cover Chinese cars. Chinese spec pages fill the energy inputs: kWh/100 km and the electric range as CLTC (never as
WLTP), the charge-sustaining 亏电油耗; the energy cost is computed. Prices are never searched there (009 FR-009).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from sqlalchemy import delete, select
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.graph.conftest import engine, make_ports, open_web_reference

from automind.acquisition import api as acquisition
from automind.acquisition.registry.api import PlannedSource
from automind.chat.application.services.report import compose
from automind.chat.dialog.nodes.compute import energy_notices
from automind.chat.domain.cost import tco
from automind.shared.infrastructure import db
from automind.shared.infrastructure.db import models as m

CONFIG = Path(__file__).parents[2] / "config"
RATES = tco.TcoRates.from_config(yaml.safe_load((CONFIG / "rates.yaml").read_text()))
CJK = re.compile(r"[一-鿿]")


class ChinaRegistry:
    """The registry's sources of the Chinese market (survey 2026-11-05) and an attempts journal."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, list[str]]] = []
        self.attempts: list = []

    async def plan(self, area, markets, make):  # noqa: ANN001, ANN201
        return None

    async def sources_for(self, area, markets, limit):  # noqa: ANN001, ANN201
        self.asked.append((area, list(markets)))
        if markets != ["CN"]:
            return []
        rows = ["autohome.com.cn", "pcauto.com.cn", "d1ev.com", "chexun.com", "carnewschina.com", "16888.com"]
        return [PlannedSource(domain=d, market="CN", priority=i, status="candidate", unverified=True)
                for i, d in enumerate(rows)][:limit]  # fmt: skip

    async def record(self, attempts):  # noqa: ANN001, ANN201
        self.attempts += attempts


def _row(attribute: str, raw: str, unit: str, excerpt: str) -> dict:
    return {"attribute": attribute, "raw_value": raw, "unit": unit, "excerpt": excerpt, "scope": "VARIANT"}


# what a reader of the Chinese spec tables returns: the rows verbatim, under the attributes the target's glossary names
S09 = [
    _row("max_power", "231", "kW", "| 最大功率(kW) | 231 |"),
    _row("claimed_0_100", "7.5", "s", "| 0-100km/h加速(s) | 7.5 |"),
    _row("curb_mass", "2475", "kg", "| 整备质量(kg) | 2475 |"),
    _row("battery_kwh", "41.2", "kWh", "| 电池容量(kWh) | 41.2 |"),
    _row("range_wltp", "210", "km", "| CLTC纯电续航里程(km) | 210 |"),  # misfiled by the reader: refiled as CLTC
    _row("consumption_ev", "20.3", "kWh/100km", "| 百公里电耗(kWh/100km) | 20.3 |"),  # Chinese page: CLTC
    _row("consumption_cs", "6.15", "L/100km", "| 亏电油耗(L/100km) | 6.15 |"),
    _row("consumption_weighted", "0.79", "L/100km", "| WLTC综合油耗(L/100km) | 0.79 |"),
]
L9 = [
    _row("max_power", "330", "kW", "| 最大功率(kW) | 330 |"),
    _row("claimed_0_100", "5.3", "s", "| 百公里加速(s) | 5.3 |"),
    _row("range_cltc", "280", "km", "| CLTC纯电续航里程(km) | 280 |"),
    _row("consumption_ev_cltc", "21.5", "kWh/100km", "| 百公里电耗(kWh/100km) | 21.5 |"),
    _row("consumption", "7.6", "L/100km", "| 亏电油耗(L/100km) | 7.6 |"),  # "consumption": its words say empty battery
]
CARNEWS = [_row("range_cltc", "210", "km", "a CLTC pure electric range of 210 km")]


def _extractor(system: str, user: str) -> dict:
    url = re.search(r'<untrusted_document url="([^"]+)"', user).group(1)  # type: ignore[union-attr]
    claims = S09 if "d1ev.com" in url else L9 if "chexun.com" in url else CARNEWS if "carnewschina" in url else []
    return {"is_about_variant": True, "claims": claims}


def _ports(fx: FixtureSearch, reg: ChinaRegistry, llm: FakeLLM):  # noqa: ANN202
    llm.responders["extractor"] = _extractor
    llm.responders["relevance"] = lambda s, u: {"verdict": "RELEVANT", "reason": "the model's page"}
    llm.responders["validator"] = lambda s, u: {"verdicts": [{"index": i, "verdict": "SAME_VARIANT"}
                                                             for i in range(12)]}  # fmt: skip
    ports = engine(make_ports(llm=llm, search=fx))
    ports.ref = open_web_reference()
    ports.registry = reg
    return ports


async def _variant(make: str, model: str, generation: str | None, name: str, years: tuple[int, int | None]) -> str:
    async with db.sessionmaker()() as s:  # as identified live: the variant row keeps the default market ES
        v = m.Variant(canonical_key=f"{make}|{model}|{name}|home-{db.uid()}".lower(), make=make, model=model,
                      generation=generation, variant_name=name, powertrain="PHEV", body_class="SUV",
                      generation_years_from=years[0], generation_years_to=years[1])  # fmt: skip
        s.add(v)
        await s.commit()
        return v.id


async def _purge(vid: str) -> None:
    async with db.sessionmaker()() as s:
        for t in (m.SpecValue, m.Claim, m.ResearchRun, m.PageRelevance, m.RegistryAttempt):
            await s.execute(delete(t).where(t.variant_id == vid))
        await s.execute(delete(m.Evidence).where(m.Evidence.variant_id == vid))
        await s.execute(delete(m.Variant).where(m.Variant.id == vid))
        await s.commit()


@pytest.fixture
async def cars():
    await db.init_db()
    s09 = await _variant("Deepal", "S09", None, "1.5T EREV 210km RWD", (2025, None))
    l9 = await _variant("Li Auto", "L9", "1st Gen", "Pro 1.5T EREV AWD", (2022, None))
    yield s09, l9
    await _purge(s09)
    await _purge(l9)


async def _values(vid: str) -> dict[str, float]:
    async with db.sessionmaker()() as s:
        rows = await s.execute(select(m.SpecValue.attribute, m.SpecValue.value_num)
                               .where(m.SpecValue.variant_id == vid, m.SpecValue.available))  # fmt: skip
        return {a: float(n) for a, n in rows.all() if n is not None}


async def _energy(vid: str):  # noqa: ANN202
    car = await compose.load_car(vid)
    return tco.compute(await compose.tco_car(car, "NEW", None, None), RATES, 15000, 5)


async def test_a_china_market_car_is_researched_in_china_and_its_energy_cost_computed(cars):
    s09, l9 = cars
    fx, reg, llm = FixtureSearch("china_research"), ChinaRegistry(), FakeLLM()
    ports = _ports(fx, reg, llm)
    for vid in (s09, l9):
        req = acquisition.AcquireRequest(job_id=db.uid(), variant_id=vid, kinds=["specs"], market="CN")
        (k,) = (await acquisition.acquire(req, None, ports=ports)).kinds
        assert k.ok, k.error

    # the searches: Chinese, with the Chinese names; the registry's Chinese sources (never pcauto / autohome);
    # the English sites that cover Chinese cars
    chinese = [q for q in fx.queries if CJK.search(q)]
    assert "深蓝S09 参数配置 百公里电耗 纯电续航 亏电油耗" in chinese
    assert "理想L9 参数配置 百公里电耗 纯电续航 亏电油耗" in chinese
    assert "深蓝S09 site:d1ev.com OR site:chexun.com OR site:16888.com" in fx.queries
    assert ("Deepal S09 specs CLTC range kWh/100km fuel consumption site:carnewschina.com OR site:cnevpost.com"
            in fx.queries)  # fmt: skip
    assert not any("autohome" in q or "pcauto" in q for q in fx.queries)
    assert {mk for q, mk in zip(fx.queries, fx.markets, strict=True) if CJK.search(q)} == {"CN"}
    assert not any("autohome" in u for u in fx.extracted)  # its terms forbid commercial use: never read
    # the extractor is told the market, the Chinese name and how Chinese pages label the figures
    target = next(c.user for c in llm.calls if c.role == "extractor" and "d1ev.com" in c.user)
    assert "market CN" in target and "深蓝S09" in target and "百公里电耗" in target and "market ES" not in target

    got = await _values(s09)
    assert got["consumption_ev_cltc"] == 20.3 and got["range_cltc"] == 210 and got["consumption_cs"] == 6.15
    assert got["max_power"] == 231 and got["claimed_0_100"] == 7.5
    assert "range_wltp" not in got and "consumption_ev" not in got  # a CLTC figure is never WLTP
    got = await _values(l9)
    assert got["consumption_ev_cltc"] == 21.5 and got["range_cltc"] == 280 and got["consumption_cs"] == 7.6
    assert "consumption" not in got

    for vid, name in ((s09, "Deepal S09"), (l9, "Li Auto L9")):
        est = await _energy(vid)
        energy = next(i for i in est.items if i.kind == "ENERGY")
        assert not energy.missing and energy.annual_eur > 0
        assert any("CLTC" in line for line in energy.inputs)
        # the report no longer says "стоимость энергии не посчитать — нет данных"
        assert energy_notices([est], {vid: name}, "ru") == []

    # every page read from these searches is an attempt of its Chinese source in the registry
    assert {a.market for a in reg.attempts if "d1ev.com" in a.url or "chexun.com" in a.url} == {"CN"}


async def test_prices_are_never_searched_on_the_home_market(cars):
    s09, _ = cars
    fx, reg = FixtureSearch("china_research"), ChinaRegistry()
    ports = _ports(fx, reg, FakeLLM())
    req = acquisition.AcquireRequest(job_id=db.uid(), variant_id=s09, kinds=["price"], market="CN")
    (k,) = (await acquisition.acquire(req, None, ports=ports)).kinds
    assert k.ok, k.error
    assert fx.queries and not any(CJK.search(q) or "site:carnewschina" in q for q in fx.queries)
    assert ("price", ["CN"]) not in reg.asked


async def test_a_car_sold_in_spain_gets_no_home_market_search(cars):
    s09, _ = cars
    fx, reg = FixtureSearch("china_research"), ChinaRegistry()
    req = acquisition.AcquireRequest(job_id=db.uid(), variant_id=s09, kinds=["specs"])  # no market: Spain
    (k,) = (await acquisition.acquire(req, None, ports=_ports(fx, reg, FakeLLM()))).kinds
    assert k.ok, k.error
    assert not any(CJK.search(q) for q in fx.queries) and not any(mk == ["CN"] for _, mk in reg.asked)
