"""Registry persistence (spec 010 migration 0016)."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func, select

from automind.acquisition.domain.blame import LABEL_010, REPUTATION_KIND
from automind.acquisition.registry.api import Attempt, TruthSignalIn
from automind.acquisition.registry.domain.model import Capability, Source
from automind.acquisition.registry.domain.score import Counts, decay, score_of
from automind.acquisition.reputation import components
from automind.acquisition.snapshots import store
from automind.observability.metrics import prom
from automind.shared.infrastructure.db.models import (
    CapabilityRow,
    Claim,
    RegistryAttempt,
    RegistryChange,
    SourceRow,
    TruthSignal,
    now,
)
from automind.shared.infrastructure.db.session import sessionmaker

log = logging.getLogger(__name__)
RECENT = 20  # last outcomes kept per capability


async def _producer_of(s: Any, a: Attempt) -> tuple[str | None, str | None]:
    """Spec 011 FR-002: an attempt names the producer version and model of the values read from its page."""
    if a.producer_version is not None or a.snapshot_id is None:
        return a.producer_version, a.model
    q = select(Claim.producer_version, Claim.model).where(Claim.snapshot_id == a.snapshot_id)
    if a.variant_id:
        q = q.where(Claim.variant_id == a.variant_id)
    row = (await s.execute(q.order_by(Claim.created_at.desc()).limit(1))).first()
    return (row[0], row[1]) if row else (None, None)


def _cap_dict(r: CapabilityRow) -> dict[str, Any]:
    return {
        "id": r.id,
        "domain": r.domain,
        "area": r.area,
        "market": r.market,
        "status": r.status,
        "score": r.score,
        "priority_seed": r.priority_seed,
        # spec 011 R7: what Thompson sampling draws from
        "attempts": r.attempts,
        "accepted": r.accepted,
        "right_w": r.right_w,
        "wrong_w": r.wrong_w,
        "cost_eur": r.cost_eur,
        "explore_spent_eur": r.explore_spent_eur or 0.0,
        "url_patterns": list(r.url_patterns or []),  # spec 011 T108: learned by the scout
    }


DECAYED = ("attempts", "accepted", "right_w", "wrong_w", "robots_refusals", "junk", "cost_eur", "signals_w",
           "families_agree")  # fmt: skip


def _decay(cap: CapabilityRow, hl: float) -> None:
    """Fade counts and signals to now (half-life), so a site that went bad loses trust (spec 010 US6)."""
    t = now()
    days = (t - cap.decayed_at).total_seconds() / 86400 if cap.decayed_at else 0.0
    if days > 0:
        for f in DECAYED:
            setattr(cap, f, decay(float(getattr(cap, f) or 0.0), days, hl))
    cap.decayed_at = t


def _refresh(cap: CapabilityRow, source_type: str, cfg: Mapping[str, Any]) -> None:
    q = score_of(Counts(cap.attempts, cap.accepted, cap.right_w, cap.wrong_w, cap.cost_eur), source_type, cfg)
    cap.score, cap.acc_mean, cap.acc_lb, cap.yield_ = q.score, q.acc_mean, q.acc_lb, q.yield_


class RegistryRepo:
    def __init__(self, cfg: Mapping[str, Any] | None = None) -> None:
        if cfg is None:
            from automind.shared.infrastructure.config.loader import load_yaml  # noqa: PLC0415

            cfg = load_yaml("registry.yaml")
        self.cfg = cfg
        self.hl = float(cfg.get("half_life_days", 90))

    async def _type(self, s: Any, domain: str, cache: dict[str, str]) -> str:
        if domain not in cache:
            src = await s.get(SourceRow, domain)
            cache[domain] = src.source_type if src is not None else "OTHER"
        return cache[domain]

    async def capabilities(self, area: str, markets: list[str]) -> list[dict[str, Any]]:
        async with sessionmaker()() as s:
            q = (
                select(CapabilityRow, SourceRow.source_type, SourceRow.access)
                .outerjoin(SourceRow, SourceRow.domain == CapabilityRow.domain)
                .where(CapabilityRow.area == area, CapabilityRow.market.in_(markets))
            )
            return [{**_cap_dict(r), "source_type": st or "OTHER", "access": acc or "unknown"}
                    for r, st, acc in (await s.execute(q)).all()]  # fmt: skip

    async def explore_spent(self) -> float:
        """Today's exploration spend over all capabilities (reset by the daily roll-up)."""
        async with sessionmaker()() as s:
            return float((await s.execute(select(func.coalesce(func.sum(CapabilityRow.explore_spent_eur), 0.0)))
                          ).scalar() or 0.0)  # fmt: skip

    async def queryable(self, area: str, markets: list[str]) -> list[dict[str, Any]]:
        """Active and candidate capabilities with their source's access (for `site:` queries)."""
        async with sessionmaker()() as s:
            q = (
                select(CapabilityRow, SourceRow.access)
                .join(SourceRow, SourceRow.domain == CapabilityRow.domain)
                .where(
                    CapabilityRow.area == area,
                    CapabilityRow.market.in_(markets),
                    CapabilityRow.status.in_(("active", "candidate")),
                )
            )
            return [{**_cap_dict(c), "access": access} for c, access in (await s.execute(q)).all()]

    async def is_empty(self) -> bool:
        async with sessionmaker()() as s:
            return (await s.execute(select(SourceRow.domain).limit(1))).first() is None

    async def seed(self, items: Iterable[tuple[Source, list[Capability]]], reason: str) -> int:
        """Insert what is missing; blocked always wins over other statuses of the same capability. Journalled."""
        added = 0
        async with sessionmaker()() as s:
            for src, caps in items:
                row = await s.get(SourceRow, src.domain)
                if row is None:
                    s.add(
                        SourceRow(
                            domain=src.domain,
                            source_type=src.source_type,
                            family=src.family,
                            markets=src.markets,
                            languages=src.languages,
                            access=src.access,
                            access_evidence=src.access_evidence,
                            reader=src.reader,
                        )
                    )
                    await s.flush()
                elif src.access not in ("ok", "unknown") and row.access in ("ok", "unknown"):
                    row.access, row.access_evidence = src.access, src.access_evidence
                elif src.reader and not row.reader:
                    row.reader = src.reader
                for c in caps:
                    q = select(CapabilityRow).where(
                        CapabilityRow.domain == c.domain, CapabilityRow.area == c.area, CapabilityRow.market == c.market
                    )
                    have = (await s.execute(q)).scalar_one_or_none()
                    if have is None:
                        cap = CapabilityRow(
                            domain=c.domain,
                            area=c.area,
                            market=c.market,
                            status=c.status,
                            priority_seed=c.priority_seed,
                            attempts=c.attempts,
                            accepted=c.accepted,
                        )
                        s.add(cap)
                        await s.flush()
                        s.add(
                            RegistryChange(
                                author="system",
                                capability_id=cap.id,
                                domain=c.domain,
                                change="added",
                                after={"status": c.status, "area": c.area, "market": c.market},
                                reason=reason,
                                evidence=src.access_evidence,
                            )
                        )
                        added += 1
                    elif c.status == "blocked" and have.status != "blocked":
                        before = have.status
                        have.status, have.status_since = "blocked", now()
                        s.add(
                            RegistryChange(
                                author="system",
                                capability_id=have.id,
                                domain=c.domain,
                                change="blocked",
                                before={"status": before},
                                after={"status": "blocked"},
                                reason=reason,
                                evidence=src.access_evidence,
                            )
                        )
                    elif have.priority_seed is None and c.priority_seed is not None:
                        have.priority_seed = c.priority_seed
            await s.commit()
        return added

    async def _capability(self, s: Any, domain: str, area: str, market: str) -> CapabilityRow:
        q = select(CapabilityRow).where(
            CapabilityRow.domain == domain, CapabilityRow.area == area, CapabilityRow.market == market
        )
        cap = (await s.execute(q)).scalar_one_or_none()
        if cap is not None:
            return cap
        if await s.get(SourceRow, domain) is None:  # met in an open search: discovered (admission comes later)
            s.add(SourceRow(domain=domain, source_type="PUBLICATION", family=domain, markets=[market]))
            await s.flush()
        cap = CapabilityRow(domain=domain, area=area, market=market, status="discovered")
        s.add(cap)
        await s.flush()
        s.add(
            RegistryChange(
                author="system",
                capability_id=cap.id,
                domain=domain,
                change="added",
                after={"status": "discovered", "area": area, "market": market},
                reason="met in a research search",
            )
        )
        prom.inc("registry_changes", change="added", author="system")
        return cap

    async def record(self, attempts: list[Attempt]) -> None:
        types: dict[str, str] = {}
        async with sessionmaker()() as s:
            for a in attempts:
                cap = await self._capability(s, a.domain, a.area, a.market)
                _decay(cap, self.hl)
                ok = a.outcome == "accepted"
                cap.attempts += 1
                cap.accepted += 1 if ok else 0
                if a.outcome == "robots":
                    cap.robots_refusals += 1
                if a.outcome == "junk":
                    cap.junk += 1
                if a.outcome == "rejected" and a.reason:
                    cap.rejected = {**(cap.rejected or {}), a.reason: float((cap.rejected or {}).get(a.reason, 0)) + 1}
                cap.cost_eur += a.cost_eur
                if cap.status == "candidate":  # spec 011 R7: a candidate's attempt is exploration
                    cap.explore_spent_eur = (cap.explore_spent_eur or 0.0) + a.cost_eur
                cap.recent = [*(cap.recent or []), ok][-RECENT:]
                cap.last_used = now()
                _refresh(cap, await self._type(s, a.domain, types), self.cfg)
                version, model = await _producer_of(s, a)
                s.add(
                    RegistryAttempt(
                        capability_id=cap.id,
                        job_id=a.job_id,
                        variant_id=a.variant_id,
                        url=a.url,
                        outcome=a.outcome,
                        reason=a.reason,
                        values=a.values,
                        cost_eur=a.cost_eur,
                        snapshot_id=a.snapshot_id,
                        producer_version=version,
                        model=model,
                        stage_versions=a.stage_versions,
                    )
                )
                prom.inc("registry_attempts", area=a.area, outcome=a.outcome)
            await s.commit()
        await _mark_snapshots(attempts)

    async def _apply(
        self, s: Any, kind: str, verdict: str, domain: str, area: str, market: str | None,
        vector: dict[str, float], comps: dict[str, str], weight: float,
    ) -> CapabilityRow | None:  # fmt: skip
        """Split a signal's weight by its blame vector: only the source share changes the capability (right/wrong
        and the accuracy-signal weight `signals_w`), the other shares go to the blamed components (FR-011)."""
        cap = None
        source_share = vector.get("source", 0.0)
        if source_share > 0:
            q = select(CapabilityRow).where(CapabilityRow.domain == domain, CapabilityRow.area == area)
            if market:
                q = q.where(CapabilityRow.market == market)
            cap = (await s.execute(q.order_by(CapabilityRow.attempts.desc()).limit(1))).scalar_one_or_none()
            if cap is not None:
                _decay(cap, self.hl)
                w = weight * source_share
                if verdict == "right":
                    cap.right_w += w
                else:
                    cap.wrong_w += w
                cap.signals_w = (cap.signals_w or 0.0) + w
                if kind == "agreement":
                    cap.families_agree = (cap.families_agree or 0.0) + source_share
                _refresh(cap, await self._type(s, cap.domain, {}), self.cfg)
        for comp, share in vector.items():
            if comp == "source" or share <= 0 or comp not in REPUTATION_KIND:
                continue
            await components.add(s, REPUTATION_KIND[comp], comps.get(comp) or "unknown", verdict, weight * share,
                                 self.hl)  # fmt: skip
        return cap

    @staticmethod
    def _component(vector: dict[str, float], comps: dict[str, str], domain: str) -> tuple[str, str]:
        top = max(vector, key=lambda c: vector[c]) if vector else "source"
        key = domain if top == "source" else comps.get(top) or "unknown"
        return top, f"{REPUTATION_KIND.get(top, top)}:{key}"[:160]

    async def signal(self, sig: TruthSignalIn, weight: float) -> str:
        """Record a truth signal and apply it (spec 011 US3). A disputed signal is recorded only: the blame judge
        applies it once the component is settled (`resolve`). Returns the signal id."""
        vector = sig.vector()
        async with sessionmaker()() as s:
            cap = None
            if not sig.disputed:
                cap = await self._apply(s, sig.kind, sig.verdict, sig.domain, sig.area, sig.market, vector,
                                        sig.components, weight)  # fmt: skip
            top, component = self._component(vector, sig.components, sig.domain)
            row = TruthSignal(
                capability_id=cap.id if cap else None,
                variant_id=sig.variant_id,
                attribute=sig.attribute,
                claim_id=sig.claim_id,
                kind=sig.kind,
                verdict=sig.verdict,
                weight=weight,
                blame=LABEL_010.get(top, sig.blame) if sig.blame_vector else sig.blame,
                details={
                    "domain": sig.domain,
                    "area": sig.area,
                    "market": sig.market,
                    "components": sig.components,
                    **sig.details,
                },  # fmt: skip
                blame_vector=vector if sig.blame_vector else None,
                component=component,
                gold_id=sig.gold_id,
                snapshot_id=sig.snapshot_id,
                disputed=sig.disputed,
            )
            s.add(row)
            await s.commit()
            return row.id

    async def resolve(self, signal_id: str, vector: dict[str, float], comps: dict[str, str], note: str) -> bool:
        """Settle a disputed signal with its final vector and apply it (the blame judge, research R9)."""
        async with sessionmaker()() as s:
            row = await s.get(TruthSignal, signal_id)
            if row is None or not row.disputed:
                return False
            d = dict(row.details or {})
            comps = {**(d.get("components") or {}), **comps}
            cap = await self._apply(s, row.kind, row.verdict, str(d.get("domain") or ""), str(d.get("area") or ""),
                                    d.get("market"), vector, comps, row.weight)  # fmt: skip
            top, row.component = self._component(vector, comps, str(d.get("domain") or ""))
            row.blame, row.blame_vector, row.disputed = LABEL_010.get(top, "source"), vector, False
            row.capability_id = cap.id if cap else row.capability_id
            row.details = {**d, "components": comps, "judge": note}
            await s.commit()
            return True


async def _mark_snapshots(attempts: list[Attempt]) -> None:
    """Spec 011 T021: a page that gave accepted values is kept longer and remembers the variant it served."""
    for a in attempts:
        if a.snapshot_id is None:
            continue
        try:
            await store.mark(a.snapshot_id, a.values if a.outcome == "accepted" else 0, a.variant_id)
        except Exception:  # noqa: BLE001 - bookkeeping never fails a job
            log.warning("snapshot.mark_failed id=%s", a.snapshot_id, exc_info=True)
