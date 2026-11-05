"""The scout (spec 011 US5 T108, research R13; closes 010 T065 "discovery"): finds new sources for gaps.

A gap is an (area, market) pair that, in the last `registry.discovery.gap_window_days`, had research with no
accepted value (a no-data outcome) or fewer active sources than `discovery.min_active_per_area_market`. For each gap
(most no-data outcomes first) the scout builds at most `discovery.per_gap_per_day` queries from the area's `open`
templates in `config/queries.yaml` for the popular variant with that gap, in the market's language (the `scout`
model role only rewords the queries; it never sees a page, and code checks what it returns), and searches with the
market's locale (`config/search.yaml: markets`). Domains it has never seen become `discovered` and go through the
existing admission check (`registry/application/admission.check_domain`: deny-list and classifieds, robots for the
page the search returned, a forbidding terms clause quoted and verified on the page, readable content); the result
moves the capability to `candidate` or `blocked` through `registry/domain/lifecycle` and `registry/domain/limits`.

It also learns where a source keeps its data (the locator): the path prefix shared by at least three pages that
gave accepted values becomes the capability's `url_patterns`; the registry's `site:` queries then name
`domain/prefix`.

Bounds: the daily budget `agents.budgets.scout` (worker budget of the `scout` kind) and, together with the
admission's terms reader, `registry.discovery.eur_per_day`; `per_gap_per_day` queries per gap; at most
`MAX_GAPS_PER_RUN` gaps and `MAX_NEW_PER_GAP` new domains per gap; prices only on European markets. It writes only
registry rows; every addition and status change is journalled in `registry_changes` (author `scout`) with its reason
and evidence (the gap, the query, the hit, the admission facts, `change_id` = the journal row of the addition).
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from automind.acquisition.registry.application import admission
from automind.acquisition.registry.domain import limits
from automind.acquisition.registry.domain.lifecycle import CapState, transition
from automind.acquisition.registry.domain.seed_rules import denied
from automind.acquisition.worker.budget import BudgetExceeded
from automind.domain import evidence as ev
from automind.domain import research_plan, search_plan
from automind.domain.search_plan import Identity
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db import models as db
from automind.infrastructure.db.session import sessionmaker
from automind.insight.metrics import prom

log = logging.getLogger(__name__)
ROLE = "scout"
AUTHOR = "scout"  # registry_changes.author (migration 0023)
PROMPT = Path(__file__).resolve().parents[2] / "orchestration" / "prompts" / "scout.md"
MAX_GAPS_PER_RUN = 6
MAX_NEW_PER_GAP = 5
PATTERN_MIN = 3  # accepted pages under one path prefix before it is a pattern
PATTERN_MAX = 2
PATTERN_LOOKBACK_DAYS = 90
EST_REWORD_EUR = 0.0005  # one flash-lite call on a few short queries
EST_ADMISSION_EUR = 0.002  # one terms-reader call on ≤ 20,000 characters
QUERY_EUR_DEFAULT = 0.002
T = TypeVar("T", bound=BaseModel)


# --- pure helpers ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Job:
    """A finished research job of an area: its variant and how many values it accepted."""

    area: str
    variant_id: str | None
    accepted: int


@dataclass(frozen=True)
class Gap:
    area: str
    market: str
    nodata: int  # research jobs of the area with no accepted value in the window
    active: int  # active capabilities of (area, market)
    variant_id: str | None  # the popular variant with the gap
    reason: str

    @property
    def key(self) -> str:
        return f"{self.area}|{self.market}"


@dataclass(frozen=True)
class Found:
    domain: str
    url: str
    title: str
    rank: int


def area_markets(search_cfg: Mapping[str, Any], area: str) -> list[str]:
    """The markets an area is searched on (config/search.yaml); prices only on European markets (010 FR-020)."""
    markets = list((search_cfg.get("area_markets") or {}).get(area) or search_cfg.get("default_markets") or ["ES"])
    if area in research_plan.PRICE_AREAS:
        markets = [m for m in markets if m in research_plan.EUROPE]
    return markets


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def find_gaps(
    jobs: Iterable[Job],
    active: Mapping[tuple[str, str], int],
    search_cfg: Mapping[str, Any],
    min_active: int,
    areas: Collection[str] | None = None,
) -> list[Gap]:
    """Gaps among the areas researched in the window, most no-data outcomes first, then the fewest active."""
    by_area: dict[str, list[Job]] = defaultdict(list)
    for j in jobs:
        if areas is None or j.area in areas:
            by_area[j.area].append(j)
    out: list[tuple[tuple[int, int, int], Gap]] = []
    for area, js in by_area.items():
        empty = [j for j in js if j.accepted <= 0]
        popular = Counter(j.variant_id for j in (empty or js) if j.variant_id).most_common(1)
        vid = popular[0][0] if popular else None
        for i, market in enumerate(area_markets(search_cfg, area)):
            n_active = int(active.get((area, market), 0))
            if not empty and n_active >= min_active:
                continue
            why = []
            if empty:
                why.append(f"{_plural(len(empty), 'no-data outcome')} in the window")
            if n_active < min_active:
                why.append(f"{_plural(n_active, 'active source')} (minimum {min_active})")
            gap = Gap(area, market, len(empty), n_active, vid, f"{area}/{market}: " + ", ".join(why))
            out.append(((-len(empty), n_active, i), gap))
    out.sort(key=lambda x: (x[0], x[1].area))
    return [g for _, g in out]


def build_queries(
    templates: Sequence[str], car: Identity, market: str, market_names: Mapping[str, str] | None, limit: int
) -> list[str]:
    """The area's open templates for the car under its name on the market; `{sites}` templates are not open."""
    ident = search_plan.for_market(car, market, market_names)
    out: list[str] = []
    for t in templates:
        if len(out) >= limit:
            break
        if "{sites}" in t:
            continue
        q = search_plan._render(t, ident)
        if q and q.lower() not in {x.lower() for x in out}:
            out.append(q)
    return out


