"""The rule auditor (spec 011 US5 T106, research R13): a bounded threshold change for a rule that rejects values
other sources later confirm (the "manuales" kind of mistake, for thresholds).

- cluster (code): claims rejected by a plausibility range whose (variant, attribute) was later accepted from ≥ 2
  independent families at a close value (±5 %), grouped by (rule, attribute); clusters of ≥ `min_cluster` values
  name one lever path (`plausibility.by_powertrain.<attribute>.<powertrain>.<min|max>`);
- propose (role `rule_auditor`, a web reader with no tools; excerpts only inside <untrusted_document>): a value and
  a one-sentence explanation;
- code clamps the value to `max_step_rel` of the current one in the direction the cluster needs, checks it with the
  levers (whitelisted paths, bounds) and journals it; the gates decide.
Relevance rejections (the "manuales" kind of mistake itself): pages a relevance rule rejected for a variant whose
values ≥ 2 other families later confirmed, at values the rejected page writes itself (its stored snapshot), clustered
by (rule, trigger word); a cluster whose rule has a stop list (`relevance.keywords.not_manual|not_auto|not_awd`) asks
the role for ONE stop phrase, and code checks it (contains the trigger word, 2–4 words, occurs on the cluster's pages)
before the levers and the gates (`gates/relevance_replay.py` re-runs the relevance stage on stored pages).
Budget: `agents.budgets.rule_auditor` and `max_runs_per_day`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field

from automind.acquisition.agents import budget as budgets
from automind.acquisition.agents.levers import RuleProposal, rule_value
from automind.acquisition.domain import relevance_audit as ra

log = logging.getLogger(__name__)
AGENT = ROLE = "rule_auditor"
PROMPT = Path(__file__).resolve().parents[2] / "orchestration" / "prompts" / "rule_auditor.md"
EST_EUR = 0.001
MIN_CLUSTER = 3
MIN_FAMILIES = 2
CLOSE_REL = 0.05
LOOKBACK_DAYS = 30
T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T: ...


class GatewayLLM:
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        from automind.infrastructure import llm_gateway  # noqa: PLC0415

        return await llm_gateway.structured(role, schema, system, user)


LLM_OVERRIDE: LLM | None = None


class AuditOut(BaseModel):
    path: str = Field(max_length=160)
    value: float | list[str]
    explanation: str = Field(default="", max_length=300)


@dataclass(frozen=True)
class Rejected:
    """A rejected value confirmed later by `families` independent families."""

    rule: str  # claims.reject_rule, e.g. "consumption.BEV"
    attribute: str
    value: float
    families: int
    excerpt: str = ""
    domain: str = ""


@dataclass
class Cluster:
    path: str
    side: str  # min | max
    current: float
    values: list[float] = field(default_factory=list)
    examples: list[Rejected] = field(default_factory=list)

    @property
    def needed(self) -> float:
        """The threshold that would accept every confirmed value."""
        return max(self.values) if self.side == "max" else min(self.values)


# --- pure ---------------------------------------------------------------------------------------------------------


def lever_path(r: Rejected, rules: Mapping[str, Any]) -> tuple[str, str, float] | None:
    """(path, side, current) of the plausibility range that rejected the value, or None (another kind of rule)."""
    attribute, _, pt = r.rule.partition(".")
    if attribute != r.attribute or not pt:
        return None
    rng = rule_value(rules, f"plausibility.by_powertrain.{attribute}.{pt}")
    if not (isinstance(rng, list | tuple) and len(rng) == 2):
        return None
    lo, hi = float(rng[0]), float(rng[1])
    if r.value > hi:
        return f"plausibility.by_powertrain.{attribute}.{pt}.max", "max", hi
    if r.value < lo:
        return f"plausibility.by_powertrain.{attribute}.{pt}.min", "min", lo
    return None


def clusters(rows: list[Rejected], rules: Mapping[str, Any], min_cluster: int = MIN_CLUSTER) -> list[Cluster]:
    """Clusters of confirmed rejections per lever path, largest first."""
    by: dict[str, Cluster] = {}
    for r in rows:
        if r.families < MIN_FAMILIES:
            continue
        got = lever_path(r, rules)
        if got is None:
            continue
        path, side, current = got
        c = by.setdefault(path, Cluster(path, side, current))
        c.values.append(r.value)
        if len(c.examples) < 5:
            c.examples.append(r)
    return sorted((c for c in by.values() if len(c.values) >= min_cluster), key=lambda c: -len(c.values))


def clamp(c: Cluster, proposed: float, max_step_rel: float) -> float | None:
    """The proposed threshold moved in the direction the cluster needs, at most `max_step_rel` of the current value
    and no further than needed; None when it does not move that way."""
    cur = c.current
    if c.side == "max":
        top = cur * (1 + max_step_rel)
        v = min(max(proposed, cur), top, max(c.needed, cur))
        return round(v, 3) if v > cur else None
    low = cur * (1 - max_step_rel)
    v = max(min(proposed, cur), low, min(c.needed, cur))
    return round(v, 3) if v < cur else None


def user_message(c: Cluster, max_step_rel: float) -> str:
    docs = "\n".join(f'<untrusted_document url="{e.domain}">\n{e.excerpt[:300]}\n</untrusted_document>'
                     for e in c.examples)  # fmt: skip
    return (f"Rule path: {c.path}\nCurrent value: {c.current:g}\nSide: {c.side}\n"
            f"Largest change in one step: {max_step_rel:.0%} of the current value\n"
            f"Rejected values later confirmed by at least {MIN_FAMILIES} independent sources: "
            f"{', '.join(f'{v:g}' for v in sorted(c.values))}\n\nExcerpts:\n{docs}")  # fmt: skip


# --- database and the task ----------------------------------------------------------------------------------------


_CONFIRMED = """
SELECT r.reject_rule, r.attribute, r.value_num, r.excerpt, e.domain,
       count(DISTINCT coalesce(src.family, e2.domain)) AS families
