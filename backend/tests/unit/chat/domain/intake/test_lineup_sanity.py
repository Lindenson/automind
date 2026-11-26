"""Spec 013 T014/T015: a line-up that is not the make's range is neither stored nor used, and the audit lists it."""

from __future__ import annotations

from automind.acquisition.api import StoredLineup
from automind.chat.application.services.identification.lineup import validate
from automind.chat.domain.intake.lineup_sanity import LineupFault, is_article, lineup_fault
from automind.delivery.cli.lineups import faulty

ARTICLE = (
    "https://www.autonocion.com/maldito-dinero-todos-los-precios-del-nuevo-mercedes-benz-clase-s-hasta-287-100-euros/"
)
PRICES = "https://www.quecochemecompro.com/precios/hyundai/"
PUB = [{"url": ARTICLE, "type": "PUBLICATION"}]


def test_the_chat_d170b861_line_up_is_rejected() -> None:
    assert lineup_fault([ARTICLE], PUB) is LineupFault.TOO_FEW


def test_five_models_from_one_article_are_rejected() -> None:
    assert lineup_fault([ARTICLE] * 5, PUB) is LineupFault.ONE_ARTICLE


def test_a_make_price_list_is_a_range() -> None:
    assert lineup_fault([PRICES] * 12, [{"url": PRICES, "type": "PUBLICATION"}]) is None
    assert not is_article(PRICES)


def test_the_makers_site_is_the_range_however_short() -> None:
    official = [{"url": "https://www.deepal.pl", "type": "MANUFACTURER"}]
    assert lineup_fault(["https://www.deepal.pl/s07"] * 3, official) is None


def test_the_min_models_is_configurable() -> None:
    urls = ["https://a.es/x", "https://b.es/y", "https://b.es/z"]
    assert lineup_fault(urls, [{"type": "PUBLICATION"}], min_models=3) is None
    assert lineup_fault(urls, [{"type": "PUBLICATION"}], min_models=5) is LineupFault.TOO_FEW


def test_validate_keeps_nothing_from_an_article() -> None:
    from automind.acquisition.api import LineupEntry

    entry = LineupEntry(model="Clase S", body="sedan", powertrains=["petrol"], price_from_eur=97350,
                        excerpt="desde 97.350 euros", source_url=ARTICLE)  # fmt: skip
    docs = {ARTICLE: ("Precios del nuevo Mercedes-Benz Clase S", "El Clase S cuesta desde 97.350 euros.")}
    assert validate("Mercedes-Benz", [entry], docs, official="mercedes-benz.es").models == []


def test_the_audit_lists_the_faulty_line_ups() -> None:
    bad = StoredLineup(make="Mercedes-Benz", models=[{"model": "Clase S", "source_url": ARTICLE}], sources=PUB)
    good = StoredLineup(make="Hyundai", models=[{"model": f"M{i}", "source_url": PRICES} for i in range(6)],
                        sources=[{"url": PRICES, "type": "PUBLICATION"}])  # fmt: skip
    found = faulty([bad, good], 5)
    assert [f.lineup.make for f in found] == ["Mercedes-Benz"]
    assert "too_few_models" in found[0].line() and "Clase S" in found[0].line()
