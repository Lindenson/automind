"""The registry port (spec 010 contracts/registry-port.md): the only registry module the chat cycle imports."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, model_validator

from automind.acquisition.domain.blame import ChallengeBlame, blame_challenge
from automind.acquisition.domain.truth import TruthKind, TruthVerdict
from automind.acquisition.registry.domain.blame import blame
from automind.acquisition.registry.domain.model import CapabilityStatus
from automind.shared.evidence import domain_of

__all__ = ["Attempt", "ChallengeBlame", "Outcome", "Plan", "PlannedSource", "RegistryPort", "TruthKind",
           "TruthSignalIn", "TruthVerdict", "blame", "blame_challenge"]  # fmt: skip


class PlannedSource(BaseModel):
    domain: str
    market: str
    priority: int
    status: CapabilityStatus  # active, candidate (explored) or retired
    unverified: bool = False
    path: str = ""  # spec 011 T108: the learned path prefix of its pages ("/fichas/"), for `site:domain/path`

    @property
    def site(self) -> str:
        """What a `site:` query names: the domain, narrowed to the learned path prefix when there is one."""
        return self.domain + self.path.rstrip("/") if self.path else self.domain


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


class Outcome(StrEnum):
    """What one page of a source gave (`registry_attempts.outcome`)."""

    ACCEPTED = "accepted"  # values accepted from it
    REJECTED = "rejected"  # read, but nothing usable (the reason says why)
    ROBOTS = "robots"  # robots.txt forbids it
    JUNK = "junk"  # not a page about cars (a shop, a forum, a 404 page)
    EMPTY = "empty"  # read, no values
    ERROR = "error"  # the fetch failed


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


Component = Literal["source", "relevance", "parser", "extractor", "units_sense", "fusion"]
_COMPONENT_OF_010 = {"check": "units_sense"}


class TruthSignalIn(BaseModel):
    kind: TruthKind
    verdict: TruthVerdict
    domain: str
    area: str
    market: str | None = None
    variant_id: str | None = None
    attribute: str | None = None
    claim_id: str | None = None
    blame: Literal["source", "parser", "extractor", "relevance", "check", "fusion"] = "source"
    details: dict[str, object] = {}
    # spec 011 US3 (research R9): shares per component (sum 1); only the source share changes the capability, the
    # others go to component_reputation under `components[component]` (km77@v1, extract_specs@v3|<model>, ...)
    blame_vector: dict[Component, float] | None = None
    components: dict[str, str] = {}
    gold_id: str | None = None
    snapshot_id: str | None = None
    disputed: bool = False

    def vector(self) -> dict[str, float]:
        if self.blame_vector:
            return {k: float(v) for k, v in self.blame_vector.items() if v > 0}
        return {_COMPONENT_OF_010.get(self.blame, self.blame): 1.0}


class RegistryPort(Protocol):
    async def plan(self, area: str, markets: list[str], make: str | None) -> Plan: ...

    async def sources_for(self, area: str, markets: list[str], limit: int) -> list[PlannedSource]:
        """Sources worth a `site:` query for an area on these markets: active ones by score, then surveyed
        candidates. Independent of autonomy: querying a source never changes its status."""
        ...

    async def record(self, attempts: list[Attempt]) -> None: ...

    async def signal(self, s: TruthSignalIn) -> str | None:
        """Record a truth signal; its id, None when it could not be stored."""
        ...
