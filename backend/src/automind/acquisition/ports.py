"""The engine's ports (spec 011 contracts/acquire.md "Ports"): what the pipeline needs from outside — model access,
reference data, search, the page store, site readers, the source registry, metrics, the market facts store and
the pipeline's own stores (`stores`: variants, evidence, values, verdicts, the job book). Built by
`acquisition/infrastructure/wiring.py: live_acq_ports()`; tests pass fakes. The chat's `application/ports.py: Ports`
has none of search, pages or readers: it reaches the engine through `Ports.acquisition` (strangler S8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from automind.acquisition.identity_readers.application.ports import LiveRows
from automind.acquisition.pipeline.application.ports import PipelineStores
from automind.acquisition.registry.api import RegistryPort
from automind.shared.contracts.config import Reference
from automind.shared.contracts.llm import LLM
from automind.shared.contracts.site_readers import NoReaders, SiteReaders
from automind.shared.contracts.web import PageStore, Searcher


class ShadowFeed(Protocol):
    """The shadow gate's feed: pages the extractor read while a prompt or model change is in shadow."""

    async def notify_extracted(self, prompt_name: str | None, snapshot_ids: list[str]) -> int:
        """Queue the pages for the shadow comparison (no work in the turn); returns how many were queued."""
        ...


@dataclass
class AcqPorts:
    llm: LLM
    ref: Reference
    search: Searcher
    stores: PipelineStores
    pages: PageStore | None = None  # None → `search` also implements PageStore (test fakes)
    readers: SiteReaders = field(default_factory=NoReaders)
    registry: RegistryPort | None = None  # None: config order only
    metrics: Any = None  # inc(name, **labels) for Prometheus counters; None: not counted
    market_facts: Any = None  # spec 006 US5: upsert(rows, evidence_id); None: market areas store nothing
    datasets: LiveRows | None = None  # a live open-dataset query of a make; None: stored/cached only
    shadow: ShadowFeed | None = None  # spec 011 T102: the shadow gate's feed; None: pages feed no shadow

    @property
    def page_store(self) -> PageStore:
        return self.pages if self.pages is not None else self.search  # type: ignore[return-value]
