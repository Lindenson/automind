"""The registry's daily review (spec 010 US7, T066): admit the sites met in searches, then fade, rescore and move
statuses, journalling every change. Only with `registry.autonomy: true`.

Every move passes the hard limits (domain/limits.py); a frozen source gets a "held" journal entry instead of a
change. The decisions are pure (domain/review.py); the run is one transaction (`ReviewBook.session`).

Errors: `RegistryStoreUnavailable` propagates (the worker retries the task); a failed run writes nothing, while the
verdicts of the admission step before it stay (each is its own transaction)."""

from __future__ import annotations

from collections.abc import Sequence

from automind.acquisition.registry.application.admission import SiteAdmission
from automind.acquisition.registry.application.ports import Clock, ReviewBook
from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.domain.review import ReviewFacts, plan_review

NOTHING = {"changes": 0, "held": 0, "refused": 0, "reordered": 0}


class DailyReview:
    """The review over its book, the admission of new sites, the config, the deny-list and the clock."""

    def __init__(self, book: ReviewBook, admission: SiteAdmission, cfg: RegistryConfig, deny: Sequence[str],
                 clock: Clock) -> None:  # fmt: skip
        self.book = book
        self.admission = admission
        self.cfg = cfg
        self.deny = tuple(deny)
        self.clock = clock

    async def run(self, kind: str = "daily", admit_sites: bool = True) -> dict[str, int]:
        """One review run: the counts of changes, held, refused and reordered (and `admission_*` when sites were
        admitted first). Nothing happens with autonomy off."""
        if not self.cfg.autonomy:
            return dict(NOTHING)
        stats: dict[str, int] = {}
        if admit_sites:  # sites met in searches get their admission check first (FR-019)
            stats = {f"admission_{k}": v for k, v in (await self.admission.admit_pending()).items()}
        async with self.book.session(kind) as session:
            caps, facts = await session.load()
            plan = plan_review(caps, ReviewFacts(facts.sources, facts.reverts, self.deny), self.cfg,
                               self.clock.now())  # fmt: skip
            session.apply(plan)
        return {**plan.stats, **stats}
