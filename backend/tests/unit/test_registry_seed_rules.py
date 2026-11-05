"""Spec 010 US8 (T048): seeding the registry from favourites and the 009 survey. Pure."""

from __future__ import annotations

from automind.acquisition.registry.domain.seed_rules import (
    AREA_OF_KIND,
    from_favourite,
    from_survey,
    market_of,
)

DENY = ("coches.net", "wallapop.com")


def test_survey_verdicts_map_to_status_with_evidence():
    e = {
        "domain": "alvolante.it",
        "country": "IT",
        "lang": "it",
        "kinds": ["new_price", "used_price", "owner_reviews"],
        "verdict": "tos_forbids",
        "tos": "'Sono vietate…' (https://www.alvolante.it/condizioni_uso)",
        "checked": "2026-11-05",
    }
    src, caps = from_survey(e, DENY)
    assert src.access == "terms_forbid" and "vietate" in src.access_evidence["clause"]
    assert {c.status for c in caps} == {"blocked"} and {c.area for c in caps} == {"price", "used_price", "reviews"}
    assert {c.market for c in caps} == {"IT"}
    ok, ok_caps = from_survey({**e, "domain": "motor.es", "country": "ES", "verdict": "candidate", "tos": ""}, DENY)
    assert ok.access == "ok" and {c.status for c in ok_caps} == {"candidate"}
    for verdict, access, status in (
        ("classifieds", "classifieds", "blocked"),
        ("blocked_robots", "robots_blocked", "blocked"),
        ("paywall", "paywall", "retired"),
        ("js_only", "js_only", "retired"),
        ("dead", "dead", "retired"),
    ):
        s, cs = from_survey({**e, "verdict": verdict}, DENY)
        assert s.access == access and {c.status for c in cs} == {status}


def test_deny_list_always_wins():
    s, caps = from_survey(
        {"domain": "coches.net", "country": "ES", "kinds": ["used_price"], "verdict": "candidate"}, DENY
    )
    assert s.access == "classifieds" and {c.status for c in caps} == {"blocked"}
    f, fcaps = from_favourite(
        {"domain": "wallapop.com", "source_type": "PUBLICATION", "areas": ["specs"], "markets": ["ES"], "priority": 1},
        DENY,
    )
    assert {c.status for c in fcaps} == {"blocked"}


def test_favourites_are_active_with_seed_priority():
    s, caps = from_favourite(
        {
            "domain": "km77.com",
            "source_type": "SPEC_DATABASE",
            "areas": ["specs", "price"],
            "markets": ["ES"],
            "priority": 1,
            "reader": "km77",
        },
        DENY,
    )
    assert s.source_type == "SPEC_DATABASE" and s.reader == "km77"
    assert {(c.area, c.market, c.status, c.priority_seed) for c in caps} == {
        ("specs", "ES", "active", 1),
        ("price", "ES", "active", 1),
    }


def test_kind_and_market_mapping():
    assert AREA_OF_KIND["residual_value"] == "depreciation" and AREA_OF_KIND["warranty"] == "manufacturer"
    assert (
        market_of("GB") == "EN" and market_of("AT") == "DE" and market_of("EU") == "ANY" and market_of(False) == "ANY"
    )
