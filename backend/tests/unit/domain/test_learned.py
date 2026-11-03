"""Learned sources (spec 007 US5, FR-022): promotion, expiry, never denied, never a false manufacturer."""

from automind.domain import learned
from automind.domain.learned import LearnedRow

CFG = learned.Config(min_runs=3, max_misses=5, per_area=4)


def test_promoted_after_min_runs_and_reset_misses():
    r = LearnedRow("autobild.de", "reliability", "DE", "PUBLICATION")
    for _ in range(2):
        r = learned.update_row(r, accepted=True)
    assert not learned.is_active(r, CFG, favourites=set())
    r = learned.update_row(learned.update_row(r, accepted=False), accepted=True)
    assert r.accepted_runs == 3 and r.misses == 0
    assert learned.is_active(r, CFG, favourites=set())


def test_expires_after_max_misses():
    r = LearnedRow("autobild.de", "reliability", "DE", "PUBLICATION", accepted_runs=5)
    for _ in range(5):
        r = learned.update_row(r, accepted=False)
    assert not learned.is_active(r, CFG, favourites=set())


def test_denied_and_configured_favourites_are_never_active():
    r = LearnedRow("milanuncios.com", "price", "ES", "PUBLICATION", accepted_runs=9)
    assert not learned.is_active(r, CFG, favourites=set())
    r = LearnedRow("km77.com", "specs", "ES", "SPEC_DATABASE", accepted_runs=9)
    assert not learned.is_active(r, CFG, favourites={"km77.com"})


def test_look_alike_brand_domain_is_never_manufacturer():
    assert learned.source_type_of("https://www.bmw-club.es/foro/320d") != "MANUFACTURER"
    assert learned.source_type_of("https://www.toyota-club.net/x") != "MANUFACTURER"


def test_domain_key_strips_www_and_keeps_subdomains():
    assert learned.domain_key("https://www.autobild.de/artikel/x") == "autobild.de"
    assert learned.domain_key("https://m.km77.com/x") == "m.km77.com"


# --- spec 007 J (T078): no self-reinforcement ---------------------------------------------------------------------


def test_acceptance_through_its_own_learned_query_is_neutral():
    r = learned.LearnedRow("site.es", "specs", "ES", "PUBLICATION", accepted_runs=3, misses=4)
    same = learned.update_row(r, accepted=True, independent=False)
    assert same == r  # no new run, the misses are not cleared
    expired = learned.update_row(same, accepted=False)
    assert not learned.is_active(expired, learned.Config(min_runs=3, max_misses=5), favourites=set())
    back = learned.update_row(r, accepted=True, independent=True)
    assert back.accepted_runs == 4 and back.misses == 0


async def test_only_searched_pages_count_and_learned_only_hits_are_not_independent():
    from types import SimpleNamespace

    from automind.application import research

    got = []

    class Store:
        async def record(self, area, outcomes):
            got.extend(outcomes)

    ports = SimpleNamespace(learned=Store())
    pages = [SimpleNamespace(url="https://a.es/x"), SimpleNamespace(url="https://b.es/y"),
             SimpleNamespace(url="https://pasted.es/z")]  # fmt: skip
    market = {"https://a.es/x": "ES", "https://b.es/y": "ES"}  # the pasted page was never a search hit
    accepted = {p.url: 1 for p in pages}
    await research._record_learned(ports, "specs", pages, accepted, market, independent={"https://a.es/x"})
    assert [(d, ok, ind) for d, _, ok, ind in got] == [("a.es", True, True), ("b.es", True, False)]
