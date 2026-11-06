"""Accuracy signals without the user (spec 011 FR-010/FR-011, research R7-R9, T070).

Read after the fact from what research stored (accepted claims, selected `spec_values`, `gold_values`, page
relevance, the stored page), so the pipeline needs no hook to produce them:

- `gold`        each accepted numeric claim with a (non-flagged) gold value for its attribute → right or wrong;
                a selected value that is wrong while one of its claims is right → wrong for `fusion`
- `physics`     the six checks of R8 on the variant's selected values → wrong against the outlier's claims
- `agreement`   values agreeing within tolerance from k independent families → one right per family, once
- `replacement` a value that was shown alone and later lost to a more confident selection → wrong

Every wrong signal carries the vector blame of R9 computed from the claim's excerpt and stored page; a disputed one is
recorded but applied only after the `blame_judge` task settles it. Each signal is emitted once (deduplicated against
`truth_signals`). `scan()` is the worker's `reputation_signals` task. Errors never fail a job.
"""

from __future__ import annotations

import html
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from automind.acquisition.domain import agreement, physics, replacement
from automind.acquisition.domain.blame import BlameCase, blame_vector, component_keys, near
from automind.acquisition.gold import repo as gold_repo
from automind.acquisition.infrastructure.config import physics_config
from automind.acquisition.registry.api import TruthSignalIn
from automind.acquisition.registry.domain.families import family_of
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db import (
    Claim,
    Document,
    Evidence,
    GoldValueRow,
    PageRelevance,
    SourceRow,
    SpecValue,
    TruthSignal,
    Variant,
    sessionmaker,
)

log = logging.getLogger(__name__)
HYBRID = ("HEV", "PHEV", "MHEV")
HYBRID_FUELS = ("hybrid", "phev", "mhev")
FUSION = "fusion:merge@1"
_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


@dataclass
class _ClaimRow:
    c: Claim
    domain: str
    family: str
    doc_id: str | None
    doc_text: str


@dataclass
class _Ctx:
    variant: Variant
    claims: list[_ClaimRow]
    selected: dict[str, SpecValue]
    gold: dict[str, GoldValueRow]
    siblings: dict[str, list[float]]
    relevance: dict[str, tuple[str, str | None]]  # document id -> (verdict, prompt version)
    done: set[tuple[str | None, str]]  # (claim id, kind) already signalled
    agreed: set[tuple[str, str]]  # (attribute, family) with an agreement signal
    fused: set[tuple[str, float]]  # (attribute, selected value) with a fusion signal
    page_cache: dict[str, str] = field(default_factory=dict)


def _registry(cfg: Mapping[str, Any]) -> Any:
    from automind.acquisition.registry.application.service import RegistryService  # noqa: PLC0415
    from automind.acquisition.registry.infrastructure.repo import RegistryRepo  # noqa: PLC0415

    return RegistryService(RegistryRepo(cfg), cfg)


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _tol(attribute: str, g: GoldValueRow | None = None) -> tuple[str, float]:
    if g is not None and g.tolerance is not None and g.tolerance_kind:
        return (g.tolerance_kind, float(g.tolerance))
    return gold_repo.tolerance_of(attribute)


def page_text_of(raw: bytes) -> str:
    """Visible text of a stored page body (tags, scripts and styles removed) for the blame rules."""
    text = raw.decode("utf-8", errors="replace")
    return " ".join(html.unescape(_TAG.sub(" ", text)).split())


async def _page(ctx: _Ctx, row: _ClaimRow) -> str:
    sid = row.c.snapshot_id
    key = sid or f"doc:{row.doc_id}"
    if key not in ctx.page_cache:
        text = row.doc_text
        if sid:
            try:
                from automind.acquisition.snapshots import store  # noqa: PLC0415

                raw, _ = await store.load(sid)
                text = f"{text}\n{page_text_of(raw)}"
            except KeyError:
                pass
        ctx.page_cache[key] = text
    return ctx.page_cache[key]


