"""What research stored about one catalogue version, as plain records the signal rules read (spec 011 T070): its
accepted claims (with the source's family and the page they came from), its selected values, its gold values, the
gold of its sibling versions, the page relevance verdicts, and what was signalled before. Data only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from automind.acquisition.domain.tolerance import Tolerance
from automind.acquisition.domain.truth import TruthKind, TruthVerdict
from automind.shared.contracts.json import JsonObject

HYBRID = ("HEV", "PHEV", "MHEV")
HYBRID_FUELS = ("hybrid", "phev", "mhev")


@dataclass(frozen=True)
class ClaimFact:
    """An accepted claim: the value, where it came from (domain, family, document, snapshot) and who read it."""

    id: str
    attribute: str
    value_num: float | None
    area: str
    domain: str
    family: str
    created_at: datetime
    snapshot_id: str | None = None
    doc_id: str | None = None
    doc_text: str = ""
    producer: str = "extractor"  # reader | extractor | dataset | user
    producer_version: str | None = None
    model: str | None = None
    excerpt: str = ""


@dataclass(frozen=True)
class SelectedValue:
    """The value shown for an attribute and the claims behind it."""

    attribute: str
    value_num: float | None
    value_text: str | None
    available: bool
    confidence: str | None
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoldFact:
    """The best gold value of an attribute; `tolerance` is its own, None: the attribute's."""

    id: str
    value_num: float | None
    tolerance: Tolerance | None
    match_rule: str | None
    confidence: str


@dataclass(frozen=True)
class VariantFacts:
    """Everything the signal rules read about one version. `claims` are oldest first; `done` holds (claim id, kind)
    already signalled, `agreed` (attribute, family) with an agreement, `fused` (attribute, selected value) with a
    fusion signal."""

    id: str
    fuel: str | None
    powertrain: str | None
    body_class: str | None
    claims: tuple[ClaimFact, ...]
    selected: dict[str, SelectedValue]
    gold: dict[str, GoldFact]
    siblings: dict[str, tuple[float, ...]] = field(default_factory=dict)
    relevance: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # document -> (verdict, version)
    done: frozenset[tuple[str | None, str]] = frozenset()
    agreed: frozenset[tuple[str, str]] = frozenset()
    fused: frozenset[tuple[str, float]] = frozenset()

    @property
    def hybrid(self) -> bool:
        """A hybrid powertrain (the blame rules read its figures differently)."""
        return (self.powertrain or "").upper() in HYBRID or (self.fuel or "").lower() in HYBRID_FUELS

    def attributes(self) -> set[str]:
        """Every attribute a claim or a selected value names."""
        return {c.attribute for c in self.claims} | set(self.selected)


@dataclass(frozen=True)
class BlameAsk:
    """A wrong signal's blame to compute: against `truth` (None: only the checks know it is wrong, read the cached
    text instead of the page), with the truth's confidence; `may_dispute` False keeps it undisputed."""

    truth: float | None
    tolerance: Tolerance
    confidence: str = "HIGH"
    may_dispute: bool = True


@dataclass(frozen=True)
class Finding:
    """One signal the rules found. With `claim` it is about that claim; without (fusion) `domain`/`area` say where.
    `blame` is set for a wrong signal whose blame vector is computed; `fixed_blame` (vector, components) when the
    rule names the component itself. `counter` is the name it is counted under."""

    kind: TruthKind
    verdict: TruthVerdict
    attribute: str
    counter: str
    details: JsonObject
    claim: ClaimFact | None = None
    domain: str = ""
    area: str = ""
    gold_id: str | None = None
    blame: BlameAsk | None = None
    fixed_blame: tuple[dict[str, float], dict[str, str]] | None = None
