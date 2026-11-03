"""Evidence rules: source typing, excerpt validation, provenance, conflict resolution, confidence.

Implements spec 001 FR-009, FR-015, FR-017, FR-018 (rules v1.0) as pure functions.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .specs import ATTRS

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


_MARKUP = re.compile(r"\\(?=[*_#|\\`\[\]()-])|[*#|`]+|(?<!\w)_+|_+(?!\w)")
_GAP = re.compile(r"\s*(?:\.\.\.|…|\[\.\.\.\])\s*")


def _norm(text: str) -> str:
    """Text for literal comparison: Unicode-normalised, lower case, without markdown markup (bold, headings,
    table pipes, escapes) and with collapsed whitespace. Page text is stored as markdown; models quote the
    rendered words (user report 2026-11-02: the Tucson price "**36.075 euros**" failed the excerpt check)."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = t.replace("\u00a0", " ").replace("\u202f", " ")
    t = _MARKUP.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def occurs(excerpt: str, document_text: str) -> bool:
    """The excerpt occurs in the document; an ellipsis in the excerpt ("Klass ... Precio") skips text, and
    the parts must occur in order."""
    doc = _norm(document_text)
    parts = [_norm(p) for p in _GAP.split(excerpt)]
    parts = [p for p in parts if p]
    pos = 0
    for p in parts:
        i = doc.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return bool(parts)


def validate_excerpt(excerpt: str, raw_value: str, document_text: str) -> bool:
    """The excerpt must literally occur in the document, and the raw value inside the excerpt."""
    ex = _norm(excerpt)
    if len(ex) < 4:
        return False
    if not occurs(excerpt, document_text):
        return False
    val = _norm(raw_value)
    if val in ex:
        return True
    digits = re.findall(r"\d+(?:[.,]\d+)?", val)
    return bool(digits) and all(d in ex for d in digits)


def assign_provenance(source_type: str, attribute: str) -> str:
    if source_type == "MANUFACTURER":
        return "MANUFACTURER_CLAIM"
    if source_type == "INSTRUMENTED_TEST" and attribute.startswith("measured_"):
        return "MEASURED"
    return "SOURCED_FACT"


@dataclass
class ClaimIn:
    claim_id: str
    attribute: str
    value: float | str
    source_type: str
    domain: str
    scope: str = "VARIANT"  # VARIANT | GENERATION | ENGINE


@dataclass
class Selected:
    attribute: str
    available: bool
    value: float | str | None = None
    provenance: str | None = None
    confidence: str | None = None
    confidence_rule: str | None = None
    claim_ids: list[str] = field(default_factory=list)
    conflict: bool = False
    resolution_rule: str | None = None
    alternatives: list[float | str] = field(default_factory=list)


def _agree(attr_key: str, a: float | str, b: float | str) -> bool:
    attr = ATTRS[attr_key]
    if attr.kind == "text" or isinstance(a, str) or isinstance(b, str):
        return str(a).strip().lower() == str(b).strip().lower() if attr.key == "drivetrain" else True
    if attr.tolerance == 0:
        return float(a) == float(b)
    ref = max(abs(float(a)), abs(float(b)), 1e-9)
    return abs(float(a) - float(b)) / ref <= attr.tolerance


def _clusters(attr_key: str, claims: list[ClaimIn]) -> list[list[ClaimIn]]:
    clusters: list[list[ClaimIn]] = []
    for c in claims:
        for cl in clusters:
            if _agree(attr_key, cl[0].value, c.value):
                cl.append(c)
                break
        else:
            clusters.append([c])
    return clusters


