"""Where a value comes from: the source policy (deny-list, official domains, favourites types), the type of a source,
and the provenance class a source type gives (constitution I, IV; FR-030)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

RULES_VERSION = "1.0"


# Authority order, high -> low (FR-017)
AUTHORITY = ["MANUFACTURER", "INSTRUMENTED_TEST", "PUBLICATION", "ENCYCLOPEDIA", "SPEC_DATABASE"]


@dataclass(frozen=True)
class SourcePolicy:
    """Source typing and deny-list, loaded from `config/sources.yaml` by the infrastructure layer."""

    manufacturer_markers: tuple[str, ...]
    instrumented: tuple[str, ...]
    encyclopedia: tuple[str, ...]
    spec_db: tuple[str, ...]
    denylist: tuple[str, ...]
    non_manufacturer_hints: tuple[str, ...] = ()
    # Official maker domains (registrable host, e.g. "toyota.es", "seat-cupra-mediacenter.es"): the only hosts,
    # with a host whose registrable name is exactly a brand (bmw.com.sg, owners-manual.mazda.com), typed as
    # MANUFACTURER. A brand inside a longer name (toyota-club.net, clubseat.es, hondapartsnow.com) is not.
    official_domains: tuple[str, ...] = ()
    # The source_type an operator gave a favourite site (km77.com: SPEC_DATABASE), checked first.
    typed_domains: tuple[tuple[str, str], ...] = ()


_policy: SourcePolicy | None = None


def configure(policy: SourcePolicy) -> None:
    """Install the source policy (called once at startup and in test setup)."""
    global _policy
    _policy = policy


def policy() -> SourcePolicy:
    if _policy is None:
        raise RuntimeError("source policy not configured: call evidence.configure() at startup")
    return _policy


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_denied(url: str) -> bool:
    d = domain_of(url)
    full = d + (urlparse(url).path or "")
    return any(x in full for x in policy().denylist)


_SECOND_LEVEL = {"co", "com", "org", "net", "gob", "gov", "ac", "or", "ne"}


def _on(d: str, dom: str) -> bool:
    """The host is the domain or one of its subdomains (never "fooautobild.de" for "autobild.de")."""
    return d == dom or d.endswith("." + dom)


def registrable_name(d: str) -> str:
    """The name under the public suffix: "bmw" for bmw.com.sg, "mazda" for owners-manual.mazda.com."""
    labels = [x for x in d.split(".") if x]
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return labels[-3]
    return labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")


def is_official(url: str) -> bool:
    """A maker's own site: listed as official, or the registrable name (or a brand TLD such as .seat) is exactly
    a brand (spec 001 FR-017; reviewer 2026-11-03: fan clubs, dealers and part shops were typed MANUFACTURER)."""
    d = domain_of(url)
    p = policy()
    if any(_on(d, o) for o in p.official_domains):
        return True
    brands = {m.strip(".").replace("-", "") for m in p.manufacturer_markers}
    name = registrable_name(d).replace("-", "")
    tld = d.rsplit(".", 1)[-1]
    return name in brands or tld in brands


def classify_source(url: str) -> str:
    d = domain_of(url)
    p = policy()
    for dom, kind in p.typed_domains:
        if _on(d, dom):
            return kind
    if any(_on(d, x) for x in p.encyclopedia):
        return "ENCYCLOPEDIA"
    if any(_on(d, x) for x in p.spec_db):
        return "SPEC_DATABASE"
    if any(_on(d, x) for x in p.instrumented):
        return "INSTRUMENTED_TEST"
    if is_official(url):
        return "MANUFACTURER"
    return "PUBLICATION"


def assign_provenance(source_type: str, attribute: str) -> str:
    if source_type == "MANUFACTURER":
        return "MANUFACTURER_CLAIM"
    if source_type == "INSTRUMENTED_TEST" and attribute.startswith("measured_"):
        return "MEASURED"
    return "SOURCED_FACT"
