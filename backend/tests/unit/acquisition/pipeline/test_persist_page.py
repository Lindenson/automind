"""A page of a non-spec area becomes its evidence and rows in one store call; a store failure propagates (the job
fails, nothing is counted as stored)."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

import pytest

from automind.acquisition.pipeline import persist
from automind.acquisition.pipeline.application.ports import PipelineStoreUnavailable
from automind.acquisition.pipeline.domain.rows import EvidenceIn, PageRow, ReviewRow
from automind.acquisition.pipeline.domain.variant import CarVariant
from automind.acquisition.pipeline.extract import ReviewEntry, ReviewItems
from automind.shared.contracts.web import WebDoc

CAR = CarVariant("v1", "Hyundai", "Tucson", "NX4", "1.6 T-GDI 150", "MHEV", "SUV", 2021, None, None, None, "ES")
TEXT = "El Tucson es muy cómodo en autopista. El maletero se queda corto."


class FakeEvidence:
    def __init__(self, down: bool = False) -> None:
        self.down = down
        self.saved: list[tuple[EvidenceIn, list[PageRow]]] = []

    async def save(self, evidence: EvidenceIn, rows: Sequence[PageRow] = ()) -> str:
        if self.down:
            raise PipelineStoreUnavailable("save: OperationalError")
        self.saved.append((evidence, list(rows)))
        return "e1"


def _ports(store: FakeEvidence) -> SimpleNamespace:
    ref = SimpleNamespace(feasibility={}, manufacturer_sites={}, favourites=[])
    return SimpleNamespace(ref=ref, stores=SimpleNamespace(evidence=store))


def _reviews() -> ReviewItems:
    return ReviewItems(is_about_variant=True, items=[
        ReviewEntry(polarity="PRO", tag="comfort", reviewer="EXPERT", text="cómodo", excerpt="muy cómodo en autopista"),
        ReviewEntry(polarity="CON", tag="practicality", reviewer="EXPERT", text="maletero",
                    excerpt="no está en la página"),
    ])  # fmt: skip


async def test_reviews_with_their_excerpt_on_the_page_are_stored_with_the_evidence() -> None:
    store = FakeEvidence()
    doc = WebDoc("https://www.km77.com/tucson", "Prueba Tucson", TEXT, False)
    got = await persist.persist_extraction(_ports(store), CAR, "reviews", doc, _reviews(), "target", False)  # type: ignore[arg-type]
    assert got == (1, 1)
    evidence, rows = store.saved[0]
    assert evidence.domain == "km77.com" and evidence.variant_id == "v1"
    assert [type(r) for r in rows] == [ReviewRow]


async def test_store_down_propagates() -> None:
    doc = WebDoc("https://www.km77.com/tucson", "Prueba Tucson", TEXT, False)
    with pytest.raises(PipelineStoreUnavailable):
        await persist.persist_extraction(_ports(FakeEvidence(down=True)), CAR, "reviews", doc, _reviews(), "t", False)  # type: ignore[arg-type]
