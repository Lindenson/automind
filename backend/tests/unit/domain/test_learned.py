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
