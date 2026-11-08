"""A market area's pages (spec 006 US5): pages are about the market, not the car, so no relevance gate; the
extraction role reads each page and every fact needs a verbatim excerpt with its amount (`market.accept`); accepted
facts are stored once per market and key through the `market_facts` port (none stored without it).

Errors: BudgetExceeded propagates (the job stops); a failing extraction drops that page only; a store failure
propagates (the job fails)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, cast

from automind.acquisition.parsing.extraction import extract as ex
from automind.acquisition.parsing.extraction.contracts import IncentiveFacts
from automind.acquisition.pipeline import market
from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.pipeline.persist import evidence_in
from automind.acquisition.pipeline.relevance import llm_per_job
from automind.acquisition.ports import AcqPorts
from automind.shared import evidence as ev
from automind.shared.contracts.web import Page
from automind.shared.metering.usage import BudgetExceeded

MARKET_TARGET = "Spain (ES market)"


@dataclass
class MarketTally:
    """What a market area's pages gave: pages read, accepted and rejected facts, accepted facts per domain."""

    docs: int = 0
    accepted: int = 0
    rejected: int = 0
    domains: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def hits(self) -> list[dict[str, Any]]:
        """The accepted facts per source domain (input to the section minimum)."""
        return [{"domain": dm, "source_type": "PUBLICATION", "items": n} for dm, n in self.domains.items()]


async def read_market_pages(ports: AcqPorts, v: VariantFacts, area: str, pages: list[Page]) -> MarketTally:
    """Read every page for the market (the variant only names the job's evidence); returns what they gave."""
    tally = MarketTally()
    sem = asyncio.Semaphore(llm_per_job(ports))

    async def one(p: Page) -> None:
        d = p.as_doc()
        try:
            async with sem:
                out = await ex.extract(ports.llm, ports.ref.prompts, area, MARKET_TARGET, d)
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 - one failing source never fails the job
            return
        if out is None:
            return
        tally.docs += 1
        rows, rj = market.accept(cast(IncentiveFacts, out), d)  # the market areas' schema (extract.schema_for)
        a = 0
        if rows and ports.market_facts is not None:
            evidence_id = await ports.stores.evidence.save(evidence_in(v, d, p))
            a = await ports.market_facts.upsert(rows, evidence_id)
        tally.accepted += a
        tally.rejected += rj
        if a:
            tally.domains[ev.domain_of(d.url)] += a

    await asyncio.gather(*(one(p) for p in pages))
    return tally
