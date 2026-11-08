"""Truth signals (`truth_signals`; spec 010 US6, spec 011 US3): recorded, and applied by their blame vector — the
source share to the capability's accuracy, the other shares to the blamed components (`component_reputation`).
Every method is one transaction and raises `RegistryStoreUnavailable` when the database fails."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.domain.blame import LABEL_010, REPUTATION_KIND
from automind.acquisition.registry.api import TruthSignalIn
from automind.acquisition.registry.application.ports import RegistryStoreUnavailable
from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.infrastructure.capability_store import source_type
from automind.acquisition.registry.infrastructure.rows import fade, rescore
from automind.acquisition.reputation.infrastructure import component_store
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import CapabilityRow, TruthSignal, now
from automind.shared.infrastructure.db.session import sessionmaker

COMPONENT_CHARS = 160


class SignalStore:
    """`Signals` over the database."""

    def __init__(self, cfg: RegistryConfig) -> None:
        self.cfg = cfg

    @translate_errors(RegistryStoreUnavailable)
    async def signal(self, sig: TruthSignalIn, weight: float) -> str:
        """Record a truth signal and apply it. A disputed signal is recorded only: the blame judge applies it once
        the component is settled (`resolve`). Returns the signal id."""
        vector = sig.vector()
        async with sessionmaker()() as s:
            cap = None
            if not sig.disputed:
                cap = await self._apply(s, Applied(sig.kind, sig.verdict, sig.domain, sig.area, sig.market), vector,
                                        sig.components, weight)  # fmt: skip
            top, component = _component(vector, sig.components, sig.domain)
            row = TruthSignal(
                capability_id=cap.id if cap else None, variant_id=sig.variant_id, attribute=sig.attribute,
                claim_id=sig.claim_id, kind=sig.kind, verdict=sig.verdict, weight=weight,
                blame=LABEL_010.get(top, sig.blame) if sig.blame_vector else sig.blame,
                details={"domain": sig.domain, "area": sig.area, "market": sig.market, "components": sig.components,
                         **sig.details},
                blame_vector=vector if sig.blame_vector else None, component=component, gold_id=sig.gold_id,
                snapshot_id=sig.snapshot_id, disputed=sig.disputed,
            )  # fmt: skip
            s.add(row)
            await s.commit()
            return row.id

    @translate_errors(RegistryStoreUnavailable)
    async def resolve(self, signal_id: str, vector: dict[str, float], components: dict[str, str], note: str) -> bool:
        """Settle a disputed signal with its final vector and apply it (the blame judge, research R9)."""
        async with sessionmaker()() as s:
            row = await s.get(TruthSignal, signal_id)
            if row is None or not row.disputed:
                return False
            d = dict(row.details or {})
            comps = {**(d.get("components") or {}), **components}
            domain = str(d.get("domain") or "")
            applied = Applied(row.kind, row.verdict, domain, str(d.get("area") or ""), d.get("market"))
            cap = await self._apply(s, applied, vector, comps, row.weight)
            top, row.component = _component(vector, comps, domain)
            row.blame, row.blame_vector, row.disputed = LABEL_010.get(top, "source"), vector, False
            row.capability_id = cap.id if cap else row.capability_id
            row.details = {**d, "components": comps, "judge": note}
            await s.commit()
            return True

    async def _apply(self, s: AsyncSession, sig: Applied, vector: dict[str, float], comps: dict[str, str],
                     weight: float) -> CapabilityRow | None:  # fmt: skip
        """Split a signal's weight by its blame vector: only the source share changes the capability (right/wrong
        and the accuracy-signal weight `signals_w`), the other shares go to the blamed components (FR-011)."""
        cap = None
        source_share = vector.get("source", 0.0)
        if source_share > 0:
            cap = await self._source_share(s, sig, weight * source_share, source_share)
        for comp, share in vector.items():
            if comp == "source" or share <= 0 or comp not in REPUTATION_KIND:
                continue
            await component_store.add(s, REPUTATION_KIND[comp], comps.get(comp) or "unknown", sig.verdict,
                                      weight * share, self.cfg.half_life_days)  # fmt: skip
        return cap

    async def _source_share(self, s: AsyncSession, sig: Applied, w: float, share: float) -> CapabilityRow | None:
        q = select(CapabilityRow).where(CapabilityRow.domain == sig.domain, CapabilityRow.area == sig.area)
        if sig.market:
            q = q.where(CapabilityRow.market == sig.market)
        cap = (await s.execute(q.order_by(CapabilityRow.attempts.desc()).limit(1))).scalar_one_or_none()
        if cap is None:
            return None
        fade(cap, self.cfg.half_life_days, now())
        if sig.verdict == "right":
            cap.right_w += w
        else:
            cap.wrong_w += w
        cap.signals_w = (cap.signals_w or 0.0) + w
        if sig.kind == "agreement":
            cap.families_agree = (cap.families_agree or 0.0) + share
        rescore(cap, await source_type(s, cap.domain), self.cfg.score)
        return cap


@dataclass(frozen=True)
class Applied:
    """What applying a signal reads of it."""

    kind: str
    verdict: str
    domain: str
    area: str
    market: str | None


def _component(vector: dict[str, float], comps: dict[str, str], domain: str) -> tuple[str, str]:
    top = max(vector, key=lambda c: vector[c]) if vector else "source"
    key = domain if top == "source" else comps.get(top) or "unknown"
    return top, f"{REPUTATION_KIND.get(top, top)}:{key}"[:COMPONENT_CHARS]