def checked_rewording(original: Sequence[str], proposed: Sequence[str], make: str) -> list[str]:
    """Code's check of the `scout` role's wording: same count; each query short, without operators or sites, and
    still naming the make; otherwise the template's query stands."""
    if len(proposed) != len(original):
        return list(original)
    out = []
    for o, p in zip(original, proposed, strict=True):
        t = " ".join(str(p).split())
        low = t.lower()
        ok = (
            search_plan.accept_ai_query(t, [], max_len=200)
            and make.lower() in low
            and "site:" not in low
            and "http" not in low
            and '"' not in t
        )
        out.append(t if ok else o)
    return out


def found_domains(
    hits: Iterable[tuple[str, str]], known: Collection[str], deny: Sequence[str], limit: int
) -> list[Found]:
    """New domains among the hits (url, title), in rank order: never a known or deny-listed one, one per domain."""
    out: list[Found] = []
    seen = set(known)
    for rank, (url, title) in enumerate(hits, 1):
        if len(out) >= limit:
            break
        d = ev.domain_of(url)
        if not d or "." not in d or d in seen or denied(d, deny) or ev.is_denied(url):
            continue
        seen.add(d)
        out.append(Found(d, url, title, rank))
    return out


def path_prefixes(urls: Iterable[str], min_examples: int = PATTERN_MIN, max_patterns: int = PATTERN_MAX) -> list[str]:
    """The locator: directory prefixes shared by at least `min_examples` accepted pages, the widest cover first
    (a prefix inside a chosen one adds nothing to a `site:` query)."""
    support: Counter[str] = Counter()
    for u in urls:
        dirs = [p for p in (urlparse(u).path or "").split("/") if p][:-1]  # the last segment is the page
        for k in range(1, len(dirs) + 1):
            support["/" + "/".join(dirs[:k]) + "/"] += 1
    ok = [(n, p) for p, n in support.items() if n >= min_examples]
    ok.sort(key=lambda x: (-x[0], x[1].count("/"), x[1]))
    out: list[str] = []
    for _, p in ok:
        if len(out) >= max_patterns:
            break
        if not any(p.startswith(q) or q.startswith(p) for q in out):
            out.append(p)
    return out


