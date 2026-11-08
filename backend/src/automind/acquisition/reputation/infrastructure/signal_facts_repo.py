"""What research stored about a version, read as `VariantFacts` for the signal rules (spec 011 T070): accepted claims
with their source's family and page, selected values, best gold values, the siblings' gold, page relevance, earlier
signals. A database failure becomes `ReputationStoreUnavailable`."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.domain.claims import ClaimStatus
from automind.acquisition.domain.truth import TruthKind
from automind.acquisition.gold.application.ports import GoldBook, GoldStoreUnavailable
from automind.acquisition.gold.domain.records import StoredGold
from automind.acquisition.registry.domain.families import family_of
from automind.acquisition.reputation.application.errors import ReputationStoreUnavailable
from automind.acquisition.reputation.domain.findings import FUSION_KEY
from automind.acquisition.reputation.domain.signal_facts import ClaimFact, GoldFact, SelectedValue, VariantFacts
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import (
    Claim,
    Document,
    Evidence,
    GoldValueRow,
    PageRelevance,
    SourceRow,
    SpecValue,
    TruthSignal,
    Variant,
)
from automind.shared.infrastructure.db.session import sessionmaker

_store_errors = translate_errors(ReputationStoreUnavailable)


class SignalFactsRepo:
    """The facts of a version; `families` is `config/registry.yaml families` (a domain's family when the registry
    does not know the source)."""

    def __init__(self, families: Mapping[str, Sequence[str]], gold: GoldBook) -> None:
        self.families = families
        self.gold = gold

    @_store_errors
    async def facts(self, variant_id: str) -> VariantFacts | None:
        """The version's facts, None when the version is gone."""
        async with sessionmaker()() as s:
            v = await s.get(Variant, variant_id)
            if v is None:
                return None
            claims = await self._claims(s, variant_id)
            selected = {sv.attribute: _selected(sv) for sv in (await s.execute(
                select(SpecValue).where(SpecValue.variant_id == variant_id))).scalars()}  # fmt: skip
            relevance = {r.document_id: (r.verdict, r.prompt_version) for r in (await s.execute(
                select(PageRelevance).where(PageRelevance.variant_id == variant_id))).scalars()}  # fmt: skip
            siblings = await _siblings(s, v)
            done, agreed, fused = await _signalled(s, variant_id)
        try:
            gold = {a: _gold(g) for a, g in (await self.gold.best(variant_id)).items()}
        except GoldStoreUnavailable as e:
            raise ReputationStoreUnavailable(f"gold of {variant_id}") from e
        return VariantFacts(v.id, v.fuel, v.powertrain, v.body_class, tuple(claims), selected, gold, siblings,
                            relevance, done, agreed, fused)  # fmt: skip

    @_store_errors
    async def recent_variants(self, since: datetime) -> list[str]:
        """Versions with an accepted claim, a selection or a gold value since `since`."""
        async with sessionmaker()() as s:
            ids: set[str] = set()
            for q in (
                select(Claim.variant_id).where(Claim.created_at >= since, Claim.status == ClaimStatus.ACCEPTED),
                select(SpecValue.variant_id).where(SpecValue.updated_at >= since),
                select(GoldValueRow.variant_id).where(GoldValueRow.verified_at >= since),
            ):
                ids |= set((await s.execute(q.distinct())).scalars())
        return sorted(ids)

    async def _claims(self, s: AsyncSession, variant_id: str) -> list[ClaimFact]:
        rows = (await s.execute(
            select(Claim, Evidence.domain, Evidence.document_id, Document.text)
            .join(Evidence, Claim.evidence_id == Evidence.id)
            .outerjoin(Document, Evidence.document_id == Document.id)
            .where(Claim.variant_id == variant_id, Claim.status == ClaimStatus.ACCEPTED)
            .order_by(Claim.created_at, Claim.id)
        )).all()  # fmt: skip
        domains = {d for _, d, _, _ in rows}
        fam_of = {r.domain: r.family for r in (await s.execute(
            select(SourceRow).where(SourceRow.domain.in_(domains)))).scalars()}  # fmt: skip
        return [_claim(c, d, fam_of.get(d) or family_of(d, self.families), doc_id, text or "")
                for c, d, doc_id, text in rows]  # fmt: skip


def _claim(c: Claim, domain: str, family: str, doc_id: str | None, text: str) -> ClaimFact:
    producer = c.producer or ("reader" if c.extracted_by == "READER" else "extractor")
    return ClaimFact(id=c.id, attribute=c.attribute, value_num=c.value_num, area=c.area, domain=domain, family=family,
                     created_at=c.created_at, snapshot_id=c.snapshot_id, doc_id=doc_id, doc_text=text,
                     producer=producer, producer_version=c.producer_version, model=c.model,
                     excerpt=c.excerpt or "")  # fmt: skip


def _selected(sv: SpecValue) -> SelectedValue:
    return SelectedValue(sv.attribute, sv.value_num, sv.value_text, bool(sv.available), sv.confidence,
                         tuple(sv.claim_ids or ()))  # fmt: skip


def _gold(g: StoredGold) -> GoldFact:
    tol = (g.tolerance_kind, float(g.tolerance)) if g.tolerance is not None and g.tolerance_kind else None
    return GoldFact(g.id, g.value_num, tol, g.match_rule, g.confidence)


async def _siblings(s: AsyncSession, v: Variant) -> dict[str, tuple[float, ...]]:
    """Gold of the same model's other versions, by attribute."""
    ids = list((await s.execute(select(Variant.id).where(
        Variant.make == v.make, Variant.model == v.model, Variant.generation.is_not_distinct_from(v.generation),
        Variant.id != v.id))).scalars())  # fmt: skip
    out: dict[str, list[float]] = defaultdict(list)
    if ids:
        q = select(GoldValueRow).where(GoldValueRow.variant_id.in_(ids), GoldValueRow.flagged.is_(False))
        for g in (await s.execute(q)).scalars():
            if g.value_num is not None:
                out[g.attribute].append(g.value_num)
    return {a: tuple(v) for a, v in out.items()}


async def _signalled(s: AsyncSession, variant_id: str) -> tuple[
        frozenset[tuple[str | None, str]], frozenset[tuple[str, str]], frozenset[tuple[str, float]]]:  # fmt: skip
    """(claim id, kind) signalled, (attribute, family) agreed, (attribute, selected value) fused."""
    done: set[tuple[str | None, str]] = set()
    agreed: set[tuple[str, str]] = set()
    fused: set[tuple[str, float]] = set()
    for t in (await s.execute(select(TruthSignal).where(TruthSignal.variant_id == variant_id))).scalars():
        done.add((t.claim_id, t.kind))
        d = t.details or {}
        if t.kind == TruthKind.AGREEMENT and t.attribute and d.get("family"):
            agreed.add((t.attribute, str(d["family"])))
        if t.component == FUSION_KEY and t.attribute and d.get("selected") is not None:
            fused.add((t.attribute, float(d["selected"])))
    return frozenset(done), frozenset(agreed), frozenset(fused)