FROM claims r
JOIN evidence e ON e.id = r.evidence_id
JOIN claims a ON a.variant_id = r.variant_id AND a.attribute = r.attribute AND a.status = 'ACCEPTED'
             AND a.created_at > r.created_at AND a.value_num IS NOT NULL
             AND abs(a.value_num - r.value_num) <= :rel * abs(r.value_num)
JOIN evidence e2 ON e2.id = a.evidence_id AND e2.domain <> e.domain
LEFT JOIN sources src ON src.domain = e2.domain
WHERE r.status = 'REJECTED_IMPLAUSIBLE' AND r.reject_rule IS NOT NULL AND r.value_num IS NOT NULL
  AND r.created_at >= :since
GROUP BY r.id, r.reject_rule, r.attribute, r.value_num, r.excerpt, e.domain
"""


async def confirmed_rejections(since: datetime) -> list[Rejected]:
    from sqlalchemy import text  # noqa: PLC0415

    from automind.infrastructure.db import sessionmaker  # noqa: PLC0415

    async with sessionmaker()() as s:
        rows = (await s.execute(text(_CONFIRMED), {"since": since, "rel": CLOSE_REL})).all()
    return [Rejected(str(rule), str(a), float(v), int(f), str(x or ""), str(d)) for rule, a, v, x, d, f in rows]


def _cfg() -> dict[str, Any]:
    from automind.infrastructure.config import agents_config  # noqa: PLC0415

    return dict((agents_config().get("levers") or {}).get("rule_auditor") or {})


async def run_auditor(*, llm: LLM | None = None, charge: Any = None, now: datetime | None = None) -> dict[str, Any]:
    from automind.acquisition.gates import journal  # noqa: PLC0415
    from automind.acquisition.worker.budget import BudgetExceeded  # noqa: PLC0415
    from automind.infrastructure.config import effective_rules  # noqa: PLC0415

    now = now or datetime.now(UTC)
    cfg = _cfg()
    step = float(cfg.get("max_step_rel", 0.2))
    rules = effective_rules()
    found = clusters(await confirmed_rejections(now - timedelta(days=LOOKBACK_DAYS)), rules,
                     int(cfg.get("min_cluster", MIN_CLUSTER)))  # fmt: skip
    out: dict[str, Any] = {"clusters": [{"path": c.path, "values": len(c.values)} for c in found], "proposed": []}
    model = llm or LLM_OVERRIDE or GatewayLLM()
    for c in found:
        try:
            if charge is not None:
                await charge(EST_EUR)
            ans = await model.structured(ROLE, AuditOut, PROMPT.read_text(encoding="utf-8"), user_message(c, step))
        except BudgetExceeded:
            out["stop"] = "budget"
            break
        except Exception as e:  # noqa: BLE001 - a failed call skips this cluster
            log.warning("rule_auditor.call_failed path=%s: %s", c.path, e)
            continue
        if ans.path != c.path or isinstance(ans.value, list):
            out["proposed"].append({"path": c.path, "refused": f"answered {ans.path!r}, not the cluster's path"})
            continue
        value = clamp(c, float(ans.value), step)
        if value is None:
            out["proposed"].append({"path": c.path, "refused": "no change in the needed direction"})
            continue
        trigger = (f"{len(c.values)} rejected {c.path.split('.')[2]} values confirmed by ≥ {MIN_FAMILIES} families "
                   f"(up to {c.needed:g} vs {c.side} {c.current:g})")  # fmt: skip
        evidence = {"trigger": trigger, "values": sorted(c.values), "explanation": ans.explanation[:300],
                    "examples": [e.__dict__ for e in c.examples]}  # fmt: skip
        cid = await journal.propose(AGENT, RuleProposal(path=c.path, value=value), "rule cluster", evidence)
        out["proposed"].append({"path": c.path, "value": value, "change_id": cid})
    if out.get("stop") != "budget":
        listed, proposed, stopped = await audit_relevance(model, charge, cfg, rules, now)
        out["relevance_clusters"] = listed
        out["proposed"] += proposed
        if stopped:
            out["stop"] = "budget"
    return out


# --- relevance rejections later contradicted (the "manuales" kind of mistake, for relevance keywords) -----------

_CLAIMS_AFTER = """
SELECT c.variant_id, c.value_num, c.attribute, e.domain, coalesce(src.family, e.domain), c.created_at
FROM claims c JOIN evidence e ON e.id = c.evidence_id LEFT JOIN sources src ON src.domain = e.domain
WHERE c.variant_id = ANY(:vids) AND c.status = 'ACCEPTED' AND c.value_num IS NOT NULL
"""


async def contradicted_rejections(since: datetime, until: datetime, *, min_families: int = MIN_FAMILIES,
                                  min_values: int = 2, min_share: float = 0.75,
                                  limit: int = 2000) -> list[ra.RejectedPage]:  # fmt: skip
    """Pages a relevance rule rejected (method RULES) for a variant whose values ≥ `min_families` other families
    accepted afterwards, at values the rejected page writes itself (its stored snapshot): ≥ `min_values` of them and
    ≥ `min_share` of the confirmed attributes (a page of another variant shares a value or two by chance)."""
    from sqlalchemy import text  # noqa: PLC0415

    from automind.acquisition.gates import relevance_replay as rr  # noqa: PLC0415
    from automind.infrastructure.db import sessionmaker  # noqa: PLC0415

    items = await rr.judged(since, until, rejected_only=True, limit=limit)
    if not items:
        return []
    async with sessionmaker()() as s:
        rows = (await s.execute(text(_CLAIMS_AFTER), {"vids": sorted({j.variant_id for j in items})})).all()
    later: dict[str, list[tuple[float, str, str, str, datetime]]] = defaultdict(list)
    for vid, x, attr, dom, fam, at in rows:
        later[str(vid)].append((float(x), str(attr), str(dom), str(fam), at))
    texts, _ = await rr.pages_text([j.ref for j in items])
    out = []
    for j in items:
        got = texts.get(j.ref.id)
        if got is None:
            continue
        rows_after = [(x, attr, fam) for x, attr, dom, fam, at in later.get(j.variant_id, [])
                      if dom != j.ref.domain and (j.judged_at is None or at > j.judged_at)]  # fmt: skip
        confirmed, agreed = _confirmed_on_page(j.variant_id, rows_after, ra.numbers(f"{got[0]}\n{got[1]}"),
                                               min_families)  # fmt: skip
        if len(confirmed) >= min_values and len(confirmed) >= min_share * agreed - 1e-9:
            out.append(ra.RejectedPage(j.ref.id, j.variant_id, j.ref.final_url or j.ref.url, got[0] or j.title,
                                       j.verdict, j.reason, tuple(confirmed)))  # fmt: skip
    return out


def _confirmed_on_page(variant_id: str, rows: list[tuple[float, str, str]], nums: set[float],
                       min_families: int) -> tuple[list[str], int]:  # fmt: skip
    """(attributes whose agreed value the page writes, attributes with an agreed value)."""
    from automind.acquisition.gates import relevance_replay as rr  # noqa: PLC0415

    by_attr: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for x, attr, fam in rows:
        by_attr[attr].append((x, fam))
    confirmed, agreed = [], 0
    for attr, vals in sorted(by_attr.items()):
        g = rr.agreement(variant_id, attr, vals, ("rel", CLOSE_REL), min_families)
        if g is None or g.num is None:
            continue
        agreed += 1
        if ra.contains_value(nums, g.num):
            confirmed.append(attr)
    return confirmed, agreed


def relevance_message(c: ra.RelevanceCluster, current: list[str], min_pages: int) -> str:
    contexts = ", ".join(f'"{k}" ×{n}' for k, n in sorted(c.contexts.items(), key=lambda kv: -kv[1])[:8])
    docs = "\n".join(f'<untrusted_document url="{p.url[:200]}">\n{p.title[:200]}\n</untrusted_document>'
                     for p in c.pages[:5])  # fmt: skip
    return (f"Rule path: {c.path}\nCurrent value: {current}\n"
            f"Kind: a list of stop phrases — phrases removed from a page's title and address before the relevance "
            f"rule looks for the word \"{c.word}\"\n"
            f"Rejection: \"{c.reason}\" on {len(c.pages)} pages whose values at least {MIN_FAMILIES} independent "
            f"sources later confirmed (the pages write the same values)\n"
            f"Trigger word: {c.word}\nHow the word appears on those pages: {contexts}\n"
            f"Answer with the current list plus ONE phrase of 2 to {ra.MAX_PHRASE_WORDS} words that contains the "
            f"trigger word and occurs on at least {min_pages} of these pages; never the bare word.\n\n"
            f"Titles and addresses:\n{docs}")  # fmt: skip


async def audit_relevance(model: LLM, charge: Any, cfg: Mapping[str, Any], rules: Mapping[str, Any],
                          now: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:  # fmt: skip
    """(clusters, proposals, stopped on budget) of relevance rejections later contradicted."""
    from automind.acquisition.gates import journal  # noqa: PLC0415
    from automind.acquisition.worker.budget import BudgetExceeded  # noqa: PLC0415

    rcfg = dict(cfg.get("relevance") or {})
    min_cluster = int(rcfg.get("min_cluster", MIN_CLUSTER))
    pages = await contradicted_rejections(now - timedelta(days=LOOKBACK_DAYS), now,
                                          min_families=int(rcfg.get("min_families", MIN_FAMILIES)),
                                          min_values=int(rcfg.get("min_values", 2)),
                                          min_share=float(rcfg.get("min_share", 0.75)))  # fmt: skip
    found = ra.relevance_clusters(pages, min_cluster)
    listed = [{"rule": c.rule, "word": c.word, "pages": len(c.pages), "path": c.path or "no lever"} for c in found]
    proposed: list[dict[str, Any]] = []
    for c in found:
        if c.path is None or not c.word:
            continue
        current = [str(w) for w in (rule_value(rules, c.path) or [])]
        try:
            if charge is not None:
                await charge(EST_EUR)
            ans = await model.structured(ROLE, AuditOut, PROMPT.read_text(encoding="utf-8"),
                                         relevance_message(c, current, min_cluster))  # fmt: skip
        except BudgetExceeded:
            return listed, proposed, True
        except Exception as e:  # noqa: BLE001 - a failed call skips this cluster
            log.warning("rule_auditor.call_failed path=%s: %s", c.path, e)
            continue
        if ans.path != c.path or not isinstance(ans.value, list):
            proposed.append({"path": c.path, "refused": f"answered {ans.path!r}, not the cluster's keyword list"})
            continue
        have = {" ".join(w.lower().split()) for w in current}
        added = [" ".join(str(w).lower().split()) for w in ans.value if " ".join(str(w).lower().split()) not in have]
        if len(added) != 1 or not have <= {" ".join(str(w).lower().split()) for w in ans.value}:
            proposed.append({"path": c.path, "refused": "the answer must keep the list and add exactly one phrase"})
            continue
        if why := ra.stop_phrase_problem(added[0], c.word, [p.text for p in c.pages], current, min_cluster):
            proposed.append({"path": c.path, "refused": why})
            continue
        trigger = (f"{len(c.pages)} pages rejected as \"{c.reason}\" on \"{c.word}\" whose values ≥ {MIN_FAMILIES} "
                   f"families later confirmed")  # fmt: skip
        evidence = {"trigger": trigger, "rule": c.rule, "word": c.word, "phrase": added[0],
                    "variants": c.variants, "pages": [p.snapshot_id for p in c.pages], "contexts": c.contexts,
                    "explanation": ans.explanation[:300], "as_of": now.isoformat(),
                    "examples": [{"url": p.url, "title": p.title[:200], "reason": p.reason,
                                  "confirmed": list(p.confirmed)} for p in c.pages[:5]]}  # fmt: skip
        cid = await journal.propose(AGENT, RuleProposal(path=c.path, value=[*current, added[0]]),
                                    "relevance cluster", evidence)  # fmt: skip
        proposed.append({"path": c.path, "value": [*current, added[0]], "change_id": cid})
    return listed, proposed, False


async def handle(payload: dict[str, Any], *, guard: Any = None, llm: LLM | None = None) -> dict[str, Any]:
    if why := await budgets.stop_reason(AGENT):
        return {"skipped": why}
    return await run_auditor(llm=llm, charge=guard.charge if guard is not None else None)


def by_rule(rows: list[Rejected]) -> dict[str, int]:
    """How many confirmed rejections each rule has (diagnostics)."""
    n: dict[str, int] = defaultdict(int)
    for r in rows:
        n[r.rule] += 1
    return dict(n)