def budget_left(scout_cap: float, scout_spent: float, discovery_cap: float, discovery_spent: float) -> float:
    return round(max(0.0, min(scout_cap - scout_spent, discovery_cap - discovery_spent)), 6)


def addition_reason(gap: Gap, query: str, rank: int) -> str:
    return (
        f"scout: gap {gap.area}/{gap.market} ({_plural(gap.nodata, 'no-data outcome')}, {gap.active} active); "
        f'hit #{rank} of "{query}"'
    )


# --- ports -------------------------------------------------------------------------------------------------------


class Reworded(BaseModel):
    queries: list[str] = Field(default_factory=list, max_length=10)


class LLM(Protocol):
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T: ...


class GatewayLLM:
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        from automind.infrastructure import llm_gateway  # noqa: PLC0415

        return await llm_gateway.structured(role, schema, system, user)


class Searcher(Protocol):
    async def search(self, query: str, *, market: str = "ES", area: str | None = None, fresh: bool = False) -> Any: ...


Charge = Callable[[float], Awaitable[None]]


@dataclass
class Spend:
    """Today's spend against both caps; `charge` is the worker's guard of the `scout` kind (when run there)."""

    scout_cap: float
    discovery_cap: float
    scout_spent: float = 0.0
    discovery_spent: float = 0.0
    outer: Charge | None = None
    run: float = 0.0

    def left(self) -> float:
        return budget_left(self.scout_cap, self.scout_spent + self.run, self.discovery_cap,
                           self.discovery_spent + self.run)  # fmt: skip

    async def take(self, eur: float) -> None:
        if eur > self.left() + 1e-9:
            raise BudgetExceeded(f"scout: {eur:.4f} EUR over today's budget (left {self.left():.4f})")
        if self.outer is not None:
            await self.outer(eur)
        self.run += eur


@dataclass
class Run:
    search: Searcher
    llm: LLM
    gather: Any
    spend: Spend
    reg: Mapping[str, Any]
    search_cfg: Mapping[str, Any]
    deny: tuple[str, ...]
    query_eur: float
    task_id: str | None = None
    used: dict[str, int] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=lambda: {"gaps": 0, "queries": 0, "added": 0, "candidate": 0,
                                                            "blocked": 0, "unknown": 0, "patterns": 0})  # fmt: skip


# --- database ----------------------------------------------------------------------------------------------------


async def _jobs(days: int) -> list[Job]:
    since = db.now() - timedelta(days=days)
    async with sessionmaker()() as s:
        q = select(db.ResearchJob.area, db.ResearchJob.variant_id, db.ResearchJob.accepted).where(
            db.ResearchJob.status == "DONE", db.ResearchJob.finished_at >= since
        )
        return [Job(a, v, int(n or 0)) for a, v, n in (await s.execute(q)).all()]


async def _active() -> dict[tuple[str, str], int]:
    async with sessionmaker()() as s:
        q = (
            select(db.CapabilityRow.area, db.CapabilityRow.market, func.count())
            .where(db.CapabilityRow.status == "active")
            .group_by(db.CapabilityRow.area, db.CapabilityRow.market)
        )
        return {(a, m): int(n) for a, m, n in (await s.execute(q)).all()}


async def gaps_now(reg: Mapping[str, Any], search_cfg: Mapping[str, Any], templates: Mapping[str, Any]) -> list[Gap]:
    disc = reg.get("discovery") or {}
    areas = {a for a, t in templates.items() if isinstance(t, dict) and t.get("open")}
    return find_gaps(await _jobs(int(disc.get("gap_window_days", 7))), await _active(), search_cfg,
                     int(disc.get("min_active_per_area_market", 2)), areas)  # fmt: skip


async def _identity(variant_id: str | None) -> tuple[Identity, dict[str, str]] | None:
    if not variant_id:
        return None
    async with sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
    if v is None:
        return None
    years = f"{v.generation_years_from}-{v.generation_years_to or ''}" if v.generation_years_from else ""
    try:
        names = search_plan.market_names_of(load_yaml("aliases.yaml").get("market_names"), v.make, v.model,
                                            v.generation)  # fmt: skip
    except FileNotFoundError:
        names = {}
    return Identity(v.make, v.model, v.generation, v.variant_name, years), names


