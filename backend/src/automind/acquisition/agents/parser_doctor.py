"""The parser doctor (spec 011 US5 T105, research R13): a new declarative parser spec version for a drifted parser, or
a first one for an active spec site without a parser. Its output is a `ParserSpec` only — data checked by the spec
checker and the levers, never code (FR-020); the gates decide its fate.

LangGraph: `collect` → `draft` → `validate` → `self_replay` ↺ (≤ 3 drafts) → `propose`.
- collect (code): the current spec, up to 3 stored pages in the new layout (after the drift's change day), their
  markup skeleton (tags, classes, text cut short), the label texts found, the reference (gold) values of their cars;
- draft (role `parser_doctor`, a web reader with no tools): the pages only inside <untrusted_document>; the answer is
  validated against the closed ParserSpec schema;
- validate (code): reader and domains are the current ones whatever the draft says (page text cannot redirect the
  reader), then `ParserSpec.check` and the lever rules;
- self_replay (code): the draft on the sample pages — rows read and agreement with gold; problems go back to the next
  draft;
- propose (code): the best valid draft that reads the pages enters the journal (`gates/journal.propose`).
Budget: `agents.budgets.parser_doctor` per day (each draft is charged before the call) and `max_runs_per_day`.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol, TypedDict, TypeVar

from pydantic import BaseModel, ValidationError

from automind.acquisition.agents import budget as budgets
from automind.acquisition.agents.levers import ParserProposal
from automind.acquisition.parsing.spec import ParserSpec, norm_label

log = logging.getLogger(__name__)
AGENT = ROLE = "parser_doctor"
PROMPT = Path(__file__).resolve().parents[2] / "chat" / "dialog" / "prompts" / "parser_doctor.md"
EST_EUR = 0.005  # one draft: ~4,000 input + 1,000 output tokens of a flash model
MAX_DRAFTS = 3
SAMPLE_PAGES = 3
SKELETON_CHARS = 4000
TEXT_CHARS = 40
LOOKBACK_DAYS = 7
T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T: ...


class GatewayLLM:
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        from automind.shared.infrastructure.llm import gateway as llm_gateway  # noqa: PLC0415

        return await llm_gateway.structured(role, schema, system, user)


LLM_OVERRIDE: LLM | None = None  # tests install a fake model here (the worker builds the gateway one)


# --- pure helpers: the context the model sees ---------------------------------------------------------------------


_SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "iframe", "template"}
_LABEL_TAGS = ("dt", "th", "label")
_HASHY = re.compile(r"[0-9a-f]{6,}|\d+")


def skeleton(html: str, limit: int = SKELETON_CHARS) -> str:
    """One line per element with text: `tag.class1.class2: text…` (digits/hashes dropped from classes), cut at
    `limit` characters."""
    from selectolax.lexbor import LexborHTMLParser  # noqa: PLC0415

    tree = LexborHTMLParser(html)
    body = tree.body
    if body is None:
        return ""
    lines: list[str] = []
    size = 0
    for node in body.traverse(include_text=False):
        if node.tag in _SKIP_TAGS or node.tag.startswith("-"):
            continue
        own = " ".join((node.text(deep=False) or "").split())
        if not own:
            continue
        classes = [c for c in (node.attributes.get("class") or "").split() if not _HASHY.search(c)]
        line = node.tag + "".join(f".{c}" for c in classes[:3]) + ": " + own[:TEXT_CHARS]
        if size + len(line) + 1 > limit:
            lines.append("…")
            break
        lines.append(line)
        size += len(line) + 1
    return "\n".join(lines)


def labels(html: str, limit: int = 80) -> list[str]:
    """Texts in label positions: dt, th, label, the first cell of a row, elements whose class says label/title."""
    from selectolax.lexbor import LexborHTMLParser  # noqa: PLC0415

    tree = LexborHTMLParser(html)
    out: list[str] = []
    seen: set[str] = set()
    nodes = [*tree.css(",".join(_LABEL_TAGS)), *tree.css("tr > td:first-child"), *tree.css("[class*=label]"),
             *tree.css("[class*=title]")]  # fmt: skip
    for n in nodes:
        t = " ".join((n.text() or "").split())
        k = norm_label(t)
        if 1 < len(t) <= 60 and k not in seen:
            seen.add(k)
            out.append(t)
        if len(out) >= limit:
            break
    return out


@dataclass
class Sample:
    snapshot_id: str
    url: str
    html: str
    variant_ids: tuple[str, ...]
    gold: dict[str, str] = field(default_factory=dict)  # attribute -> "140 kW"


def user_message(current: ParserSpec | None, reader: str, domains: list[str], samples: list[Sample],
                 found: list[str], feedback: list[str]) -> str:  # fmt: skip
    cur = current.model_dump_json(indent=1) if current is not None else json.dumps(
        {"reader": reader, "domains": domains, "note": "no specification yet"})  # fmt: skip
    parts = [f"Reader: {reader}\nDomains (keep): {', '.join(domains)}\n\nCurrent specification:\n{cur}\n"]
    for i, s in enumerate(samples, 1):
        gold = "; ".join(f"{a} = {v}" for a, v in sorted(s.gold.items())) or "none"
        parts.append(f"Page {i} reference values: {gold}\n"
                     f'<untrusted_document url="{s.url}">\n{skeleton(s.html)}\n</untrusted_document>\n')  # fmt: skip
    parts.append("Labels found on the pages: " + " | ".join(found[:80]))
    if feedback:
        parts.append("Problems of the previous draft:\n- " + "\n- ".join(feedback[:20]))
    return "\n".join(parts)


# --- the graph ----------------------------------------------------------------------------------------------------


class DoctorState(TypedDict, total=False):
    reader: str
    domains: list[str]
    current: ParserSpec | None
    samples: list[Sample]
    found: list[str]
    evidence: dict[str, Any]
    reason: str
    drafts: int
    draft: ParserSpec | None
    errors: list[str]
    feedback: list[str]
    best: tuple[float, ParserSpec] | None
    stop: str | None
    change_id: str | None


@dataclass
class Doctor:
    llm: LLM
    charge: Any = None  # async charge(eur) raising BudgetExceeded
    system: str = ""
    log: list[dict[str, Any]] = field(default_factory=list)

    async def draft(self, st: DoctorState) -> DoctorState:
        from automind.acquisition.worker.budget import BudgetExceeded  # noqa: PLC0415

        n = int(st.get("drafts") or 0) + 1
        try:
            if self.charge is not None:
                await self.charge(EST_EUR)
        except BudgetExceeded:
            return {"drafts": n, "draft": None, "errors": [], "stop": "budget"}
        user = user_message(st.get("current"), st["reader"], st["domains"], st.get("samples") or [],
                            st.get("found") or [], st.get("feedback") or [])  # fmt: skip
        try:
            spec = await self.llm.structured(ROLE, ParserSpec, self.system or PROMPT.read_text(encoding="utf-8"),
                                             user)  # fmt: skip
        except ValidationError as e:
            errs = [f"schema: {'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()][:10]
            self.log.append({"draft": n, "errors": errs})
            return {"drafts": n, "draft": None, "errors": errs}
        except Exception as e:  # noqa: BLE001 - a failed call ends this run; the drift stays journalled
            self.log.append({"draft": n, "error": f"{type(e).__name__}: {e}"})
            return {"drafts": n, "draft": None, "errors": [], "stop": f"model call failed ({type(e).__name__})"}
        return {"drafts": n, "draft": spec, "errors": []}

    async def validate(self, st: DoctorState) -> DoctorState:
        from automind.acquisition.gates.infrastructure.wiring import change_journal  # noqa: PLC0415

        journal = change_journal()

        spec = st.get("draft")
        if spec is None:
            return {"errors": st.get("errors") or ["no draft"]}
        cur = st.get("current")
        # the page text cannot redirect the reader: reader, domains and version are code's
        spec = spec.model_copy(update={"reader": st["reader"], "domains": list(st["domains"]),
                                       "version": (cur.version + 1) if cur is not None else 1})  # fmt: skip
        errs = await journal.check(AGENT, ParserProposal(spec=spec))
        self.log.append({"draft": st.get("drafts"), "check": errs})
        return {"draft": spec, "errors": errs}

    async def self_replay(self, st: DoctorState) -> DoctorState:
        spec = st.get("draft")
        if spec is None or st.get("errors"):
            return {"feedback": list(st.get("errors") or [])}
        score, feedback = replay_samples(spec, st.get("samples") or [])
        self.log.append({"draft": st.get("drafts"), "score": score, "feedback": feedback})
        best = st.get("best")
        if score > 0 and (best is None or score > best[0]):
            best = (score, spec)
        return {"feedback": feedback, "best": best}

    def route(self, st: DoctorState) -> str:
        if st.get("stop"):
            return "propose"
        if not st.get("feedback") and st.get("best") is not None:
            return "propose"  # clean: every sample read, every gold value reproduced
        return "propose" if int(st.get("drafts") or 0) >= MAX_DRAFTS else "draft"

    async def propose(self, st: DoctorState) -> DoctorState:
        from automind.acquisition.gates.infrastructure.wiring import change_journal  # noqa: PLC0415

        journal = change_journal()

        best = st.get("best")
        if best is None:
            return {"stop": st.get("stop") or "no valid draft that reads the pages", "change_id": None}
        _, spec = best
        ev = {**(st.get("evidence") or {}), "drafts": st.get("drafts"),
              "snapshots": [s.snapshot_id for s in st.get("samples") or []]}  # fmt: skip
        cid = await journal.propose(AGENT, ParserProposal(spec=spec), st.get("reason") or "drift", ev)
        return {"change_id": cid, "stop": None if cid else "refused by the journal"}

    def graph(self) -> Any:
        from langgraph.graph import END, START, StateGraph  # noqa: PLC0415

        g = StateGraph(DoctorState)
        g.add_node("draft", self.draft)
        g.add_node("validate", self.validate)
        g.add_node("self_replay", self.self_replay)
        g.add_node("propose", self.propose)
        g.add_edge(START, "draft")
        g.add_edge("draft", "validate")
        g.add_edge("validate", "self_replay")
        g.add_conditional_edges("self_replay", self.route, {"draft": "draft", "propose": "propose"})
        g.add_edge("propose", END)
        return g.compile()


def replay_samples(spec: ParserSpec, samples: list[Sample]) -> tuple[float, list[str]]:
    """(score, problems) of a draft on the sample pages: rows read and gold values reproduced (code only)."""
    from automind.acquisition.parsing import interpreter  # noqa: PLC0415

    problems: list[str] = []
    score = 0.0
    for i, s in enumerate(samples, 1):
        try:
            rows = interpreter.read_rows(spec, s.html, s.url).rows
        except Exception as e:  # noqa: BLE001 - a draft that breaks the interpreter reads nothing
            problems.append(f"page {i}: the reader failed ({type(e).__name__})")
            continue
        if len(rows) < spec.min_rows:
            problems.append(f"page {i}: only {len(rows)} fields read (min_rows {spec.min_rows})")
            continue
        score += len(rows) / 100
        got = {r.attribute: r for r in rows}
        for attr, ref in s.gold.items():
            row = got.get(attr)
            if row is None:
                problems.append(f"page {i}: {attr} (reference {ref}) not read")
            elif _first_number(row.raw_value) is not None and not _close(row.raw_value, ref):
                problems.append(f"page {i}: {attr} read {row.raw_value} {row.raw_unit or ''} under "
                                f"{row.excerpt[:40]!r}, reference {ref}")  # fmt: skip
            else:
                score += 1
    return score, problems


_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _first_number(s: str) -> float | None:
    m = _NUM.search(s or "")
    if not m:
        return None
    t = m.group(0)
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    elif t.count(".") == 1 and len(t.split(".")[1]) == 3:
        t = t.replace(".", "")  # 1.615 kg
    try:
        return float(t)
    except ValueError:
        return None


def _close(raw: str, ref: str) -> bool:
    a, b = _first_number(raw), _first_number(ref)
    return a is not None and b is not None and abs(a - b) <= 0.03 * max(abs(b), 1e-9)


# --- collect (database) and the task --------------------------------------------------------------------------------


def reader_name(domain: str) -> str:
    """`motor.es` → `motor_es` (a reader name for a site without one)."""
    return re.sub(r"[^a-z0-9_]", "_", domain.lower().removeprefix("www."))[:40]


def _day(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


async def _drift_facts(version_key: str, change_id: str | None) -> dict[str, Any]:
    """The drift journal row's day and reason, and the first day of the window with the new structure."""
    from sqlalchemy import select  # noqa: PLC0415

    from automind.acquisition.infrastructure.config import acquisition_config  # noqa: PLC0415
    from automind.shared.infrastructure.db import AcqChange, ParserDaily, sessionmaker  # noqa: PLC0415

    async with sessionmaker()() as s:
        ch = await s.get(AcqChange, change_id) if change_id else None
        ev = dict(ch.evidence or {}) if ch is not None else {}
        as_of = _day(ev.get("day")) or (ch.created_at.date() if ch is not None else datetime.now(UTC).date())
        min_sim = float((acquisition_config().get("drift") or {}).get("min_similarity", 0.6))
        days = (await s.execute(select(ParserDaily.day, ParserDaily.structure_sim).where(
            ParserDaily.version_key == version_key, ParserDaily.day > as_of - timedelta(days=LOOKBACK_DAYS),
            ParserDaily.day <= as_of).order_by(ParserDaily.day))).all()  # fmt: skip
    changed = next((d for d, sim in days if sim is not None and sim < min_sim), None)
    return {"as_of": as_of, "changed_on": changed, "reason": (ch.reason if ch is not None else "drift"),
            "drift": (ch.explanation if ch is not None else "")}  # fmt: skip


