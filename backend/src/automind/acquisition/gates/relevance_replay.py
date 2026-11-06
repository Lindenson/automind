"""The offline measure of a relevance keyword change (spec 011 US5 gap "manuales"; research R14): the relevance stage
re-run with the old and the candidate keywords over the stored pages of the last `gates.relevance.window_days` days
whose title or address names the changed words.

A page counts when the rules give again the verdict stored in `page_relevance` (method RULES) with the old keywords;
its values are read the live way — the running reader of its site, offline, through the live sense and plausibility
checks, else the extractor through `extraction_cache` within the agent's budget — and checked against gold, else the
agreement of ≥ 2 other families (`claims`). `domain/relevance_audit` turns the pages into the measure (pages flipped to
relevant, precision of their values, junk acceptance of correct rejections) and decides.
"""

from __future__ import annotations

import statistics
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

from automind.acquisition.domain import gates
from automind.acquisition.domain import relevance_audit as ra
from automind.acquisition.domain import replay as scoring
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.snapshots.store import SnapshotRef
from automind.shared.infrastructure.config import loader as config
from automind.shared.infrastructure.db import AcqChange, Variant, sessionmaker

PREFIX = "relevance.keywords."
Charge = Callable[[float], Awaitable[None]]
DEFAULT_TOL: scoring.Tolerance = ("rel", 0.03)


def applies(c: AcqChange) -> bool:
    return c.object_kind == "rule" and c.object_key.startswith(PREFIX)


def gate_cfg() -> ra.RelevanceGateConfig:
    return ra.RelevanceGateConfig.from_mapping(acq_config.agents_config())


@dataclass(frozen=True)
class Judged:
    """A stored relevance verdict and the page it was given on."""

    ref: SnapshotRef
    variant_id: str
    verdict: str
    reason: str
    judged_at: datetime | None = None
    title: str = ""


_JUDGED = """
SELECT pr.variant_id, pr.verdict, pr.reason, pr.created_at, d.title,
       ps.id, ps.url, ps.final_url, ps.domain, ps.fetched_at, ps.content_type, ps.blob_sha256
FROM page_relevance pr
JOIN documents d ON d.id = pr.document_id
JOIN LATERAL (SELECT * FROM page_snapshots s WHERE s.document_id = pr.document_id AND s.replayable
              AND s.blob_sha256 IS NOT NULL ORDER BY s.fetched_at DESC LIMIT 1) ps ON true
WHERE pr.method = 'RULES' AND (pr.created_at >= :since OR ps.fetched_at >= :since) AND pr.created_at <= :until
  {verdicts} {words}
ORDER BY pr.created_at DESC
LIMIT :limit
"""


async def judged(since: datetime, until: datetime, *, words: Sequence[str] = (), rejected_only: bool = False,
                 limit: int = 400) -> list[Judged]:  # fmt: skip
    """Pages judged by the relevance rules in the period (newest first); only those whose title or address names one
    of `words` when given (a keyword change can only move those)."""
    params: dict[str, Any] = {"since": since, "until": until, "limit": limit}
    verdicts = "AND pr.verdict IN ('OTHER_VARIANT', 'NOT_ABOUT_CAR')" if rejected_only else ""
    cond = ""
    if words:
        params["pats"] = [f"%{w.split()[0]}%" for w in words if w.strip()]
        cond = ("AND (coalesce(d.title, '') ILIKE ANY(:pats) OR d.url ILIKE ANY(:pats) "
                "OR coalesce(ps.final_url, ps.url) ILIKE ANY(:pats))")  # fmt: skip
    async with sessionmaker()() as s:
        rows = (await s.execute(text(_JUDGED.format(verdicts=verdicts, words=cond)), params)).all()
    return [Judged(SnapshotRef(str(i), str(u), fu, str(dom), at, ct, (str(vid),), str(sha)), str(vid), str(v),
                   str(r or ""), jat, str(t or ""))
            for vid, v, r, jat, t, i, u, fu, dom, at, ct, sha in rows]  # fmt: skip