async def _known() -> set[str]:
    async with sessionmaker()() as s:
        return set((await s.execute(select(db.SourceRow.domain))).scalars())


async def _add(f: Found, gap: Gap, query: str, task_id: str | None) -> tuple[str, str] | None:
    """A new source and its `discovered` capability for the gap, journalled; (capability id, change id)."""
    async with sessionmaker()() as s:
        if await s.get(db.SourceRow, f.domain) is not None:
            return None
        s.add(db.SourceRow(domain=f.domain, source_type="PUBLICATION", family=f.domain, markets=[gap.market]))
        await s.flush()
        cap = db.CapabilityRow(domain=f.domain, area=gap.area, market=gap.market, status="discovered")
        s.add(cap)
        await s.flush()
        ch = db.RegistryChange(
            author=AUTHOR,
            capability_id=cap.id,
            domain=f.domain,
            change="added",
            after={"status": "discovered", "area": gap.area, "market": gap.market},
            reason=addition_reason(gap, query, f.rank),
            evidence={
                "agent": ROLE,
                "task_id": task_id,
                "gap": gap.reason,
                "variant_id": gap.variant_id,
                "query": query,
                "url": f.url,
                "title": f.title[:200],
                "rank": f.rank,
            },  # fmt: skip
        )
        s.add(ch)
        await s.commit()
    prom.inc("registry_changes", change="added", author=AUTHOR)
    return cap.id, ch.id


async def _settle(cap_id: str, change_id: str, sample: str, checked: admission.Checked | None, r: Run) -> str:
    """discovered → candidate | blocked by the lifecycle after the admission check, within the hard limits."""
    async with sessionmaker()() as s:
        cap = await s.get(db.CapabilityRow, cap_id)
        src = await s.get(db.SourceRow, cap.domain) if cap is not None else None
        if cap is None or src is None or cap.status != "discovered":
            return "gone"
        st = CapState(cap.status, cap.attempts, cap.acc_lb, cap.yield_, cap.status_since, src.access)
        mv = transition(st, r.reg, db.now())
        if mv is None:
            return "unknown"  # not enough facts: stays discovered, re-checked by the admission later
        verdict = limits.check(limits.Guard(cap.domain, src.access, bool(src.frozen), cap.status), mv.to, r.deny)
        if verdict == "refused":
            return "refused"
        change = "promoted" if mv.to == "candidate" else "blocked"
        adm = checked.admission if checked is not None else None
        s.add(
            db.RegistryChange(
                author=AUTHOR,
                capability_id=cap.id,
                domain=cap.domain,
                change=change,
                before={"status": cap.status},
                after={"status": mv.to},
                reason=f"scout: {mv.reason}" + (f" ({adm.reason})" if adm else ""),
                evidence={
                    "agent": ROLE,
                    "task_id": r.task_id,
                    "change_id": change_id,
                    "access": src.access,
                    "sample_url": sample,
                    **({"admission": adm.evidence} if adm else {}),
                },  # fmt: skip
                held=verdict == "held",
            )
        )
        if verdict == "apply":
            cap.status, cap.status_since = mv.to, db.now()
        await s.commit()
    prom.inc("registry_changes", change=change, author=AUTHOR)
    return mv.to if verdict == "apply" else "held"


