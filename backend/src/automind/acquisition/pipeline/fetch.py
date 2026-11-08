"""S3 fetch (spec 011 strangler, research R5): the ranked URLs through the page store — cache-first, under the fetch
policy (deny-list, robots, rate, size) — best first until the job's page limit; refusals are counted by reason.
Moved from `application/research.py` (the page half of `_collect`) with the body unchanged.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from automind.shared.contracts.web import Page
from automind.shared.metering.usage import BudgetExceeded

VERSION = "fetch@1"


async def pages(store: Any, order: list[str], area: str, limit: int) -> tuple[list[Page], dict[str, int]]:
    """The ranked URLs through the page store, best first, until `limit` pages (R3, R4)."""
    pages: list[Page] = []
    rejected: dict[str, int] = defaultdict(int)
    pos = 0
    while len(pages) < limit and pos < len(order) and pos < 2 * limit:
        batch = order[pos : pos + (limit - len(pages))]
        pos += len(batch)
        got = await asyncio.gather(*(store.get(u, area=area) for u in batch), return_exceptions=True)
        for u, g in zip(batch, got, strict=True):
            if isinstance(g, BudgetExceeded):
                raise g
            if isinstance(g, Page):
                pages.append(g)
            else:
                reason = store.last_reason(u) if not isinstance(g, BaseException) else type(g).__name__
                rejected[_reason_key(reason)] += 1
    return pages, rejected


def _reason_key(reason: str | None) -> str:
    r = (reason or "error").lower()
    for k in ("deny-list", "robots", "no content", "content type", "larger than", "http 4", "http 5"):
        if k in r:
            return k.replace(" ", "_")
    return "fetch_error"
