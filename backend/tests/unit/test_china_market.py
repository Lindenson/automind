"""Cars not sold in Spain (live chat 2026-11-06: "Deepal S09 vs Lixiang L9"): the user's model names kept, never the
model asked offered as its own alternative, Chinese makes known by their transliterations, looked up Europe first
then on their home market, and no euro price taken from outside Europe (spec 009 FR-009)."""

from dataclasses import dataclass

from automind.acquisition.api import LineupEntry, WebHint
from automind.acquisition.pipeline import identity as readers
from automind.acquisition.registry.api import PlannedSource
from automind.application import lineup
from automind.application.makes import MakeRegistry
from automind.domain import identity, intake
from automind.domain.casefile import CaseCar
from automind.infrastructure.config import load_yaml, search_config
from automind.orchestration.phrases import PHRASES, market_name, t

REG = MakeRegistry.from_config(load_yaml("makes.yaml"))


def _car(text: str, make: str, model: str, **kw: object) -> CaseCar:
    return CaseCar(key="car#1", request_text=text, make=make, model=model, **kw)


def test_the_asker_sentence_keeps_the_users_model_names() -> None:
    cars = [_car("Deepal S09", "Deepal", "S09"), _car("Lixiang L9", "Li Auto", "L9")]
    live = "Вы ищете информацию о кроссоверах Deepal S07 и Lixiang L9."
    assert intake.keep_user_names(live, cars) == "Вы ищете информацию о кроссоверах Deepal S09 и Lixiang L9."
    assert intake.keep_user_names("Сравниваю Lixiang L7 и Deepal S09.", cars) == "Сравниваю Lixiang L9 и Deepal S09."
    # a paraphrase that is not a sibling code is left alone ("BMW 3 Series" for a 320d)
    bmw = [_car("BMW 320d", "BMW", "320d")]
    assert intake.keep_user_names("Вы сравниваете BMW 3 Series.", bmw) == "Вы сравниваете BMW 3 Series."
    assert intake.keep_user_names("Понял: BMW X5 и BMW 320d.", bmw) == "Понял: BMW X5 и BMW 320d."


def test_a_confirmed_other_model_is_named_as_confirmed() -> None:
    car = _car("Deepal S09", "Deepal", "S07", resolution="CONFIRMED")
    assert intake.user_model(car) == "S07"
    assert intake.keep_user_names("Deepal S07, понял.", [car]) == "Deepal S07, понял."


def test_never_the_model_asked_as_its_own_alternative() -> None:
    assert intake.other_names("Deepal S09", ["Deepal S09", "Deepal S07", "Deepal s-09"]) == ["Deepal S07"]
    assert intake.same_name("S09", "s 09") and not intake.same_name("S09", "S07")


def test_a_european_page_names_its_country() -> None:
    assert intake.country_of_url("https://www.deepal.pl/modele") == "PL"
    assert intake.country_of_url("https://www.autoexpress.co.uk/deepal") == "GB"
    assert intake.country_of_url("https://www.autonews.com/x") is None
    assert intake.country_of_url("https://www.16888.com/deepal/") is None
    assert intake.european("UA") and intake.european("NO") and intake.european("TR") and not intake.european("CN")
    assert intake.market_note("PL") == "sold_in_europe" and intake.market_note("CN") == "sold_abroad"
    pl = [LineupEntry(model="S09", source_url="https://www.deepal.pl/modele")]
    docs = {"https://www.deepal.pl/modele": ("Deepal Polska", "Deepal S07 · Deepal S09")}
    lu = lineup.validate("Deepal", pl, docs, None, "EU")  # the maker's own country site counts as official
    assert [(m.model, m.country) for m in lu.models] == [("S09", "PL")]


def test_lookup_order_europe_first_then_home_then_anywhere() -> None:
    assert intake.lookup_markets("CN") == ["EU", "CN", "ANY"]
    assert intake.lookup_markets(None) == ["EU", "ANY"]
    assert intake.lookup_markets("DE") == ["EU", "ANY"]
    assert intake.european(None) and intake.european("EU") and not intake.european("CN")
    assert intake.abroad_note("CN", priced=False) == "abroad_no_price"
    assert intake.abroad_note("CN", priced=True) == "abroad_priced"
    assert intake.abroad_note("PL", priced=False) == "sold_in_europe" and intake.abroad_note(None, priced=False) is None


