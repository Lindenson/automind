"""Admission and re-checks (spec 010 US7, FR-019): sites met in searches are checked before any use; admitted
and blocked sites are re-checked every 90 / 180 days. Bounded per run and by the daily discovery budget.

`check_domain` is the check of one site; the scout (acquisition/agents/scout.py) uses it for the sites it found,
with the page the search returned as the robots sample."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, text

from automind.acquisition.registry.domain.admission import Admission, admit
from automind.acquisition.registry.infrastructure import terms
from automind.observability.metrics import prom
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db.models import CapabilityRow, RegistryChange, SourceRow, now
from automind.shared.infrastructure.db.session import sessionmaker

log = logging.getLogger(__name__)
PER_RUN = 10


async def spent_today() -> float:
    t = now()
    async with sessionmaker()() as s:
        q = text("SELECT coalesce(sum(cost_eur),0) FROM llm_calls WHERE role = 'terms_reader' AND created_at >= :s")
        return float((await s.execute(q, {"s": t - timedelta(hours=24)})).scalar() or 0)


def denylist() -> tuple[str, ...]:
    return tuple(str(x).lower() for x in load_yaml("sources.yaml").get("denylist") or [])


@dataclass(frozen=True)
class Checked:
    admission: Admission
    before: str  # the source's access before the check
    changed: bool  # the access changed (journalled by `system`)


async def check_domain(
    domain: str,
    sample_url: str | None,
    cfg: dict[str, Any],
    deny: tuple[str, ...],
    llm: Any = None,
    gather: Any = None,
) -> Checked | None:
    """The admission check of one site (deny-list and classifieds, robots for `sample_url` or the home page, a
    forbidding terms clause quoted and verified on the page, readable content): writes `sources.access`, its
    evidence and the next re-check, journals an access change. None when the facts could not be gathered or the
    source does not exist."""
    rech = cfg.get("recheck_days") or {}
    t = now()
    try:
        fx = await (gather or terms.facts)(domain, sample_url, llm)
    except Exception:  # noqa: BLE001 - one site never stops the run
        log.exception("registry.admission_failed domain=%s", domain)
        return None
    verdict = admit(fx, deny)
    async with sessionmaker()() as s:
        row = await s.get(SourceRow, domain)
        if row is None:
            return None
        before = row.access
        row.access, row.checked_at = verdict.access, t
        row.access_evidence = {**(row.access_evidence or {}), **verdict.evidence}
        ok = verdict.access in ("ok", "unknown")
        row.next_check_at = t + timedelta(days=int(rech.get("active" if ok else "blocked", 90 if ok else 180)))
        changed = before != verdict.access
        if changed:
            change = "admitted" if ok else "blocked"
            s.add(
                RegistryChange(
                    author="system",
                    domain=row.domain,
                    change=change,
                    before={"access": before},
                    after={"access": verdict.access},
                    reason=f"admission check: {verdict.reason}",
                    evidence=verdict.evidence,
                )
            )
            prom.inc("registry_changes", change=change, author="system")
        await s.commit()
    return Checked(verdict, before, changed)


async def admit_pending(cfg: dict[str, Any], llm: Any = None, gather: Any = None) -> dict[str, int]:
    deny = denylist()
    budget = float((cfg.get("discovery") or {}).get("eur_per_day", 0.2))
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
        checked = await check_domain(src.domain, None, cfg, deny, llm, gather)
        if checked is None:
            continue
        out["checked"] += 1
        if checked.changed:
            out["admitted" if checked.admission.access in ("ok", "unknown") else "blocked"] += 1
    return out