async def pages_text(refs: Sequence[SnapshotRef]) -> tuple[dict[str, tuple[str, str]], dict[str, bytes]]:
    """snapshot id → (title, main text) of the stored bodies, and the bodies by sha."""
    from automind.acquisition.infrastructure.fetch import decode_body  # noqa: PLC0415
    from automind.acquisition.infrastructure.pages import main_content  # noqa: PLC0415
    from automind.acquisition.snapshots import store  # noqa: PLC0415

    bodies = await store.load_bodies(sorted({r.blob_sha256 for r in refs}))
    out = {}
    for r in refs:
        if r.blob_sha256 in bodies:
            out[r.id] = main_content(decode_body(bodies[r.blob_sha256], None), r.final_url or r.url)
    return out, bodies


async def variants(ids: set[str]) -> dict[str, Variant]:
    from automind.acquisition.replay import run  # noqa: PLC0415

    have: dict[str, Variant] = {}
    await run._variants(ids, have)
    return have


# --- references: gold, else agreement ---------------------------------------------------------------------------

_AGREED = """
SELECT c.variant_id, c.attribute, c.value_num, e.domain, coalesce(src.family, e.domain)
FROM claims c JOIN evidence e ON e.id = c.evidence_id LEFT JOIN sources src ON src.domain = e.domain
WHERE c.variant_id = ANY(:vids) AND c.status = 'ACCEPTED' AND c.value_num IS NOT NULL
"""


@dataclass
class References:
    gold: dict[tuple[str, str], scoring.Gold]
    claims: dict[tuple[str, str], list[tuple[float, str, str]]]  # (value, domain, family)
    tolerances: dict[str, scoring.Tolerance]
    min_families: int = 2

    def of(self, variant_id: str, attribute: str, domain: str) -> scoring.Gold | None:
        g = self.gold.get((variant_id, attribute))
        if g is not None:
            return g
        rows = [(x, f) for x, d, f in self.claims.get((variant_id, attribute), []) if d != domain]
        return agreement(variant_id, attribute, rows, self.tolerances.get(attribute, DEFAULT_TOL), self.min_families)

    def check(self, values: Sequence[scoring.Value], domain: str) -> tuple[int, int]:
        """(right, wrong) of the values that have a reference."""
        right = wrong = 0
        for v in values:
            g = self.of(v.variant_id, v.attribute, domain)
            if g is None:
                continue
            if scoring.agrees(v, g, self.tolerances):
                right += 1
            else:
                wrong += 1
        return right, wrong


def agreement(variant_id: str, attribute: str, rows: Sequence[tuple[float, str]], tol: scoring.Tolerance,
              min_families: int = 2) -> scoring.Gold | None:  # fmt: skip
    """The value ≥ `min_families` independent families agree on (within the attribute's tolerance), as a gold."""
    kind, t = tol
    best: tuple[int, float] | None = None
    for x, _ in rows:
        near = [(y, f) for y, f in rows if abs(y - x) <= (t if kind == "abs" else t * abs(x)) + 1e-9]
        fams = len({f for _, f in near})
        if fams >= min_families and (best is None or fams > best[0]):
            best = (fams, statistics.median(y for y, _ in near))
    if best is None:
        return None
    return scoring.Gold(variant_id, attribute, best[1], None, "", t, kind, "agreement", None)


async def references(variant_ids: set[str]) -> References:
    from automind.acquisition.replay import run  # noqa: PLC0415

    gold = await run._gold(variant_ids)
    claims: dict[tuple[str, str], list[tuple[float, str, str]]] = {}
    if variant_ids:
        async with sessionmaker()() as s:
            for vid, attr, x, dom, fam in (await s.execute(text(_AGREED), {"vids": sorted(variant_ids)})).all():
                claims.setdefault((str(vid), str(attr)), []).append((float(x), str(dom), str(fam)))
    return References(gold, claims, acq_config.gold_tolerances())


# --- re-judging and reading -------------------------------------------------------------------------------------


