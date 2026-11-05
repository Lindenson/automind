"""The engine's ports (spec 011 contracts/acquire.md "Ports"): what the pipeline needs from outside — model access,
reference data, search, the page store, site readers, the source registry, metrics and the market facts
store. Built by `acquisition/infrastructure/wiring.py: live_acq_ports()`; tests pass fakes. The chat's
`application/ports.py: Ports` has none of search, pages or readers: it reaches the engine through
`Ports.acquisition` (strangler S8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from automind.application.ports import LLM, NoReaders, PageStore, Reference, Searcher, SiteReaders


@dataclass
class AcqPorts:
    llm: LLM
    ref: Reference
    search: Searcher
    pages: PageStore | None = None  # None → `search` also implements PageStore (test fakes)
    readers: SiteReaders = field(default_factory=NoReaders)
    registry: Any = None  # acquisition.registry.api.RegistryPort; None: config order only
    metrics: Any = None  # inc(name, **labels) for Prometheus counters; None: not counted
    market_facts: Any = None  # spec 006 US5: upsert(rows, evidence_id); None: market areas store nothing
    datasets: Any = None  # async (make) -> [gold DatasetRow]: a live open-dataset query; None: stored/cached only

    @property
    def page_store(self) -> PageStore:
        return self.pages if self.pages is not None else self.search  # type: ignore[return-value]