def select_value(attr_key: str, claims: list[ClaimIn]) -> Selected:
    """FR-017 resolution + FR-018 confidence for one attribute of one variant."""
    if not claims:
        return Selected(attr_key, available=False)
    claims = sorted(claims, key=lambda c: (AUTHORITY.index(c.source_type), c.claim_id))
    all_clusters = _clusters(attr_key, claims)
    conflict = len(all_clusters) > 1
    top_rank = claims[0].source_type
    top = [c for c in claims if c.source_type == top_rank]
    top_clusters = sorted(_clusters(attr_key, top), key=lambda cl: -len({c.domain for c in cl}))
    rule: str | None = None
    if len(top_clusters) == 1:
        winner = top_clusters[0]
        rule = "AUTHORITY_ORDER" if conflict else None
    elif len({c.domain for c in top_clusters[0]}) >= 2 and len({c.domain for c in top_clusters[0]}) > len(
        {c.domain for c in top_clusters[1]}
    ):
        winner = top_clusters[0]
        rule = "MAJORITY_SAME_RANK"
    else:
        alts = [cl[0].value for cl in all_clusters]
        return Selected(
            attr_key,
            True,
            value=top_clusters[0][0].value,
            provenance=assign_provenance(top_rank, attr_key),
            confidence="LOW",
            confidence_rule="LOW:UNRESOLVED_CONFLICT",
            claim_ids=[c.claim_id for c in claims],
            conflict=True,
            alternatives=alts,
        )
    value = winner[0].value
    supporting = [c for c in claims if _agree(attr_key, c.value, value)]
    domains = {c.domain for c in supporting}
    if all(c.scope != "VARIANT" for c in winner):
        conf, crule = "LOW", "LOW:INDIRECT_SCOPE"
    elif top_rank == "MANUFACTURER":
        conf, crule = "HIGH", "HIGH:MANUFACTURER"
    elif len(domains) >= 2:
        conf, crule = "HIGH", "HIGH:2_INDEPENDENT_AGREE"
    else:
        conf, crule = "MEDIUM", "MEDIUM:SINGLE_SOURCE"
    alts = [cl[0].value for cl in all_clusters if not _agree(attr_key, cl[0].value, value)]
    return Selected(
        attr_key,
        True,
        value=value,
        provenance=assign_provenance(top_rank, attr_key),
        confidence=conf,
        confidence_rule=crule,
        claim_ids=[c.claim_id for c in supporting],
        conflict=conflict,
        resolution_rule=rule,
        alternatives=alts,
    )


def select_all(claims: list[ClaimIn]) -> dict[str, Selected]:
    by_attr: dict[str, list[ClaimIn]] = defaultdict(list)
    for c in claims:
        by_attr[c.attribute].append(c)
    return {k: select_value(k, by_attr.get(k, [])) for k in ATTRS}


def _mentions(code: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(code.lower())}(?![A-Za-z0-9])", text) is not None


_CODE_RE = re.compile(r"^([a-z]+)\s?(\d+(?:\.\d)?)$")


def _sibling_code(generation: str, low: str) -> bool:
    """Another code of the same family on the page ("mk2" when the target is "Mk1", "j250" vs "J150")."""
    m = _CODE_RE.match(generation.strip().lower())
    if m is None:
        return False
    prefix, number = m.groups()
    found = re.findall(rf"(?<![a-z0-9]){prefix}\s?(\d+(?:\.\d)?)(?![a-z0-9])", low)
    width = len(number.split(".")[0])
    return any(n != number and len(n.split(".")[0]) == width for n in found)


def variant_match_uncertain(
    text: str,
    title: str,
    generation: str | None,
    other_generations: list[str],
    years: tuple[int | None, int | None] = (None, None),
) -> bool:
    """True when a page may not be about the target generation (→ validator role, constitution XI).

    Uncertain if the page names another generation of the same model, or names neither the target
    generation nor a year inside its production years.
    """
    low = f"{title}\n{text}".lower()
    if any(_mentions(g, low) for g in other_generations if g and g != generation):
        return True
    if generation and _sibling_code(generation, low):
        return True
    if generation and _mentions(generation, low):
        return False
    lo, hi = years
    if lo is not None:
        top = hi if hi is not None else lo + 15
        if any(str(y) in low for y in range(lo, top + 1)):
            return False
    return True
