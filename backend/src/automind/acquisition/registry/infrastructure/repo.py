"""Registry persistence (spec 010 migration 0016)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select

from automind.acquisition.registry.api import Attempt, TruthSignalIn
from automind.acquisition.registry.domain.model import Capability, Source
from automind.acquisition.registry.domain.score import Counts, decay, score_of
from automind.infrastructure.db.models import (
    CapabilityRow,
    RegistryAttempt,
    RegistryChange,
    SourceRow,
    TruthSignal,
    now,
)
from automind.infrastructure.db.session import sessionmaker
from automind.insight.metrics import prom

RECENT = 20  # last outcomes kept per capability


def _cap_dict(r: CapabilityRow) -> dict[str, Any]:
    return {
        "id": r.id,
        "domain": r.domain,
        "area": r.area,
        "market": r.market,
        "status": r.status,
        "score": r.score,
        "priority_seed": r.priority_seed,
    }


DECAYED = ("attempts", "accepted", "right_w", "wrong_w", "robots_refusals", "junk", "cost_eur")


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
            from automind.infrastructure.config import load_yaml  # noqa: PLC0415

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
            q = select(CapabilityRow).where(CapabilityRow.area == area, CapabilityRow.market.in_(markets))
            return [_cap_dict(r) for r in (await s.execute(q)).scalars()]

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
                if not a.via_learned_query or not ok:  # spec 007 rule: no self-reinforcement through own queries
                    cap.attempts += 1
                    cap.accepted += 1 if ok else 0
                if a.outcome == "robots":
                    cap.robots_refusals += 1
                if a.outcome == "junk":
                    cap.junk += 1
                if a.outcome == "rejected" and a.reason:
                    cap.rejected = {**(cap.rejected or {}), a.reason: float((cap.rejected or {}).get(a.reason, 0)) + 1}
                cap.cost_eur += a.cost_eur
                cap.recent = [*(cap.recent or []), ok][-RECENT:]
                cap.last_used = now()
                _refresh(cap, await self._type(s, a.domain, types), self.cfg)
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
                    )
                )
                prom.inc("registry_attempts", area=a.area, outcome=a.outcome)
            await s.commit()

    async def signal(self, sig: TruthSignalIn, weight: float) -> None:
        async with sessionmaker()() as s:
            cap = None
            if sig.blame == "source":
                q = select(CapabilityRow).where(CapabilityRow.domain == sig.domain, CapabilityRow.area == sig.area)
                if sig.market:
                    q = q.where(CapabilityRow.market == sig.market)
                cap = (await s.execute(q.order_by(CapabilityRow.attempts.desc()).limit(1))).scalar_one_or_none()
                if cap is not None:
                    _decay(cap, self.hl)
                    if sig.verdict == "right":
                        cap.right_w += weight
                    else:
                        cap.wrong_w += weight
                    _refresh(cap, await self._type(s, cap.domain, {}), self.cfg)
            s.add(
                TruthSignal(
                    capability_id=cap.id if cap else None,
                    variant_id=sig.variant_id,
                    attribute=sig.attribute,
                    claim_id=sig.claim_id,
                    kind=sig.kind,
                    verdict=sig.verdict,
                    weight=weight,
                    blame=sig.blame,
                    details={"domain": sig.domain, "area": sig.area, **sig.details},
                )
            )
            await s.commit()