def trigger(reason: str, changed_on: date | None, as_of: date) -> str:
    kind = reason.removeprefix("drift:")
    on = (changed_on or as_of).strftime("%d.%m")
    return {"structure": f"page layout changed on {on}", "zero_streak": f"pages read empty since {on}",
            "yield_drop": f"fields per page fell by {on}", "pass_drop": f"checks failing more by {on}",
            "new_site": "a spec site without a reader"}.get(kind, f"{kind} on {on}")  # fmt: skip


async def collect(payload: dict[str, Any]) -> DoctorState:
    from automind.acquisition.gates.infrastructure import page_reading as evaluate  # noqa: PLC0415
    from automind.acquisition.infrastructure.fetch import decode_body  # noqa: PLC0415
    from automind.acquisition.parsing import store  # noqa: PLC0415
    from automind.acquisition.replay import run  # noqa: PLC0415
    from automind.acquisition.snapshots import store as snapshots  # noqa: PLC0415

    current = None
    if key := payload.get("version"):
        v = await store.version(str(key))
        current = v.spec if v is not None else None
    if current is not None:
        reader, domains = current.reader, list(current.domains)
        facts = await _drift_facts(current.key, payload.get("change_id"))
    else:
        domain = str(payload.get("domain") or "").lower()
        reader, domains = reader_name(domain), [domain]
        facts = {"as_of": datetime.now(UTC).date(), "changed_on": None, "reason": "new_site", "drift": ""}
    as_of, changed = facts["as_of"], facts["changed_on"]
    since = datetime.combine(changed or as_of - timedelta(days=LOOKBACK_DAYS), time.min, tzinfo=UTC)
    until = datetime.combine(as_of + timedelta(days=1), time.min, tzinfo=UTC)
    refs = list(reversed(await evaluate.corpus_refs(domains, since, until, limit=500)))  # newest first
    refs.sort(key=lambda r: (not r.variant_ids,))  # pages of known cars (with gold) first, stable
    picked = refs[:SAMPLE_PAGES]
    bodies = await snapshots.load_bodies(sorted({r.blob_sha256 for r in picked}))
    gold = await run.gold_values({v for r in picked for v in r.variant_ids})
    samples = []
    found: list[str] = []
    for r in picked:
        if r.blob_sha256 not in bodies:
            continue
        html = decode_body(bodies[r.blob_sha256], None)
        g = {a: f"{x.num:g} {x.unit}" if x.num is not None else str(x.text)
             for (vid, a), x in gold.items() if r.variant_ids and vid == r.variant_ids[0]}  # fmt: skip
        samples.append(Sample(r.id, r.final_url or r.url, html, r.variant_ids, g))
        found += [x for x in labels(html) if x not in found]
    evidence = {"as_of": as_of.isoformat(), "changed_on": changed.isoformat() if changed else None,
                "trigger": trigger(str(facts["reason"]), changed, as_of), "drift": facts["drift"],
                "drift_change": payload.get("change_id"), "degraded": current is not None}  # fmt: skip
    return {
        "reader": reader,
        "domains": domains,
        "current": current,
        "samples": samples,
        "found": found,
        "evidence": evidence,
        "reason": str(facts["reason"]),
        "drafts": 0,
        "best": None,
        "feedback": [],
    }


