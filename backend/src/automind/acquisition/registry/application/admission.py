"""Admission and re-checks (spec 010 US7, FR-019): sites met in searches are checked before any use; admitted
and blocked sites are re-checked every 90 / 180 days. Bounded per run and by the daily discovery budget."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, text

from automind.acquisition.registry.domain.admission import admit
from automind.acquisition.registry.infrastructure import terms
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db.models import CapabilityRow, RegistryChange, SourceRow, now
from automind.infrastructure.db.session import sessionmaker
from automind.insight.metrics import prom

log = logging.getLogger(__name__)
PER_RUN = 10


async def spent_today() -> float:
    t = now()
    async with sessionmaker()() as s:
        q = text("SELECT coalesce(sum(cost_eur),0) FROM llm_calls WHERE role = 'terms_reader' AND created_at >= :s")
        return float((await s.execute(q, {"s": t - timedelta(hours=24)})).scalar() or 0)


async def admit_pending(cfg: dict[str, Any], llm: Any = None, gather: Any = None) -> dict[str, int]:
    deny = tuple(str(x).lower() for x in load_yaml("sources.yaml").get("denylist") or [])
    budget = float((cfg.get("discovery") or {}).get("eur_per_day", 0.2))
    rech = cfg.get("recheck_days") or {}
    out = {"checked": 0, "admitted": 0, "blocked": 0}
    t = now()
    async with sessionmaker()() as s:
        discovered = select(CapabilityRow.domain).where(CapabilityRow.status == "discovered")
        q = (
            select(SourceRow)
            .where(or_(SourceRow.domain.in_(discovered), SourceRow.next_check_at < t), SourceRow.frozen.is_(False))
            .limit(PER_RUN)
        )
        rows = list((await s.execute(q)).scalars())
    for src in rows:
        if await spent_today() >= budget:
            break
        try:
            fx = await (gather or terms.facts)(src.domain, None, llm)
        except Exception:  # noqa: BLE001 - one site never stops the run
            log.exception("registry.admission_failed domain=%s", src.domain)
            continue
        verdict = admit(fx, deny)
        out["checked"] += 1
        async with sessionmaker()() as s:
            row = await s.get(SourceRow, src.domain)
            if row is None:
                continue
            before = row.access
            row.access, row.checked_at = verdict.access, t
            row.access_evidence = {**(row.access_evidence or {}), **verdict.evidence}
            ok = verdict.access in ("ok", "unknown")
            row.next_check_at = t + timedelta(days=int(rech.get("active" if ok else "blocked", 90 if ok else 180)))
            if before != verdict.access:
                change = "blocked" if verdict.access not in ("ok", "unknown") else "admitted"
                s.add(
                    RegistryChange(
                        author="system",
                        domain=row.domain,
                        change=change[:12],
                        before={"access": before},
                        after={"access": verdict.access},
                        reason=f"admission check: {verdict.reason}",
                        evidence=verdict.evidence,
                    )
                )
                prom.inc("registry_changes", change=change, author="system")
                out["admitted" if change == "admitted" else "blocked"] += 1
            await s.commit()
    return out
