"""What the running job knows beyond its arguments: the registry's plan for the job (source order and the domains
never to read) and the registry candidates its `site:` queries named. Context variables, set for the job's duration
by `stages/opening.py`, read by planning, ranking and storage; a page of either kind of candidate is "unverified".
"""

from __future__ import annotations

from contextvars import ContextVar

from automind.acquisition.registry.api import Plan

# spec 010 US6-US8: the registry's plan for the running job (source order and the domains never to read)
current_plan: ContextVar[Plan | None] = ContextVar("current_plan", default=None)
# spec 011 FR-022 (010 T059): registry candidates the running job queried with `site:` (filled by the planners)
current_candidates: ContextVar[set[str] | None] = ContextVar("current_candidates", default=None)


def is_unverified(domain: str) -> bool:
    """A page of a registry candidate, from the job's plan or one of its `site:` queries: its values are labelled
    "unverified source" and its domain counts as half an independent source."""
    d = domain.lower().removeprefix("www.")
    plan = current_plan.get()
    if plan is not None and plan.unverified(d):
        return True
    return any(d == c or d.endswith("." + c) for c in current_candidates.get() or ())


def note_candidates(domains: list[str]) -> None:
    """Remember registry candidates the running job is about to query (nothing outside a job)."""
    candidates = current_candidates.get()
    if candidates is not None:
        candidates.update(domains)
