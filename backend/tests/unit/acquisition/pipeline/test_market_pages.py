"""`read_market_pages` over fakes: a fact with its amount in a verbatim excerpt is stored once with the page's
evidence; a fact without it is rejected; a failing extraction drops that page only; an exhausted budget propagates."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from automind.acquisition.parsing.extraction.contracts import IncentiveEntry, IncentiveFacts
from automind.acquisition.pipeline.stages.market_pages import MARKET_TARGET, read_market_pages
from automind.shared.contracts.web import Page
from automind.shared.metering.usage import BudgetExceeded

SAID = "El Plan MOVES III ofrece hasta 7.000 euros para la compra de un coche eléctrico nuevo."
GOOD = Page(url="https://www.idae.es/moves", title="MOVES III", text=f"Ayudas. {SAID} Hasta fin de año.")
OTHER = Page(url="https://blog.example.es/ayudas", title="Ayudas", text="Hay ayudas para coches eléctricos este año.")
BROKEN = Page(url="https://broken.example.es/x", title="x", text="x")


def _fact(amount: float, excerpt: str) -> IncentiveEntry:
    return IncentiveEntry(key="subsidy.purchase", label="Plan MOVES III", amount_eur=amount, excerpt=excerpt)


class _LLM:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.targets: list[bool] = []

    async def structured(self, role: str, schema: type[BaseModel], prompt: str, user: str) -> BaseModel:
        self.targets.append(MARKET_TARGET in user)
        if self.fail is not None:
            raise self.fail
        if GOOD.url in user:
            return IncentiveFacts(facts=[_fact(7000, SAID)])
        if BROKEN.url in user:
            raise RuntimeError("model down")
        return IncentiveFacts(facts=[_fact(9000, "Hay ayudas para coches eléctricos este año.")])


class _Evidence:
    def __init__(self) -> None:
        self.saved: list[Any] = []

    async def save(self, evidence: Any, rows: Any = ()) -> str:
        self.saved.append(evidence)
        return f"e{len(self.saved)}"


class _Facts:
    def __init__(self) -> None:
        self.rows: list[tuple[str, list[dict[str, Any]]]] = []

    async def upsert(self, rows: list[dict[str, Any]], evidence_id: str) -> int:
        self.rows.append((evidence_id, rows))
        return len(rows)


def _ports(llm: _LLM) -> Any:
    ref = SimpleNamespace(prompts={"extract_incentives": "p"}, search={})
    return SimpleNamespace(llm=llm, ref=ref, stores=SimpleNamespace(evidence=_Evidence()), market_facts=_Facts())


VARIANT: Any = SimpleNamespace(id="v1")  # the variant only names the evidence


async def test_a_fact_with_its_amount_in_the_excerpt_is_stored_with_the_page_evidence() -> None:
    llm = _LLM()
    ports = _ports(llm)
    tally = await read_market_pages(ports, VARIANT, "incentives", [GOOD, OTHER, BROKEN])
    assert (tally.docs, tally.accepted, tally.rejected) == (2, 1, 1)  # the broken page is dropped, not counted
    assert tally.hits() == [{"domain": "idae.es", "source_type": "PUBLICATION", "items": 1}]
    assert [e.url for e in ports.stores.evidence.saved] == [GOOD.url]
    ((evidence_id, rows),) = ports.market_facts.rows
    assert evidence_id == "e1" and rows[0]["key"] == "subsidy.purchase" and rows[0]["value"]["amount_eur"] == 7000
    assert all(llm.targets)  # the extractor is told the market, not a car


async def test_an_exhausted_budget_stops_the_market_area() -> None:
    with pytest.raises(BudgetExceeded):
        await read_market_pages(_ports(_LLM(BudgetExceeded("llm", "spent"))), VARIANT, "incentives", [GOOD])
