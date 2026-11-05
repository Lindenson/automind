"""S4 parse (spec 011 strangler, research R5): the deterministic site readers on the job's pages (the running parser
spec version of each site, `parsing/registry.py`); ambiguous or unknown layouts go to the extraction role
(`pipeline/extract.py`). Moved from `application/research.py`.
"""

from __future__ import annotations

from typing import Any

from automind.application.ports import Page, Ports
from automind.infrastructure import db

VERSION = "parse@1"


async def _read_tables(ports: Ports, v: db.Variant, pages: list[Page]) -> dict[str, Any]:
    """Deterministic site readers for favourite spec sites; ambiguous or unknown layouts go to the LLM."""
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