async def run_doctor(payload: dict[str, Any], *, llm: LLM | None = None, charge: Any = None) -> dict[str, Any]:
    st = await collect(payload)
    if not st.get("samples"):
        return {"skipped": "no stored pages of the site in its current layout"}
    doc = Doctor(llm or LLM_OVERRIDE or GatewayLLM(), charge)
    out = await doc.graph().ainvoke(st)
    return {"reader": st["reader"], "drafts": out.get("drafts"), "change_id": out.get("change_id"),
            "stop": out.get("stop"), "log": doc.log[-6:]}  # fmt: skip


async def sweep() -> dict[str, Any]:
    """Daily: active spec-database sources with access "ok", no parser and stored pages get a doctor task."""
    from sqlalchemy import text  # noqa: PLC0415

    from automind.acquisition.worker import queue  # noqa: PLC0415
    from automind.shared.infrastructure.db import sessionmaker  # noqa: PLC0415

    q = text(
        "SELECT s.domain FROM sources s WHERE s.source_type = 'SPEC_DATABASE' AND s.access = 'ok' AND NOT s.frozen "
        "AND EXISTS (SELECT 1 FROM capabilities c WHERE c.domain = s.domain AND c.status = 'active') "
        "AND NOT EXISTS (SELECT 1 FROM parsers p WHERE s.domain = ANY(p.domains)) "
        "AND (SELECT count(*) FROM page_snapshots ps WHERE ps.domain = s.domain AND ps.replayable "
        "     AND ps.fetched_at > now() - interval '30 days') >= :n"
    )
    async with sessionmaker()() as s:
        domains = [str(d) for (d,) in (await s.execute(q, {"n": SAMPLE_PAGES})).all()]
    queued = [d for d in domains if await queue.enqueue(AGENT, {"domain": d}, dedupe_key=f"doctor:new:{d}")]
    return {"sweep": True, "queued": queued}


async def handle(payload: dict[str, Any], *, guard: Any = None, llm: LLM | None = None) -> dict[str, Any]:
    if not payload.get("version") and not payload.get("domain"):
        return await sweep()
    if why := await budgets.stop_reason(AGENT):
        return {"skipped": why}
    return await run_doctor(payload, llm=llm, charge=guard.charge if guard is not None else None)
