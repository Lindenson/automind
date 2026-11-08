"""Admission and re-checks (spec 010 US7, FR-019): sites met in searches are checked before any use; admitted and
blocked sites are re-checked every 90 / 180 days. Bounded per run and by the daily discovery budget.

`SiteAdmission.check` is the check of one site; the scout (acquisition/agents/scout.py) uses it for the sites it
found, with the page the search returned as the robots sample.

Errors: a site whose facts cannot be gathered (network, model) gets no verdict and the run goes on (logged);
`RegistryStoreUnavailable` from the book propagates (the worker retries the task; each verdict is its own
transaction, so the ones written stay)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from automind.acquisition.registry.application.ports import AdmissionBook, Clock, SiteFacts
from automind.acquisition.registry.domain.admission import Admission, admit
from automind.acquisition.registry.domain.config import RegistryConfig

log = logging.getLogger(__name__)
PER_RUN = 10
ADMITTING = ("ok", "unknown")  # accesses that let a source be used (unknown: no slots until a re-check)
BUDGET_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class Checked:
    """The verdict of one check with the access before it; `changed`: the access changed (journalled)."""

    admission: Admission
    before: str
    changed: bool


class SiteAdmission:
    """The admission check of sites over the book, the facts gatherer, the deny-list and the clock."""

    def __init__(self, book: AdmissionBook, facts: SiteFacts, cfg: RegistryConfig, deny: Sequence[str],
                 clock: Clock) -> None:  # fmt: skip
        self.book = book
        self.facts = facts
        self.cfg = cfg
        self.deny = tuple(deny)
        self.clock = clock

    async def check(self, domain: str, sample_url: str | None) -> Checked | None:
        """The admission check of one site (deny-list and classifieds, robots for `sample_url` or the home page, a
        forbidding terms clause quoted and verified on the page, readable content): writes `sources.access`, its
        evidence and the next re-check, journals an access change. None when the facts could not be gathered or
        the source does not exist."""
        try:
            facts = await self.facts.gather(domain, sample_url)
        except Exception:  # noqa: BLE001 - one site never stops the run
            log.exception("registry.admission_failed domain=%s", domain)
            return None
        verdict = admit(facts, self.deny)
        now = self.clock.now()
        days = self.cfg.recheck_active_days if verdict.access in ADMITTING else self.cfg.recheck_blocked_days
        before = await self.book.record_verdict(domain, verdict, now + timedelta(days=days), now)
        return None if before is None else Checked(verdict, before, before != verdict.access)

    async def admit_pending(self) -> dict[str, int]:
        """Check the sites due (at most `PER_RUN`) while today's discovery budget lasts; counts checked, admitted
        and blocked (an access that changed)."""
        out = {"checked": 0, "admitted": 0, "blocked": 0}
        for domain in await self.book.due(PER_RUN, self.clock.now()):
            if await self.spent_today() >= self.cfg.discovery_eur_per_day:
                break
            checked = await self.check(domain, None)
            if checked is None:
                continue
            out["checked"] += 1
            if checked.changed:
                out["admitted" if checked.admission.access in ADMITTING else "blocked"] += 1
        return out

    async def spent_today(self) -> float:
        """What the terms reader cost over the last 24 hours (EUR)."""
        return await self.book.terms_spent_since(self.clock.now() - BUDGET_WINDOW)