async def _load(variant_id: str, families_cfg: Mapping[str, Any]) -> _Ctx | None:
    async with sessionmaker()() as s:
        v = await s.get(Variant, variant_id)
        if v is None:
            return None
        rows = (
            await s.execute(
                select(Claim, Evidence.domain, Evidence.document_id, Document.text)
                .join(Evidence, Claim.evidence_id == Evidence.id)
                .outerjoin(Document, Evidence.document_id == Document.id)
                .where(Claim.variant_id == variant_id, Claim.status == "ACCEPTED")
                .order_by(Claim.created_at, Claim.id)
            )
        ).all()
        domains = {d for _, d, _, _ in rows}
        fam_of = {r.domain: r.family for r in (await s.execute(select(SourceRow).where(SourceRow.domain.in_(domains))))
                  .scalars()}  # fmt: skip
        claims = [
            _ClaimRow(c, d, fam_of.get(d) or family_of(d, families_cfg), doc_id, text or "")
            for c, d, doc_id, text in rows
        ]
        selected = {
            sv.attribute: sv
            for sv in (await s.execute(select(SpecValue).where(SpecValue.variant_id == variant_id))).scalars()
        }
        rel = {
            r.document_id: (r.verdict, r.prompt_version)
            for r in (await s.execute(select(PageRelevance).where(PageRelevance.variant_id == variant_id))).scalars()
        }
        sib_ids = [
            x
            for x in (
                await s.execute(
                    select(Variant.id).where(
                        Variant.make == v.make,
                        Variant.model == v.model,
                        Variant.generation.is_not_distinct_from(v.generation),
                        Variant.id != v.id,
                    )  # fmt: skip
                )
            ).scalars()
        ]
        siblings: dict[str, list[float]] = defaultdict(list)
        if sib_ids:
            for g in (
                await s.execute(
                    select(GoldValueRow).where(GoldValueRow.variant_id.in_(sib_ids), GoldValueRow.flagged.is_(False))
                )
            ).scalars():
                if g.value_num is not None:
                    siblings[g.attribute].append(g.value_num)
        done: set[tuple[str | None, str]] = set()
        agreed: set[tuple[str, str]] = set()
        fused: set[tuple[str, float]] = set()
        for t in (await s.execute(select(TruthSignal).where(TruthSignal.variant_id == variant_id))).scalars():
            done.add((t.claim_id, t.kind))
            d = t.details or {}
            if t.kind == "agreement" and t.attribute and d.get("family"):
                agreed.add((t.attribute, str(d["family"])))
            if t.component == FUSION and t.attribute and d.get("selected") is not None:
                fused.add((t.attribute, float(d["selected"])))
    gold = gold_repo.best_by_attribute(await gold_repo.gold_for(variant_id))
    return _Ctx(v, claims, selected, gold, dict(siblings), rel, done, agreed, fused)


def _hybrid(v: Variant) -> bool:
    return (v.powertrain or "").upper() in HYBRID or (v.fuel or "").lower() in HYBRID_FUELS


async def _blame(
    ctx: _Ctx, row: _ClaimRow, truth: float | None, tol: tuple[str, float], confidence: str = "HIGH"
) -> tuple[dict[str, float], dict[str, str], bool]:
    c = row.c
    sv = ctx.selected.get(c.attribute)
    verdict, rel_version = ctx.relevance.get(row.doc_id or "", (None, None))
    case = BlameCase(
        attribute=c.attribute,
        claim_value=c.value_num,
        truth=truth,
        tolerance=tol,
        selected_value=sv.value_num if sv is not None and sv.available else None,
        producer=c.producer or ("reader" if c.extracted_by == "READER" else "extractor"),
        producer_version=c.producer_version,
        model=c.model,
        relevance=verdict,
        relevance_version=rel_version,
        siblings=tuple(ctx.siblings.get(c.attribute, ())),
        excerpt=c.excerpt or "",
        page_text=await _page(ctx, row) if truth is not None else row.doc_text,
        truth_confidence=confidence,
        hybrid=_hybrid(ctx.variant),
        domain=row.domain,
    )
    b = blame_vector(case)
    vector = b.vector or {"source": 1.0}
    return vector, component_keys(case, b) if b.vector else {"source": row.domain}, b.disputed


@dataclass
class Emitted:
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    disputed: list[str] = field(default_factory=list)  # signal ids waiting for the judge

    def add(self, key: str) -> None:
        self.counts[key] += 1


async def _emit(reg: Any, out: Emitted, sig: TruthSignalIn, key: str) -> None:
    sid = await reg.signal(sig)
    if sid is None:
        return
    out.add(key)
    if sig.disputed:
        out.disputed.append(sid)


