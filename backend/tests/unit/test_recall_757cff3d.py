"""Replay of the German-car searches of chat 757cff3d (spec 007 US5, SC-006), offline, on the real config.

A `site:` query needs every word on the page. The fake search below models exactly that: a site answers when
all words of the query (without the `site:` part) occur in its page. On 2026-11-03 round 0 asked for
"Volkswagen Golf Mk8.5 Golf Variant R 2.0 TSI 333 CV DSG 4MOTION …" and found nothing.
"""

from types import SimpleNamespace

import pytest

from automind.acquisition.pipeline.plan import queries_for
from automind.infrastructure.config import reference

GOLF = SimpleNamespace(make="Volkswagen", model="Golf", generation="Mk8.5",
                       variant_name="Golf Variant R 2.0 TSI 333 CV DSG 4MOTION",
                       generation_years_from=2024, generation_years_to=None)  # fmt: skip
BMW = SimpleNamespace(make="BMW", model="3 Series", generation="G21", variant_name="320d Touring M Sport Steptronic",
                      generation_years_from=2019, generation_years_to=None)  # fmt: skip

# what such pages write (titles and first lines of real test and data pages)
PAGES = {
    "de": "volkswagen golf variant r 333 ps test messwerte technische daten pannenstatistik mängel bmw 320d touring "
          "3 series",
    "es": "volkswagen golf variant r 333 cv prueba 0-100 ficha técnica fiabilidad problemas bmw 320d touring 3 series",
    "en": "volkswagen golf variant r 333 test 0-60 specs reliability problems review bmw 320d touring 3 series",
}  # fmt: skip


def _found(text: str) -> bool:
    words = [w.lower() for w in text.split() if not w.startswith("site:") and w != "OR"]
    lang = "de" if "site:" in text and any(s.endswith(".de") for s in text.split()) else None
    pages = [PAGES[lang]] if lang else list(PAGES.values())
    return any(all(w in p for w in words) for p in pages)


@pytest.fixture(scope="module")
def ports():
    return SimpleNamespace(ref=reference({}))


@pytest.mark.parametrize("car", [GOLF, BMW], ids=["golf", "bmw"])
@pytest.mark.parametrize("area", ["specs", "measured", "reliability"])
def test_round0_finds_pages_for_both_cars(ports, car, area):
    qs = queries_for(ports, car, area, 0, [])
    assert qs, area
    for q in qs:
        words = q.text.lower().split()
        assert "mk8.5" not in words and "g21" not in words and "dsg" not in words, q.text
        plain = [w for w in words if not w.startswith("site:") and w != "or"]
        assert len(plain) == len(set(plain)), q.text  # no repeated words ("Golf … Golf")
    assert any(_found(q.text) for q in qs), [q.text for q in qs]


def test_german_sites_get_german_words(ports):
    de = [q for q in queries_for(ports, GOLF, "reliability", 0, []) if q.market == "DE"]
    assert de and all("Pannenstatistik" in q.text for q in de)
    es = [q for q in queries_for(ports, GOLF, "reliability", 0, []) if q.market == "ES"]
    assert es and all("fiabilidad" in q.text and "reliability" not in q.text for q in es)
