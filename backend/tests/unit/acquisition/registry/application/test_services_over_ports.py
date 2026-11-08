"""Spec 012 A4a: the registry's services over fake ports — the plan, the attempts, signals, admission, review and
seed, each with its failure path (a store down, facts that cannot be gathered, the budget spent)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from automind.acquisition.registry.api import Attempt, TruthSignalIn
from automind.acquisition.registry.application.admission import SiteAdmission
from automind.acquisition.registry.application.ports import RegistryStoreUnavailable
from automind.acquisition.registry.application.review import DailyReview
from automind.acquisition.registry.application.seed import RegistrySeed, SeedSources
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.domain.admission import Admission, AdmissionFacts
from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.domain.model import Capability, Source
from automind.acquisition.registry.domain.records import CapabilityView, ReviewedCapability, SourceState
from automind.acquisition.registry.domain.review import ReviewFacts, ReviewPlan
from automind.acquisition.registry.domain.seed_rules import Favourite

NOW = datetime(2026, 11, 8, tzinfo=UTC)
ON = RegistryConfig(autonomy=True)


class Clock:
    def now(self) -> datetime:
        return NOW


class Caps:
    def __init__(self, rows: list[CapabilityView], down: bool = False, spent: float = 0.0) -> None:
        self.rows, self.down, self.spent = rows, down, spent
        self.recorded: list[Attempt] = []

    def _check(self) -> None:
        if self.down:
            raise RegistryStoreUnavailable("down")

    async def capabilities(self, area: str, markets: list[str]) -> list[CapabilityView]:
        self._check()
        return [r for r in self.rows if r.market in markets]

    async def queryable(self, area: str, markets: list[str]) -> list[CapabilityView]:
        self._check()
        return [r for r in self.rows if r.market in markets]

    async def explore_spent(self) -> float:
        return self.spent

    async def record(self, attempts: list[Attempt]) -> None:
        self._check()
        self.recorded += attempts


class Signals:
    def __init__(self, down: bool = False) -> None:
        self.down = down
        self.weights: list[float] = []

    async def signal(self, s: TruthSignalIn, weight: float) -> str:
        if self.down:
            raise RegistryStoreUnavailable("down")
        self.weights.append(weight)
        return "sig-1"

    async def resolve(self, signal_id: str, vector: dict[str, float], components: dict[str, str], note: str) -> bool:
        return False


class Pages:
    def __init__(self) -> None:
        self.marked: list[tuple[str, int, str | None]] = []

    async def mark(self, snapshot_id: str, accepted_values: int, variant_id: str | None) -> None:
        self.marked.append((snapshot_id, accepted_values, variant_id))


def _cap(domain: str, status: str, score: float = 0.0, market: str = "ES") -> CapabilityView:
    return CapabilityView(domain=domain, area="specs", market=market, status=status, score=score, access="ok")


def _svc(caps: Caps, cfg: RegistryConfig = ON, signals: Signals | None = None,
         pages: Pages | None = None) -> RegistryService:  # fmt: skip
    return RegistryService(caps, signals or Signals(), pages or Pages(), cfg)


# --- RegistryService ---------------------------------------------------------------------------------------------


async def test_plan_orders_active_by_score_and_skips_blocked() -> None:
    caps = Caps([_cap("b.es", "active", 0.2), _cap("a.es", "active", 0.9), _cap("x.es", "blocked"),
                 _cap("d.es", "degraded", 0.99)])  # fmt: skip
    plan = await _svc(caps).plan("specs", ["ES"], None, seed=1)
    assert [s.domain for s in plan.sources] == ["a.es", "b.es", "d.es"] and plan.skip == ["x.es"]
    off = await _svc(caps, RegistryConfig()).plan("specs", ["ES"], None)
    assert off.sources == [] and off.skip == ["x.es"] and not off.autonomy


async def test_plan_draws_a_candidate_within_the_exploration_budget() -> None:
    rows = [_cap("a.es", "active", 0.9), _cap("c.es", "candidate")]
    plan = await _svc(Caps(rows)).plan("specs", ["ES"], None, seed=7)
    assert [(s.domain, s.status, s.unverified) for s in plan.sources] == [
        ("a.es", "active", False), ("c.es", "candidate", True)
    ]  # fmt: skip
    spent = await _svc(Caps(rows, spent=1.0)).plan("specs", ["ES"], None, seed=7)
    assert [s.domain for s in spent.sources] == ["a.es"]


async def test_store_down_gives_an_empty_plan_and_no_sources() -> None:
    svc = _svc(Caps([_cap("a.es", "active")], down=True))
    plan = await svc.plan("specs", ["ES"], None)
    assert plan.sources == [] and plan.skip == []
    assert await svc.sources_for("specs", ["ES"], 5) == []


async def test_attempts_counted_then_pages_marked_and_nothing_marked_when_the_store_is_down() -> None:
    attempts = [
        Attempt(area="specs", market="ES", url="https://a.es/1", outcome="accepted", values=3, snapshot_id="s1",
                variant_id="v"),
        Attempt(area="specs", market="ES", url="https://a.es/2", outcome="empty", values=0, snapshot_id="s2"),
        Attempt(area="specs", market="ES", url="https://a.es/3", outcome="error"),
    ]  # fmt: skip
    caps, pages = Caps([]), Pages()
    await _svc(caps, pages=pages).record(attempts)
    assert len(caps.recorded) == 3 and pages.marked == [("s1", 3, "v"), ("s2", 0, None)]
    down, pages = Caps([], down=True), Pages()
    await _svc(down, pages=pages).record(attempts)
    assert pages.marked == []


async def test_signal_weight_from_config_and_none_when_the_store_is_down() -> None:
    sig = TruthSignalIn(kind="agreement", verdict="right", domain="a.es", area="specs")
    signals = Signals()
    cfg = RegistryConfig(weights={"agreement": 0.3})
    assert await _svc(Caps([]), cfg, signals).signal(sig) == "sig-1" and signals.weights == [0.3]
    assert await _svc(Caps([]), cfg, Signals(down=True)).signal(sig) is None


# --- SiteAdmission -----------------------------------------------------------------------------------------------


class Book:
    def __init__(self, due: list[str], access: dict[str, str], spent: float = 0.0, down: bool = False) -> None:
        self.due_domains, self.access, self.spent, self.down = due, access, spent, down
        self.written: list[tuple[str, str, datetime]] = []

    async def due(self, limit: int, now: datetime) -> list[str]:
        return self.due_domains[:limit]

    async def record_verdict(self, domain: str, verdict: Admission, next_check_at: datetime,
                             now: datetime) -> str | None:  # fmt: skip
        if self.down:
            raise RegistryStoreUnavailable("down")
        if domain not in self.access:
            return None
        before, self.access[domain] = self.access[domain], verdict.access
        self.written.append((domain, verdict.access, next_check_at))
        return before

    async def terms_spent_since(self, since: datetime) -> float:
        return self.spent


class Facts:
    async def gather(self, domain: str, sample_url: str | None) -> AdmissionFacts:
        if domain == "broken.es":
            raise OSError("network")
        return AdmissionFacts(domain, domain != "nobots.es", False, content_chars=5000)


def _admission(book: Book) -> SiteAdmission:
    return SiteAdmission(book, Facts(), RegistryConfig(discovery_eur_per_day=0.2), ("deny.es",), Clock())


async def test_admission_writes_verdicts_with_their_recheck_and_skips_what_it_cannot_judge() -> None:
    book = Book(["ok.es", "nobots.es", "broken.es", "gone.es"], {"ok.es": "unknown", "nobots.es": "unknown"})
    out = await _admission(book).admit_pending()
    assert out == {"checked": 2, "admitted": 1, "blocked": 1}
    assert [(d, a, t - NOW) for d, a, t in book.written] == [
        ("ok.es", "ok", timedelta(days=90)), ("nobots.es", "robots_blocked", timedelta(days=180))
    ]  # fmt: skip


async def test_admission_stops_at_the_budget_and_a_store_failure_propagates() -> None:
    assert await _admission(Book(["ok.es"], {"ok.es": "unknown"}, spent=0.5)).admit_pending() == {
        "checked": 0, "admitted": 0, "blocked": 0
    }  # fmt: skip
    with pytest.raises(RegistryStoreUnavailable):
        await _admission(Book(["ok.es"], {"ok.es": "unknown"}, down=True)).check("ok.es", None)


# --- DailyReview -------------------------------------------------------------------------------------------------


class Session:
    def __init__(self, caps: list[ReviewedCapability], sources: dict[str, SourceState]) -> None:
        self.caps, self.sources = caps, sources
        self.applied: ReviewPlan | None = None

    async def load(self) -> tuple[list[ReviewedCapability], ReviewFacts]:
        return self.caps, ReviewFacts(self.sources)

    def apply(self, plan: ReviewPlan) -> None:
        self.applied = plan


class Reviews:
    def __init__(self, session: Session, fail: bool = False) -> None:
        self.s, self.fail = session, fail
        self.kinds: list[str] = []

    @asynccontextmanager
    async def session(self, kind: str) -> AsyncIterator[Session]:
        self.kinds.append(kind)
        if self.fail:
            raise RegistryStoreUnavailable("down")
        yield self.s


def _reviewed(cid: str, status: str, acc_lb: float, yield_: float, recent: tuple[bool, ...]) -> ReviewedCapability:
    score = acc_lb * yield_
    return ReviewedCapability(id=cid, domain=f"{cid}.es", area="specs", market="ES", status=status,
                              status_since=NOW - timedelta(days=2), attempts=20, acc_lb=acc_lb, yield_=yield_,
                              score=score, score_before=score, signals_w=10, recent=recent)  # fmt: skip


async def test_review_applies_the_plan_and_holds_a_frozen_source() -> None:
    session = Session([_reviewed("good", "candidate", 0.8, 0.7, (True,) * 10),
                       _reviewed("bad", "active", 0.1, 0.0, (False,) * 10)],
                      {"good.es": SourceState("ok"), "bad.es": SourceState("ok", frozen=True)})  # fmt: skip
    review = DailyReview(Reviews(session), _admission(Book([], {})), ON, (), Clock())
    stats = await review.run("test", admit_sites=False)
    assert stats["changes"] == 1 and stats["held"] == 1 and session.applied is not None
    assert [(m.capability_id, m.to) for m in session.applied.moves] == [("good", "active")]
    assert [(e.domain, e.change, e.held) for e in session.applied.journal][:2] == [
        ("good.es", "promoted", False), ("bad.es", "demoted", True)
    ]  # fmt: skip


async def test_review_does_nothing_without_autonomy_and_a_store_failure_propagates() -> None:
    reviews = Reviews(Session([], {}))
    off = DailyReview(reviews, _admission(Book([], {})), RegistryConfig(), (), Clock())
    assert await off.run() == {"changes": 0, "held": 0, "refused": 0, "reordered": 0} and reviews.kinds == []
    down = DailyReview(Reviews(Session([], {}), fail=True), _admission(Book([], {})), ON, (), Clock())
    with pytest.raises(RegistryStoreUnavailable):
        await down.run(admit_sites=False)


# --- RegistrySeed ------------------------------------------------------------------------------------------------


class Seeds:
    def __init__(self, empty: bool) -> None:
        self.empty = empty
        self.reasons: list[tuple[str, int]] = []

    async def is_empty(self) -> bool:
        return self.empty

    async def seed(self, items: Iterable[tuple[Source, Sequence[Capability]]], reason: str) -> int:
        n = sum(len(caps) for _, caps in items)
        self.reasons.append((reason, n))
        return n


async def test_seed_runs_only_on_an_empty_registry() -> None:
    sources = SeedSources([Favourite("km77.com", areas=("specs", "price"), markets=("ES",))], [], (), {})
    assert await RegistrySeed(Seeds(empty=False), sources).run_if_empty() is None
    seeds = Seeds(empty=True)
    assert await RegistrySeed(seeds, sources).run_if_empty() == {"favourites": 2, "survey": 0}
