"""Spec 010 US7 (T064): admission verdicts. Pure."""

from automind.acquisition.registry.domain.admission import AdmissionFacts, admit

DENY = ("coches.net",)


def f(**kw: object) -> AdmissionFacts:
    base: dict[str, object] = {
        "domain": "site.example",
        "robots_allows": True,
        "terms_forbid": False,
        "content_chars": 5000,
    }
    base.update(kw)
    return AdmissionFacts(**base)  # type: ignore[arg-type]


def test_verdicts_in_order():
    assert admit(f(domain="coches.net"), DENY).access == "classifieds"
    assert admit(f(title="Anuncios de coches usados"), DENY).access == "classifieds"
    assert admit(f(robots_allows=False), DENY).access == "robots_blocked"
    t = admit(f(terms_forbid=True, clause="Queda prohibida la extracción automatizada", terms_url="https://s/t"), DENY)
    assert t.access == "terms_forbid" and "prohibida" in t.evidence["clause"]
    assert admit(f(terms_forbid=True, clause=None), DENY).access == "ok"  # a verdict without a quote is not proof
    assert admit(f(content_chars=100), DENY).access == "js_only"
    assert admit(f(robots_allows=None), DENY).access == "unknown"
    assert admit(f(terms_forbid=None), DENY).access == "unknown"
    assert admit(f(), DENY).access == "ok"