def test_chinese_makes_and_their_transliterations() -> None:
    for text, make in (("Lixiang L9", "Li Auto"), ("理想L9", "Li Auto"), ("ли сян л9", "Li Auto"),
                       ("Deepal S09", "Deepal"), ("深蓝S09", "Deepal"), ("Changan Deepal S07", "Deepal"),
                       ("дипал с09", "Deepal"), ("NIO ES8", "NIO"), ("Aito M9", "Aito")):  # fmt: skip
        assert REG.match_make(text) == make, text
    assert REG.home("Li Auto") == "CN" and not REG.sold_in_spain("Li Auto") and not REG.sold_in_spain("Deepal")
    assert REG.sold_in_spain("Zeekr") and REG.home("Zeekr") == "CN" and REG.sold_in_spain("Toyota")
    assert REG.site_on("Li Auto", "CN") == "lixiang.com" and REG.site_on("Li Auto", "EU") is None
    assert REG.match_make("BMW 3 series") == "BMW"  # no Chinese make steals a common word
    aliases = identity.Aliases.from_config(load_yaml("aliases.yaml"))
    assert identity.normalize_make_model("Lixiang", "L9", aliases) == ("Li Auto", "L9")
    assert identity.normalize_make_model("深蓝", "深蓝S09", aliases) == ("Deepal", "S09")


DOCS = {"https://www.lixiang.com": ("理想汽车", "理想L9 Li Auto L9 指导价 40.98万元 · 理想L6"),
        "https://news.example/li-auto": ("Li Auto news", "Li Auto L9 and L6 sold in China")}  # fmt: skip


def test_a_lineup_outside_europe_keeps_no_price_and_needs_the_maker_or_a_trusted_source() -> None:
    entries = [LineupEntry(model="L9", price_from_eur=409800, excerpt="理想L9 指导价 40.98万元",
                           source_url="https://www.lixiang.com"),
               LineupEntry(model="L6", source_url="https://www.lixiang.com")]  # fmt: skip
    lu = lineup.validate("Li Auto", entries, DOCS, "lixiang.com", "CN")
    assert [m.model for m in lu.models] == ["L9", "L6"] and all(m.price_from_eur is None for m in lu.models)
    news = [LineupEntry(model="L9", source_url="https://news.example/li-auto")]
    assert not lineup.validate("Li Auto", news, DOCS, None, "CN").models  # a news page alone is not a line-up
    assert lineup.validate("Li Auto", news, DOCS, None, "CN", ("news.example",)).models


@dataclass
class _Hit:
    url: str
    title: str = ""
    snippet: str = ""


@dataclass
class _Search:
    queries: list[tuple[str, str]]

    async def search(self, query: str, *, market: str = "ES", area: str | None = None, fresh: bool = False):
        self.queries.append((query, market))
        return [_Hit(url=f"https://{market.lower()}.example/{len(self.queries)}")]

    async def get(self, url: str, *, area: str | None = None):
        return None


class _Registry:
    async def sources_for(self, area: str, markets: list[str], limit: int) -> list[PlannedSource]:
        return [PlannedSource(domain=d, market="CN", priority=i, status="candidate")
                for i, d in enumerate(["price.pcauto.com.cn", "d1ev.com", "16888.com", "k.autohome.com.cn",
                                       "chexun.com"])][:limit]  # fmt: skip


@dataclass
class _Ref:
    search: dict


@dataclass
class _Ports:
    search: _Search
    ref: _Ref
    registry: object = None

    @property
    def page_store(self) -> _Search:
        return self.search


async def test_resolver_hints_search_the_market_and_its_open_spec_sources() -> None:
    ports = _Ports(_Search([]), _Ref(search_config()), _Registry())
    hints = await readers.generation_hints(ports, "Deepal S09", market="CN")  # type: ignore[arg-type]
    markets = [m for _, m in ports.search.queries]
    assert markets[0] == "EN" and "CN" in markets
    site = next(q for q, _ in ports.search.queries if "site:" in q)
    # the registry's Chinese spec sources, without those whose terms forbid commercial use
    assert "site:d1ev.com" in site and "site:16888.com" in site and "pcauto" not in site and "autohome" not in site
    assert all(isinstance(h, WebHint) for h in hints) and hints[0].url.startswith("https://cn.")
    # Spain stays as it was: one English search, no market search
    es = _Ports(_Search([]), _Ref(search_config()), _Registry())
    await readers.generation_hints(es, "Toyota RAV4")  # type: ignore[arg-type]
    assert [m for _, m in es.search.queries] == ["EN"]


def test_phrases_name_the_market_in_every_language() -> None:
    for key in ("sold_in_europe", "sold_abroad", "abroad_no_price", "abroad_priced"):
        assert set(PHRASES[key]) >= {"en", "ru", "es"}
    assert (
        market_name("CN", "ru") == "Китая" and market_name("PL", "ru") == "Польши" and market_name("XX", "ru") == "XX"
    )
    assert t("sold_in_europe", "ru", car="Deepal S09", market=market_name("PL", "ru")).startswith(
        "Deepal S09 в Испании не продаётся — нашёл на рынке Польши"
    )
    assert t("sold_abroad", "ru", car="Deepal S09", market=market_name("CN", "ru")).startswith(
        "Deepal S09 в Европе не продаётся — нашёл на рынке Китая"
    )
    assert "no price in euros" in t("abroad_no_price", "en", car="Deepal S09", market="China")