def _sig(ctx: _Ctx, row: _ClaimRow | None, kind: str, verdict: str, attribute: str, **kw: Any) -> TruthSignalIn:
    c = row.c if row else None
    return TruthSignalIn(
        kind=kind,  # type: ignore[arg-type]
        verdict=verdict,  # type: ignore[arg-type]
        domain=row.domain if row else str(kw.pop("domain", "")),
        area=c.area if c else str(kw.pop("area", "specs")),
        variant_id=ctx.variant.id,
        attribute=attribute,
        claim_id=c.id if c else None,
        snapshot_id=c.snapshot_id if c else None,
        **kw,
    )


async def _gold_signals(ctx: _Ctx, reg: Any, out: Emitted) -> None:
    for row in ctx.claims:
        c = row.c
        g = ctx.gold.get(c.attribute)
        if g is None or g.value_num is None or c.value_num is None or (c.id, "gold") in ctx.done:
            continue
        tol = _tol(c.attribute, g)
        details = {"gold": g.value_num, "value": c.value_num, "rule": g.match_rule}
        if near(c.value_num, g.value_num, tol):
            await _emit(reg, out, _sig(ctx, row, "gold", "right", c.attribute, gold_id=g.id, details=details),
                        "gold_right")  # fmt: skip
        else:
            vec, comps, disputed = await _blame(ctx, row, g.value_num, tol, g.confidence)
            sig = _sig(ctx, row, "gold", "wrong", c.attribute, gold_id=g.id, blame_vector=vec, components=comps,
                       disputed=disputed, details=details)  # fmt: skip
            await _emit(reg, out, sig, "gold_wrong")
        ctx.done.add((c.id, "gold"))
    # fusion: the selected value is wrong although one of the claims behind the attribute was right
    for attr, sv in ctx.selected.items():
        g = ctx.gold.get(attr)
        if g is None or g.value_num is None or sv.value_num is None or not sv.available:
            continue
        tol = _tol(attr, g)
        if near(sv.value_num, g.value_num, tol) or (attr, float(sv.value_num)) in ctx.fused:
            continue
        right = [r for r in ctx.claims if r.c.attribute == attr and r.c.value_num is not None
                 and near(r.c.value_num, g.value_num, tol)]  # fmt: skip
        if right:
            sig = TruthSignalIn(kind="gold", verdict="wrong", domain=right[0].domain, area=right[0].c.area,
                                variant_id=ctx.variant.id, attribute=attr, gold_id=g.id,
                                blame_vector={"fusion": 1.0}, components={"fusion": "merge@1"},
                                details={"selected": float(sv.value_num), "gold": g.value_num})  # fmt: skip
            await _emit(reg, out, sig, "fusion")
            ctx.fused.add((attr, float(sv.value_num)))


async def _physics_signals(ctx: _Ctx, reg: Any, out: Emitted) -> None:
    values = {a: float(sv.value_num) for a, sv in ctx.selected.items() if sv.available and sv.value_num is not None}
    drive = ctx.selected.get("drivetrain")
    by_id = {r.c.id: r for r in ctx.claims}
    fams = {a: len({by_id[i].family for i in (sv.claim_ids or []) if i in by_id}) or 1
            for a, sv in ctx.selected.items()}  # fmt: skip
    drivetrain = ((drive.value_text or "").upper() or None) if drive else None
    facts = physics.Facts(values, ctx.variant.fuel, ctx.variant.powertrain, drivetrain, ctx.variant.body_class, fams)
    o = physics.outlier(facts, physics_config().get("checks") or {})
    if o.attribute is None:
        return
    inc = next(i for i in o.inconsistencies if o.attribute in i.values)
    for cid in ctx.selected[o.attribute].claim_ids or []:
        row = by_id.get(cid)
        if row is None or (cid, "physics") in ctx.done:
            continue
        vec, comps, disputed = await _blame(ctx, row, None, _tol(o.attribute))
        details = {"check": inc.check, "values": inc.values, "about": inc.about, "expected": list(inc.expected),
                   "outlier_rule": o.rule}  # fmt: skip
        sig = _sig(ctx, row, "physics", "wrong", o.attribute, blame_vector=vec, components=comps, disputed=disputed,
                   details=details)  # fmt: skip
        await _emit(reg, out, sig, "physics")
        ctx.done.add((cid, "physics"))