@contextmanager
def keywords(lists: Mapping[str, Sequence[str]]) -> Iterator[None]:
    """The relevance rules with these keyword lists for the block (synchronous: no other task runs meanwhile)."""
    from automind.acquisition.domain import relevance  # noqa: PLC0415

    saved = {k: list(v) for k, v in relevance.KEYWORDS.items()}
    relevance.configure_keywords(dict(lists))
    try:
        yield
    finally:
        relevance.configure_keywords(saved)


def keyword_sets(c: AcqChange) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(keyword lists before, after) of a relevance keyword change."""
    from automind.acquisition.domain import relevance  # noqa: PLC0415

    name = c.object_key.removeprefix(PREFIX)
    current = {k: list(v) for k, v in relevance.KEYWORDS.items()}
    before = dict(current)
    if c.status in ("watch", "kept"):  # the change is live: "before" is its old value
        before[name] = list((c.diff or {}).get("from") or [])
    after = {**current, name: [str(w) for w in ((c.diff or {}).get("to") or [])]}
    return before, after


def changed_words(c: AcqChange) -> list[str]:
    d = c.diff or {}
    old = {str(w).lower() for w in d.get("from") or []}
    new = {str(w).lower() for w in d.get("to") or []}
    return sorted(old ^ new)


def rejudge(items: Sequence[Judged], texts: Mapping[str, tuple[str, str]], vs: Mapping[str, Variant],
            before: Mapping[str, Sequence[str]], after: Mapping[str, Sequence[str]]
            ) -> tuple[list[tuple[Judged, str, str]], int]:  # fmt: skip
    """[(page, old verdict, new verdict)] of the pages whose stored verdict the old keywords reproduce, and how many
    did not reproduce."""
    from automind.acquisition.domain import relevance as rel  # noqa: PLC0415
    from automind.acquisition.pipeline.relevance import relevance_target  # noqa: PLC0415

    gens = config.generations()
    out: list[tuple[Judged, str, str]] = []
    unreproduced = 0
    for j in items:
        v, got = vs.get(j.variant_id), texts.get(j.ref.id)
        if v is None or got is None:
            continue
        tgt, generations = relevance_target(v, gens)
        facts = rel.PageFacts(j.ref.final_url or j.ref.url, got[0], got[1])
        with keywords(before):
            old = rel.judge(facts, tgt, generations).verdict
        with keywords(after):
            new = rel.judge(facts, tgt, generations).verdict
        if old != j.verdict:
            unreproduced += 1
            continue
        out.append((j, old, new))
    return out, unreproduced


ValuesByPage = dict[tuple[str, str], list[scoring.Value]]


async def read_values(items: Sequence[Judged], bodies: Mapping[str, bytes], vs: Mapping[str, Variant], *,
                      llm: Any = None, charge: Charge | None = None) -> ValuesByPage:  # fmt: skip
    """(snapshot, variant) → the values the live path would accept from the page for the variant."""
    from automind.acquisition.gates import evaluate  # noqa: PLC0415
    from automind.acquisition.replay.offline import no_network  # noqa: PLC0415
    from automind.acquisition.replay.run import read_page  # noqa: PLC0415

    specs = await evaluate._running_specs()
    rules = config.plausibility_rules()
    out: ValuesByPage = {}
    for j in items:
        raw = bodies.get(j.ref.blob_sha256)
        if raw is None:
            continue
        ref = SnapshotRef(j.ref.id, j.ref.url, j.ref.final_url, j.ref.domain, j.ref.fetched_at, j.ref.content_type,
                          (j.variant_id,), j.ref.blob_sha256)  # fmt: skip
        sp = evaluate._spec_for(specs, ref.domain)
        if sp is not None:
            with no_network():
                got = read_page(ref, raw, sp, dict(vs), rules)
            if got.values or got.rows_read:
                out[(ref.id, j.variant_id)] = list(got.values)
                continue
        if charge is not None or llm is not None:
            out[(ref.id, j.variant_id)] = await _extracted(ref, raw, vs, rules, llm=llm, charge=charge)
    return out


async def _extracted(ref: SnapshotRef, raw: bytes, vs: Mapping[str, Variant], rules: dict[str, Any], *, llm: Any,
                     charge: Charge | None) -> list[scoring.Value]:  # fmt: skip
    """The specs extractor on a page without a reader (cached; one call within the agent's budget)."""
    from automind.acquisition.gates import evaluate  # noqa: PLC0415
    from automind.acquisition.infrastructure import overrides  # noqa: PLC0415
    from automind.acquisition.infrastructure.fetch import decode_body  # noqa: PLC0415
    from automind.acquisition.infrastructure.pages import main_content  # noqa: PLC0415
    from automind.acquisition.pipeline import job as pipeline_job  # noqa: PLC0415
    from automind.acquisition.replay import run  # noqa: PLC0415
    from automind.shared.contracts.web import WebDoc  # noqa: PLC0415
    from automind.shared.infrastructure.llm import gateway as llm_gateway

    name = "extract_specs"
    path = run.PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        return []
    prompt = overrides.prompt_text(name, path.read_text(encoding="utf-8").strip())
    url = ref.final_url or ref.url
    title, body = main_content(decode_body(raw, None), url)
    d = WebDoc(url, title, body, False, snapshot_id=ref.id)
    v = vs.get(ref.variant_ids[0])
    target = pipeline_job.target_of(v) if v is not None else "the vehicle on this page"
    if charge is not None:
        await charge(evaluate.EST_EXTRACT_EUR)
    got = await run._extract_cached(d, ref.blob_sha256, name, prompt, "specs", llm_gateway.model_name("extractor"),
                                    target, llm=llm)  # fmt: skip
    return run._values(ref, list(getattr(got, "claims", [])), dict(vs), d, rules, False)


# --- the measure --------------------------------------------------------------------------------------------------


@dataclass
class Result:
    measure: ra.RelevanceMeasure
    old: gates.Metrics
    new: gates.Metrics
    snapshot_ids: list[str]


async def measure(c: AcqChange, since: datetime, until: datetime, *, limit: int, llm: Any = None,
                  charge: Charge | None = None) -> Result:  # fmt: skip
    """Re-judge the pages of the period with the old and the candidate keywords and check the moved pages' values."""
    before, after = keyword_sets(c)
    items = await judged(since, until, words=changed_words(c), limit=limit)
    texts, bodies = await pages_text([j.ref for j in items])
    vs = await variants({j.variant_id for j in items})
    pairs, unreproduced = rejudge(items, texts, vs, before, after)
    # values only where the measure needs them: pages rejected before (correct rejections, flips) and pages the
    # change would newly reject
    need = [j for j, old, new in pairs if old in ra.REJECTED or new in ra.REJECTED]
    values = await read_values(need, bodies, vs, llm=llm, charge=charge)
    refs = await references({j.variant_id for j in need})
    checks: list[ra.PageCheck] = []
    old_vals: list[scoring.Value] = []
    new_vals: list[scoring.Value] = []
    for j, old, new in pairs:
        vals = values.get((j.ref.id, j.variant_id), [])
        right, wrong = refs.check(vals, j.ref.domain)
        chk = ra.PageCheck(j.ref.id, j.variant_id, old, new, right, wrong, len(vals))
        checks.append(chk)
        if chk.flipped:
            new_vals += vals
        elif chk.lost:
            old_vals += vals
    m = ra.RelevanceMeasure.from_pages(checks, unreproduced)
    lost = [c for c in checks if c.lost]
    n = len(checks)
    old_m = gates.Metrics(pages=n, yield_=len(old_vals) / n if n else 0.0,
                          gold_covered=sum(x.right + x.wrong for x in lost), gold_match=sum(x.right for x in lost),
                          accuracy_lb=scoring.wilson_lb(sum(x.right for x in lost),
                                                        sum(x.right + x.wrong for x in lost)))  # fmt: skip
    new_m = gates.Metrics(pages=n, yield_=len(new_vals) / n if n else 0.0, gold_covered=m.values_checked,
                          gold_match=m.values_right, accuracy_lb=m.precision_lb)  # fmt: skip
    return Result(m, old_m, new_m, sorted({j.ref.id for j, _, _ in pairs}))
