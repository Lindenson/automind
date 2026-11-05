"""The registry port (spec 010 contracts/registry-port.md): the only registry module the chat cycle imports."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, model_validator

from automind.acquisition.registry.domain.blame import blame
from automind.domain.evidence import domain_of

__all__ = ["Attempt", "Plan", "PlannedSource", "RegistryPort", "TruthSignalIn", "blame"]


class PlannedSource(BaseModel):
    domain: str
    market: str
    priority: int
    status: Literal["active", "candidate", "retired"]
    unverified: bool = False


class Plan(BaseModel):
    area: str
    autonomy: bool = False
    sources: list[PlannedSource] = []
    skip: list[str] = []

    def priority_of(self, domain: str) -> int | None:
        d = domain.lower().removeprefix("www.")
        best = None
        for s in self.sources:
            if d == s.domain or d.endswith("." + s.domain):
                best = s.priority if best is None else min(best, s.priority)
        return best

    def unverified(self, domain: str) -> bool:
        d = domain.lower().removeprefix("www.")
        return any((d == s.domain or d.endswith("." + s.domain)) and s.unverified for s in self.sources)


Outcome = Literal["accepted", "rejected", "robots", "junk", "empty", "error"]


class Attempt(BaseModel):
    domain: str = ""  # the URL's domain when not given
    area: str
    market: str
    url: str
    outcome: Outcome
    job_id: str | None = None
    variant_id: str | None = None
    reason: str | None = None
    values: int = 0
    cost_eur: float = 0.0
    via_learned_query: bool = False
    # spec 011 FR-002: the stored page, the producer's version and model, and the pipeline stages' versions
    snapshot_id: str | None = None
    producer_version: str | None = None
    model: str | None = None
    stage_versions: dict[str, str] = {}

    @model_validator(mode="after")
    def _domain_from_url(self) -> Attempt:
        if not self.domain:
            self.domain = domain_of(self.url)
        return self


class TruthSignalIn(BaseModel):
    kind: Literal["challenge", "bad_source", "replacement", "agreement", "gold"]
    verdict: Literal["right", "wrong"]
    domain: str
    area: str
    market: str | None = None
    variant_id: str | None = None
    attribute: str | None = None
    claim_id: str | None = None
    blame: Literal["source", "parser", "extractor", "relevance", "check", "fusion"] = "source"
    details: dict[str, object] = {}


class RegistryPort(Protocol):
    async def plan(self, area: str, markets: list[str], make: str | None) -> Plan: ...

    async def sources_for(self, area: str, markets: list[str], limit: int) -> list[PlannedSource]:
        """Sources worth a `site:` query for an area on these markets: active ones by score, then surveyed
        candidates. Independent of autonomy: querying a source never changes its status."""
        ...

    async def record(self, attempts: list[Attempt]) -> None: ...

    async def signal(self, s: TruthSignalIn) -> None: ...
