"""A search for identification that never fails the turn: no provider able to answer (no key, no credit, a refused
request) gives no hits, and identification goes on with what it has (pre-prod 2026-11-08: Serper "Not enough
credits" failed the whole turn)."""

from __future__ import annotations

import logging

from automind.acquisition.ports import AcqPorts
from automind.shared.contracts.web import SearchHit, SearchUnavailable

log = logging.getLogger(__name__)


async def search_hits(ports: AcqPorts, query: str, *, market: str, area: str) -> list[SearchHit]:
    """The hits of a search; none when no provider can answer (logged)."""
    try:
        return await ports.search.search(query, market=market, area=area)
    except SearchUnavailable as e:
        log.warning("identity.search_unavailable area=%s market=%s: %s", area, market, e)
        return []