async def learn_patterns(deny: tuple[str, ...], task_id: str | None = None) -> int:
    """The locator: path prefixes of the pages that gave accepted values, per capability, journalled when they
    change (a frozen source's change is held; a blocked one is never touched)."""
    since = db.now() - timedelta(days=PATTERN_LOOKBACK_DAYS)
    async with sessionmaker()() as s:
        q = select(db.RegistryAttempt.capability_id, db.RegistryAttempt.url).where(
            db.RegistryAttempt.outcome == "accepted",
            db.RegistryAttempt.url.is_not(None),
            db.RegistryAttempt.created_at >= since,
        )
        urls: dict[str, list[str]] = defaultdict(list)
        for cid, url in (await s.execute(q)).all():
            urls[cid].append(url)
        n = 0
        for cid, us in urls.items():
            if len(us) < PATTERN_MIN:
                continue
            cap = await s.get(db.CapabilityRow, cid)
            src = await s.get(db.SourceRow, cap.domain) if cap is not None else None
            if cap is None or src is None:
                continue
            own = [u for u in us if ev.domain_of(u) == cap.domain or ev.domain_of(u).endswith("." + cap.domain)]
            pats = path_prefixes(own)
            if pats == list(cap.url_patterns or []):
                continue
            verdict = limits.check(limits.Guard(cap.domain, src.access, bool(src.frozen), cap.status), cap.status, deny)
            if verdict == "refused":
                continue
            covered = sum(1 for u in own if any((urlparse(u).path or "").startswith(p) for p in pats))
            s.add(
                db.RegistryChange(
                    author=AUTHOR,
                    capability_id=cap.id,
                    domain=cap.domain,
                    change="url_patterns",
                    before={"url_patterns": list(cap.url_patterns or [])},
                    after={"url_patterns": pats},
                    reason=f"scout locator: {covered} of {len(own)} accepted pages of {cap.area}/{cap.market} under "
                    + (", ".join(pats) or "no common path"),
                    evidence={"agent": ROLE, "task_id": task_id, "examples": own[:5]},
                    held=verdict == "held",
                )
            )
            if verdict == "apply":
                cap.url_patterns = pats
                n += 1
        await s.commit()
    return n


async def _scout_spent_today() -> float:
    day = db.now().replace(hour=0, minute=0, second=0, microsecond=0)
    async with sessionmaker()() as s:
        q = text("SELECT coalesce(sum(cost_eur),0) FROM acq_tasks WHERE kind = 'scout' AND finished_at >= :d")
        return float((await s.execute(q, {"d": day})).scalar() or 0)


async def used_today() -> dict[str, int]:
    """Queries per gap already spent today (from today's finished scout tasks)."""
    day = db.now().replace(hour=0, minute=0, second=0, microsecond=0)
    out: Counter[str] = Counter()
    async with sessionmaker()() as s:
        q = select(db.AcqTask.result).where(
            db.AcqTask.kind == "scout", db.AcqTask.state == "done", db.AcqTask.finished_at >= day
        )
        for (res,) in (await s.execute(q)).all():
            out.update({str(k): int(v) for k, v in ((res or {}).get("per_gap") or {}).items()})
    return dict(out)


async def runs_today() -> int:
    day = db.now().replace(hour=0, minute=0, second=0, microsecond=0)
    async with sessionmaker()() as s:
        q = select(func.count()).where(
            db.AcqTask.kind == "scout", db.AcqTask.state == "done", db.AcqTask.finished_at >= day
        )
        return int((await s.execute(q)).scalar() or 0)


# --- the run -----------------------------------------------------------------------------------------------------


async def _reword(r: Run, queries: list[str], market: str, make: str) -> list[str]:
    if not queries:
        return queries
    hl = str(((r.search_cfg.get("markets") or {}).get(market) or {}).get("hl") or "en")
    user = f"Market: {market}\nLanguage: {hl}\nQueries:\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(queries, 1))
    try:
        await r.spend.take(EST_REWORD_EUR)
        out = await r.llm.structured(ROLE, Reworded, PROMPT.read_text(encoding="utf-8"), user)
    except BudgetExceeded:
        raise
    except Exception:  # noqa: BLE001 - the templates' wording stands
        log.warning("scout.reword_failed market=%s", market)
        return queries
    return checked_rewording(queries, out.queries, make)


def _hits(res: Any) -> list[tuple[str, str]]:
    return [(str(getattr(h, "url", "")), str(getattr(h, "title", "") or "")) for h in (res or [])]


