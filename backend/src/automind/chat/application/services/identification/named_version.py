"""A version the person names that the sourced list lacks (spec 017 V2; chat 725e7437: the 320d was in the dealer's
table but not in the list the `versions` reader made of it): searched for on its own before anyone says it does not
exist. A sourced list says what exists; it never proves that a named version does not.

Errors: the search, page store and model errors pass through (the caller keeps the list as it is)."""

from __future__ import annotations

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.versions import validate
from automind.chat.domain.identification.ladder import Generation, Wanted, cv_label, narrow

NAMED_READ_PAGES = 4  # a search for one named version: pages read, and kept
NAMED_KEPT_PAGES = 2


def named_engine(w: Wanted) -> Wanted | None:
    """The engine the person named (family, power, fuel) — what a sourced list is checked against; None when they
    named no family and no power."""
    if not (w.family or w.power_kw):
        return None
    return Wanted(fuel=w.fuel, family=w.family, power_kw=w.power_kw)


def lacks(g: Generation, named: Wanted) -> bool:
    """The list has no version with the named family or power."""
    return bool(narrow(g.versions, named).missing)


def named_query(g: Generation, named: Wanted, year: int | None) -> str:
    """ "BMW 3 Series 320d 190 CV 2024": the named version, on its own."""
    parts = (g.make, g.model, named.family, cv_label(named.power_kw) if named.power_kw else None, year and str(year))
    return " ".join(str(x) for x in parts if x)


async def find_named(ports: Ports, g: Generation, named: Wanted, year: int | None) -> Generation:
    """The person named a version the sourced list lacks (spec 017 V2; chat 725e7437: the 320d was in the dealer's
    table but not in the list read from it): one search for that version, its own data pages read; the versions
    found that match are added to the cached list. A list is never taken as the proof that a named version does
    not exist before this search. `g` unchanged when nothing is found or there is no engine."""
    if ports.acquisition is None or not lacks(g, named):
        return g
    lim = {**dict(ports.ref.search["intake"]), "versions_one_version": True, "versions_read_pages": NAMED_READ_PAGES,
           "versions_max_pages": NAMED_KEPT_PAGES}  # fmt: skip
    q = named_query(g, named, year)
    got = await ports.acquisition.versions(g.make, g.model, g.generation, year=year, limits=lim, done=set(),
                                           queries=[f"{q} ficha técnica", f"{q} precio versiones"])  # fmt: skip
    found = [v for v in validate(got.out, got.docs) if not narrow([v], named).missing] if got else []
    have = {v.engine_key for v in g.versions}
    add = [v for v in found if v.engine_key not in have]
    if not add:
        return g
    srcs = [*g.sources, *({"url": v.source_url, "name": got.docs[v.source_url][0] or v.source_url}
                          for v in add if got and v.source_url in got.docs)]  # fmt: skip
    merged = Generation(g.make, g.model, g.generation, g.years_from, g.years_to, g.body_class, [*g.versions, *add],
                        srcs)  # fmt: skip
    if ports.versions is not None and not any(s.get("dataset") for s in g.sources):  # registrations are not cached
        await ports.versions.put(merged)
    return merged