async def _agreement_signals(ctx: _Ctx, reg: Any, out: Emitted) -> None:
    by_attr: dict[str, list[agreement.FamilyValue]] = defaultdict(list)
    for r in ctx.claims:
        if r.c.value_num is not None:
            by_attr[r.c.attribute].append(agreement.FamilyValue(r.c.id, r.domain, r.family, float(r.c.value_num)))
    by_id = {r.c.id: r for r in ctx.claims}
    for attr, vals in by_attr.items():
        for a in agreement.agreements(vals, _tol(attr, ctx.gold.get(attr))):
            if (attr, a.family) in ctx.agreed:
                continue
            sig = _sig(ctx, by_id[a.claim_id], "agreement", "right", attr,
                       details={"family": a.family, "families": a.families, "value": a.value})  # fmt: skip
            await _emit(reg, out, sig, "agreement")
            ctx.agreed.add((attr, a.family))


async def _replacement_signals(ctx: _Ctx, reg: Any, out: Emitted) -> None:
    by_id = {r.c.id: r for r in ctx.claims}
    for attr, sv in ctx.selected.items():
        if not sv.available or sv.value_num is None or (sv.confidence or "").upper() not in ("HIGH", "MEDIUM"):
            continue
        hist = [replacement.Seen(r.c.id, r.domain, float(r.c.value_num), r.c.created_at.timestamp())
                for r in ctx.claims if r.c.attribute == attr and r.c.value_num is not None]  # fmt: skip
        for old in replacement.replaced(hist, sv.claim_ids or [], float(sv.value_num), _tol(attr)):
            if (old.claim_id, "replacement") in ctx.done:
                continue
            row = by_id[old.claim_id]
            vec, comps, disputed = await _blame(ctx, row, float(sv.value_num), _tol(attr), "MEDIUM")
            sig = _sig(ctx, row, "replacement", "wrong", attr, blame_vector=vec, components=comps,
                       disputed=False, details={"replaced_by": float(sv.value_num), "judge": "not needed"})  # fmt: skip
            await _emit(reg, out, sig, "replacement")
            ctx.done.add((old.claim_id, "replacement"))


async def for_variant(variant_id: str, reg: Any = None, cfg: Mapping[str, Any] | None = None) -> Emitted:
    """All four kinds of signals for one variant, each emitted once."""
    cfg = cfg if cfg is not None else load_yaml("registry.yaml")
    reg = reg or _registry(cfg)
    out = Emitted()
    ctx = await _load(variant_id, cfg.get("families") or {})
    if ctx is None:
        return out
    for step in (_gold_signals, _physics_signals, _agreement_signals, _replacement_signals):
        try:
            await step(ctx, reg, out)
        except Exception:  # noqa: BLE001 - one failing kind never stops the others
            log.exception("reputation.%s_failed variant=%s", step.__name__, variant_id)
    return out


async def _enqueue_judges(ids: Iterable[str]) -> int:
    from automind.acquisition.worker import queue  # noqa: PLC0415

    n = 0
    for sid in ids:
        if await queue.enqueue("blame_judge", {"signal_id": sid}, dedupe_key=f"blame:{sid}", priority=7):
            n += 1
    return n


async def recent_variants(since: datetime) -> list[str]:
    """Variants with an accepted claim, a selection or a gold value since `since` (new gold re-checks old claims)."""
    async with sessionmaker()() as s:
        ids: set[str] = set()
        for q in (
            select(Claim.variant_id).where(Claim.created_at >= since, Claim.status == "ACCEPTED"),
            select(SpecValue.variant_id).where(SpecValue.updated_at >= since),
            select(GoldValueRow.variant_id).where(GoldValueRow.verified_at >= since),
        ):
            ids |= set((await s.execute(q.distinct())).scalars())
    return sorted(ids)


async def scan(
    variant_ids: list[str] | None = None, since: datetime | None = None, cfg: Mapping[str, Any] | None = None,
    reg: Any = None, judge: bool = True,
) -> dict[str, int]:  # fmt: skip
    """The `reputation_signals` task: signals for the given variants, or for those touched since `since`."""
    cfg = cfg if cfg is not None else load_yaml("registry.yaml")
    reg = reg or _registry(cfg)
    if variant_ids is None:
        variant_ids = await recent_variants(since or datetime.now(UTC) - timedelta(hours=26))
    total: dict[str, int] = defaultdict(int)
    disputed: list[str] = []
    for vid in variant_ids:
        e = await for_variant(vid, reg, cfg)
        for k, n in e.counts.items():
            total[k] += n
        disputed += e.disputed
    total["variants"] = len(variant_ids)
    total["disputed"] = len(disputed)
    if judge and disputed:
        total["judge_tasks"] = await _enqueue_judges(disputed)
    return dict(total)