async def _scout_gap(r: Run, gap: Gap, left: int) -> list[tuple[str, str, str]]:
    """Searches for one gap; the new capabilities as (capability id, change id, sample url)."""
    who = await _identity(gap.variant_id)
    tpl = list((load_yaml("queries.yaml").get(gap.area) or {}).get("open") or [])
    if who is None or not tpl:
        return []
    car, names = who
    queries = await _reword(r, build_queries(tpl, car, gap.market, names, left), gap.market, car.make)
    added: list[tuple[str, str, str]] = []
    for q in queries:
        await r.spend.take(r.query_eur)
        r.used[gap.key] = r.used.get(gap.key, 0) + 1
        r.stats["queries"] += 1
        try:
            res = await r.search.search(q, market=gap.market, area=gap.area)
        except Exception:  # noqa: BLE001 - a failed search is not a finding
            log.warning("scout.search_failed gap=%s", gap.key)
            continue
        for f in found_domains(_hits(res), await _known(), r.deny, MAX_NEW_PER_GAP - len(added)):
            got = await _add(f, gap, q, r.task_id)
            if got is not None:
                added.append((*got, f.url))
                r.stats["added"] += 1
    return added


async def _admit(r: Run, added: list[tuple[str, str, str]]) -> None:
    for cap_id, change_id, sample in added:
        await r.spend.take(EST_ADMISSION_EUR)
        domain = ev.domain_of(sample)
        checked = await admission.check_domain(domain, sample, dict(r.reg), r.deny, r.llm, r.gather)
        out = await _settle(cap_id, change_id, sample, checked, r)
        key = out if out in ("candidate", "blocked") else "unknown"
        r.stats[key] += 1


def _query_eur(search_cfg: Mapping[str, Any]) -> float:
    try:
        prov = (load_yaml("prices.yaml").get("search") or {}).get("providers") or {}
    except FileNotFoundError:
        return QUERY_EUR_DEFAULT
    return float((prov.get(str(search_cfg.get("provider") or "serper")) or {}).get("eur_per_query", QUERY_EUR_DEFAULT))


async def run(
    search: Searcher,
    *,
    llm: LLM | None = None,
    gather: Any = None,
    charge: Charge | None = None,
    used: Mapping[str, int] | None = None,
    task_id: str | None = None,
    reg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One scout run: the locator, then the gaps within the budgets. Returns the stats and `per_gap` queries."""
    reg = reg if reg is not None else load_yaml("registry.yaml")
    disc = reg.get("discovery") or {}
    search_cfg = load_yaml("search.yaml")
    scout_spent = await _scout_spent_today()
    spend = Spend(float((load_yaml("agents.yaml").get("budgets") or {}).get("scout", 0.10)),
                  float(disc.get("eur_per_day", 0.20)), scout_spent,
                  scout_spent + await admission.spent_today(), charge)  # fmt: skip
    r = Run(search, llm or GatewayLLM(), gather, spend, reg, search_cfg, admission.denylist(), _query_eur(search_cfg),
            task_id, dict(used or {}))  # fmt: skip
    r.stats["patterns"] = await learn_patterns(r.deny, task_id)
    gaps = await gaps_now(reg, search_cfg, load_yaml("queries.yaml"))
    per_gap = int(disc.get("per_gap_per_day", 3))
    before = dict(r.used)
    added: list[tuple[str, str, str]] = []
    try:
        for gap in gaps[:MAX_GAPS_PER_RUN]:
            left = per_gap - r.used.get(gap.key, 0)
            if left <= 0:
                continue
            r.stats["gaps"] += 1
            added += await _scout_gap(r, gap, left)
        await _admit(r, added)
    except BudgetExceeded:
        r.stats["stopped"] = "budget"
    async with sessionmaker()() as s:
        s.add(db.RegistryRun(kind="scout", finished_at=db.now(), changes=r.stats["added"],
                             discovery_queries=r.stats["queries"], cost_eur=round(spend.run, 4)))  # fmt: skip
        await s.commit()
    r.stats["per_gap"] = {k: v - before.get(k, 0) for k, v in r.used.items() if v - before.get(k, 0)}
    r.stats["eur"] = round(spend.run, 4)
    r.stats["open_gaps"] = len(gaps)
    return r.stats
