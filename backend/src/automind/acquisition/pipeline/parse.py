"""S4 parse (spec 011 strangler, research R5): the deterministic site readers on the job's pages (the running parser
spec version of each site, `parsing/registry.py`); ambiguous or unknown layouts go to the extraction role
(`parsing/extraction/`). Moved from `application/research.py`.
"""

from __future__ import annotations

from typing import Any

from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.ports import AcqPorts
from automind.shared.contracts.web import Page

VERSION = "parse@1"


async def read_tables(ports: AcqPorts, v: VariantFacts, pages: list[Page]) -> dict[str, Any]:
    """The site readers' tables of the pages, by URL (favourite spec sites); a page whose layout is ambiguous or
    unknown is left out (the extraction role reads it)."""
    prepare = getattr(ports.readers, "prepare", None)
    if prepare is not None:
        await prepare()  # the live registry reloads the running parser versions every 60 s
    readings: dict[str, Any] = {}
    for p in pages:
        r = ports.readers.read(p, {"variant_id": v.id})
        if r is not None and not r.ambiguous:
            readings[p.url] = r
    flush = getattr(ports.readers, "flush_stats", None)
    if flush is not None:
        await flush()
    return readings
