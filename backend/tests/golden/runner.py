"""Golden dialogue runner (FR-046): replay mode (cassettes + fixture search) and live mode.

Replay: each turn loads `cassettes/<id>/turn<N>.json` ({role: [outputs...]}) into the FakeLLM and
uses the dialogue's fixture search scenario. All scripted outputs must be consumed.
Live: the real gateway and Tavily; with `--record` the model outputs are written as cassettes.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from sqlalchemy import delete, select

from automind.application.ports import Ports
from automind.infrastructure.db import models as m
from automind.infrastructure.db.repositories import (
    CaseRepo,
    EventRepo,
    FeasibilityRepo,
    JobRepo,
    MarketFactRepo,
    MessageRepo,
    TurnRepo,
)
from automind.infrastructure.db.session import sessionmaker
from automind.infrastructure.events import EventBus
from automind.orchestration.runner import ChatRunner, TurnResult
from tests.fakes.fake_llm import FakeLLM, FixedEstimator
from tests.fakes.fixture_search import FixtureSearch

from .schema import Dialogue, Expect

GOLDEN_DIR = Path(__file__).resolve().parent
CASSETTES = GOLDEN_DIR / "cassettes"
FRESH_AREAS = (
    "specs",
    "engineering",
    "measured",
    "price",
    "maintenance",
    "reviews",
    "reliability",
    "manufacturer",
    "used_issues",
)


def load(path: Path) -> Dialogue:
    return Dialogue.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


# --- assertions -------------------------------------------------------------------------------

_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def get_path(obj: Any, path: str) -> Any:
    cur = obj
    for name, idx in _TOKEN.findall(path):
        if cur is None:
            return None
        if idx:
            i = int(idx)
            cur = cur[i] if isinstance(cur, list) and i < len(cur) else None
        else:
            cur = cur.get(name) if isinstance(cur, dict) else None
    return cur


def check_value(actual: Any, expected: Any) -> str | None:
    if isinstance(expected, dict) and expected and set(expected) <= {"contains", "not_contains", "lte", "gte", "in"}:
        for op, val in expected.items():
            seq = actual if isinstance(actual, (list, str)) else []
            items = [x.get("criterion", x) if isinstance(x, dict) else x for x in seq] if isinstance(seq, list) else seq
            if op == "contains" and val not in items:
                return f"{actual!r} does not contain {val!r}"
            if op == "not_contains" and val in items:
                return f"{actual!r} contains {val!r}"
            if op == "lte" and not (actual is not None and actual <= val):
                return f"{actual!r} > {val!r}"
            if op == "gte" and not (actual is not None and actual >= val):
                return f"{actual!r} < {val!r}"
            if op == "in" and actual not in val:
                return f"{actual!r} not in {val!r}"
        return None
    return None if actual == expected else f"{actual!r} != {expected!r}"


@dataclass
class TurnObservation:
    result: TurnResult
    case: dict[str, Any]
    variants: dict[str, dict[str, Any]]
    search_calls: int
    researched: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    energy_report: dict[str, Any] | None = None  # spec 006 FR-022: the intake event of this turn


def check_turn(obs: TurnObservation, exp: Expect) -> list[str]:
    errs: list[str] = []
    r = obs.result
    if exp.action and r.action != exp.action:
        errs.append(f"action {r.action!r} != {exp.action!r}")
    if exp.status and r.status != exp.status:
        errs.append(f"status {r.status!r} != {exp.status!r}")
    for path, val in exp.case.items():
        if (e := check_value(get_path(obs.case, path), val)) is not None:
            errs.append(f"case.{path}: {e}")
    for v in exp.variants:
        got = obs.variants.get(v.car)
        if got is None:
            errs.append(f"{v.car}: no resolved variant")
            continue
        if v.generation and got.get("generation") != v.generation:
            errs.append(f"{v.car}: generation {got.get('generation')!r} != {v.generation!r}")
        if v.make and got.get("make") != v.make:
            errs.append(f"{v.car}: make {got.get('make')!r} != {v.make!r}")
        if v.model and got.get("model") != v.model:
            errs.append(f"{v.car}: model {got.get('model')!r} != {v.model!r}")
        if v.years_include:
            lo, hi = got.get("generation_years_from"), got.get("generation_years_to")
            if lo is None or v.years_include < lo or (hi is not None and v.years_include > hi):
                errs.append(f"{v.car}: years {lo}-{hi} do not include {v.years_include}")
    for gen in exp.no_variant_generation:
        if any(x.get("generation") == gen for x in obs.variants.values()):
            errs.append(f"generation {gen} present in resolved variants")
        if any(gen in (o.get("label") or "") for o in (r.confirm or {}).get("options", [])):
            errs.append(f"generation {gen} offered in confirmation options")
    if exp.max_questions is not None:
        n = len((obs.case.get("pending") or {}).get("items", []))
        if n > exp.max_questions or n == 0:
            errs.append(f"{n} questions (expected 1..{exp.max_questions})")
    if exp.no_search and obs.search_calls:
        errs.append(f"{obs.search_calls} search calls (expected none)")
    if exp.max_cost_eur is not None and r.usage.get("cost_eur", 0) > exp.max_cost_eur:
        errs.append(f"cost €{r.usage.get('cost_eur')} > €{exp.max_cost_eur}")
    if exp.confirm_kind and (r.confirm or {}).get("kind") != exp.confirm_kind:
        errs.append(f"confirm kind {(r.confirm or {}).get('kind')!r} != {exp.confirm_kind!r}")
    if exp.language and r.state.get("language") != exp.language:
        errs.append(f"language {r.state.get('language')!r} != {exp.language!r}")
    if exp.researched is not None and sorted(obs.researched) != sorted(exp.researched):
        errs.append(f"researched {sorted(obs.researched)} != {sorted(exp.researched)}")
    errs += check_electrified(obs, exp)
    for path, val in exp.energy_metrics.items():
        if obs.energy_report is None:
            errs.append("no ENERGY_REPORT metric recorded")
            break
        if (e := check_value(get_path(obs.energy_report, path), val)) is not None:
            errs.append(f"energy metric {path}: {e}")
    if exp.block_order_starts_with:
        types = [b.get("type") for b in r.blocks if b.get("type") != "notice"]
        if types[: len(exp.block_order_starts_with)] != exp.block_order_starts_with:
            errs.append(f"blocks start {types[:4]} != {exp.block_order_starts_with}")
    return errs


def _block(r: TurnResult, kind: str) -> dict[str, Any]:
    return next((b for b in r.blocks if b.get("type") == kind), {})


def check_electrified(obs: TurnObservation, exp: Expect) -> list[str]:  # noqa: C901 - one check per field
    """Spec 006 expectations on the report blocks."""
    errs: list[str] = []
    ids = {k: v.get("id") for k, v in obs.variants.items()}
    tco = {c["car_id"]: c for c in _block(obs.result, "tco").get("cars", [])}

    def energy(car: str) -> dict[str, Any]:
        items = (tco.get(ids.get(car) or "") or {}).get("items", [])
        return next((i for i in items if i.get("kind") == "ENERGY"), {})

    for car in exp.energy_for:
        if energy(car).get("annual_eur") is None:
            errs.append(f"{car}: no energy amount ({energy(car).get('label')!r})")
    for car in exp.energy_missing_for:
        if energy(car).get("annual_eur") is not None or not energy(car).get("missing"):
            errs.append(f"{car}: energy computed although inputs are missing")
    if exp.no_weighted_priced:
        for c in tco.values():
            for i in c.get("items", []):
                if i.get("kind") == "ENERGY" and any("weighted" in str(p) for p in i.get("parts", [])):
                    errs.append(f"{c['label']}: a weighted figure is priced")
    verdict = _block(obs.result, "verdict")
    for car, label in exp.labels.items():
        got = (verdict.get("labels") or {}).get(ids.get(car) or "", {}).get("label")
        if got != label:
            errs.append(f"{car}: label {got!r} != {label!r}")
    if exp.break_even is not None:
        got = (verdict.get("break_even") or {}).get("verdict")
        if got != exp.break_even:
            errs.append(f"break-even {got!r} != {exp.break_even!r}")
    for text in exp.notes_contain:
        if not any(text in n for n in verdict.get("profile_notes", [])):
            errs.append(f"no profile note with {text!r}: {verdict.get('profile_notes')}")
    el = _block(obs.result, "electric")
    rows = {c["car_id"]: c for c in el.get("cars", [])}
    if exp.electric_cars is not None and sorted(rows) != sorted(ids.get(c) or c for c in exp.electric_cars):
        errs.append(f"electric section cars {sorted(c['label'] for c in rows.values())} != {exp.electric_cars}")
    for car in exp.electric_share_for:
        share = ((rows.get(ids.get(car) or "") or {}).get("values") or {}).get("electric_share", {}).get("share")
        if share is None:
            errs.append(f"{car}: no electric share")
    ret = {c["car_id"]: c for c in _block(obs.result, "value_retention").get("cars", [])}
    for car in exp.retention_insufficient:
        if not (ret.get(ids.get(car) or "") or {}).get("insufficient"):
            errs.append(f"{car}: resale value not marked insufficient")
    return errs


# --- seeding and observation ------------------------------------------------------------------


async def hide_makes(d: Dialogue) -> list[tuple[str, str, str]]:
    """Hide other tests' catalog rows of the `forget` makes for one dialogue (the dialogue's own seeded rows stay);
    `restore_makes` puts them back, so later tests (candidates, corrections) still find them."""
    if not d.forget:
        return []
    from automind.domain.identity import Aliases, canonical_key
    from automind.infrastructure.config import aliases

    al = Aliases.from_config(aliases())
    own = {canonical_key(v.make, v.model, v.generation, v.variant_name, v.powertrain, al) for v in d.seed}
    async with sessionmaker()() as s:
        q = select(m.Variant).where(m.Variant.make.in_(d.forget), m.Variant.canonical_key.not_in(own))
        rows = (await s.execute(q)).scalars().all()
        saved = [(v.id, v.make, v.canonical_key) for v in rows]
        for v in rows:
            v.make, v.canonical_key = f"hidden-{uuid.uuid4().hex[:8]}", f"{v.canonical_key}#hidden#{v.id}"
        await s.commit()
    return saved


async def restore_makes(saved: list[tuple[str, str, str]]) -> None:
    if not saved:
        return
    async with sessionmaker()() as s:
        for vid, make, key in saved:
            v = await s.get(m.Variant, vid)
            if v is not None:
                v.make, v.canonical_key = make, key
        await s.commit()


async def seed(d: Dialogue) -> None:
    from datetime import date, datetime

    from automind.domain.identity import Aliases, canonical_key
    from automind.infrastructure.config import aliases

    al = Aliases.from_config(aliases())

    async with sessionmaker()() as s:
        # spec 006: market facts are global; every dialogue starts from its own (fresh as of the fixed clock)
        await s.execute(delete(m.MarketFact))
        await s.execute(delete(m.ResearchRun).where(m.ResearchRun.area == "incentives"))
        for f in d.market_facts:
            s.add(
                m.MarketFact(
                    market="ES",
                    key=f["key"],
                    value=f["value"],
                    evidence_ids=["golden"],
                    valid_from=date.fromisoformat(f["valid_from"]) if f.get("valid_from") else None,
                    valid_to=date.fromisoformat(f["valid_to"]) if f.get("valid_to") else None,
                    fetched_at=datetime.fromisoformat(f.get("fetched_at", "2026-10-25T00:00:00+00:00")),
                )
            )
        for v in d.seed:
            key = canonical_key(v.make, v.model, v.generation, v.variant_name, v.powertrain, al)
            existing = (await s.execute(select(m.Variant).where(m.Variant.canonical_key == key))).scalar_one_or_none()
            if existing is None:
                existing = m.Variant(
                    canonical_key=key,
                    make=v.make,
                    model=v.model,
                    generation=v.generation,
                    variant_name=v.variant_name,
                    powertrain=v.powertrain,
                    body_class=v.body_class,
                    model_year_from=v.years[0] if v.years else None,
                    generation_years_from=v.years[0] if v.years else None,
                    generation_years_to=v.years[1] if v.years else None,
                    vehicle_class=v.vehicle_class,
                    segment=v.segment,
                )
                s.add(existing)
                await s.flush()
            if not v.cached:  # make the dialogue reproducible: forget earlier research of this variant
                for t in (m.ResearchRun, m.SpecValue):
                    await s.execute(delete(t).where(t.variant_id == existing.id))
            if v.cached:
                for area in FRESH_AREAS:
                    await s.execute(
                        delete(m.ResearchRun).where(m.ResearchRun.variant_id == existing.id, m.ResearchRun.area == area)
                    )
                    s.add(m.ResearchRun(variant_id=existing.id, area=area, minimum_met=True))
                for attr, val in v.specs.items():
                    await s.execute(
                        delete(m.SpecValue).where(m.SpecValue.variant_id == existing.id, m.SpecValue.attribute == attr)
                    )
                    s.add(
                        m.SpecValue(
                            variant_id=existing.id,
                            attribute=attr,
                            available=True,
                            value_num=val if isinstance(val, (int, float)) else None,
                            value_text=val if isinstance(val, str) else None,
                            provenance="MANUFACTURER_CLAIM",
                            confidence="HIGH",
                        )
                    )
        await s.commit()


async def variants_of(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    async with sessionmaker()() as s:
        for car in case.get("cars", []):
            vid = car.get("variant_id")
            if vid:
                v = await s.get(m.Variant, vid)
                if v is not None:
                    out[car["key"]] = {
                        "id": v.id,
                        "make": v.make,
                        "model": v.model,
                        "generation": v.generation,
                        "generation_years_from": v.generation_years_from,
                        "generation_years_to": v.generation_years_to,
                        "label": v.label,
                    }
    return out


async def energy_report(turn_id: str) -> dict[str, Any] | None:
    async with sessionmaker()() as s:
        q = select(m.IntakeEvent.details).where(m.IntakeEvent.turn_id == turn_id, m.IntakeEvent.kind == "ENERGY_REPORT")
        row = (await s.execute(q)).first()
    return dict(row[0]) if row else None


async def researched_cars(turn_id: str, case: dict[str, Any]) -> list[str]:
    keys = {c.get("variant_id"): c["key"] for c in case.get("cars", [])}
    async with sessionmaker()() as s:
        vids = {
            v
            for (v,) in (
                await s.execute(select(m.ResearchJob.variant_id).where(m.ResearchJob.turn_id == turn_id))
            ).all()
        }
    return sorted(keys.get(v, v) for v in vids)


# --- recording LLM (live --record) ------------------------------------------------------------


class RecordingLLM:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.turn: dict[str, list[Any]] = {}

    def _rec(self, role: str, out: Any) -> None:
        self.turn.setdefault(role, []).append(out.model_dump(mode="json") if isinstance(out, BaseModel) else out)

    async def structured(self, role, schema, system, user):  # noqa: ANN001
        out = await self.inner.structured(role, schema, system, user)
        self._rec(role, out)
        return out

    async def text(self, role, system, user):  # noqa: ANN001
        out = await self.inner.text(role, system, user)
        self._rec(role, out)
        return out

    def agent(self, role, tools, system_prompt):  # noqa: ANN001
        agent = self.inner.agent(role, tools, system_prompt)
        rec = self

        class _A:
            async def ainvoke(self, inputs, config=None):  # noqa: ANN001
                res = await agent.ainvoke(inputs, config)
                msgs = res["messages"]
                calls = [
                    {"name": tc["name"], "args": tc["args"]}
                    for msg in msgs
                    for tc in (getattr(msg, "tool_calls", None) or [])
                ]
                final = msgs[-1].text if isinstance(getattr(msgs[-1], "text", None), str) else str(msgs[-1].content)
                rec._rec(role, {"tool_calls": calls, "answer": final})
                return res

        return _A()


# --- driver -----------------------------------------------------------------------------------


async def run_dialogue(path: Path, saver: Any, *, live: bool = False, record: bool = False) -> list[str]:
    """Run one golden dialogue. Returns a list of failure messages (empty = pass)."""
    d = load(path)
    hidden = await hide_makes(d)
    try:
        return await _run_dialogue(d, saver, live=live, record=record)
    finally:
        await restore_makes(hidden)


async def _run_dialogue(d: Dialogue, saver: Any, *, live: bool, record: bool) -> list[str]:
    from automind.orchestration.graph import build_graph  # US1 (T035)

    await seed(d)
    chat_id = str(uuid.uuid4())
    async with sessionmaker()() as s:  # as the API does: per-chat metrics (intake events) need the chat row
        s.add(m.Chat(id=chat_id, title=d.id[:60]))
        await s.commit()
    if live:
        from automind.infrastructure.adapters import LiveLLM, live_pages, live_search
        from automind.infrastructure.llm_gateway import new_budget

        llm: Any = RecordingLLM(LiveLLM()) if record else LiveLLM()
        search: Any = live_search()
        budgets = new_budget
    else:
        llm = FakeLLM()
        search = FixtureSearch(d.scenario) if d.scenario else FixtureSearch("empty")
        from tests.graph.conftest import budget_factory

        budgets = budget_factory()
    events = EventBus(EventRepo())
    from automind.infrastructure.config import reference
    from automind.orchestration.prompts import load_all
    from tests.graph.conftest import open_web_reference

    ports = Ports(
        llm=llm,
        search=search,
        cases=CaseRepo(),
        turns=TurnRepo(),
        events=events,
        jobs=JobRepo(),
        clock=_clock(),
        ref=reference(load_all()) if live else open_web_reference(),
        messages=MessageRepo(),
        estimator=_estimator(live),
        pages=live_pages() if live else None,
        feasibility=FeasibilityRepo(),
        market_facts=MarketFactRepo(),
    )
    runner = ChatRunner(build_graph(saver), ports, budgets, messages=MessageRepo())
    failures: list[str] = []
    from automind.config import settings as _settings

    saved = {k: getattr(_settings(), k) for k in d.settings}
    for k, v in d.settings.items():
        setattr(_settings(), k, v)
    try:
        return await _run_turns(d, runner, chat_id, live, record, failures, llm, ports)
    finally:
        for k, v in saved.items():
            setattr(_settings(), k, v)


async def _run_turns(d, runner, chat_id, live, record, failures, llm, ports):  # noqa: ANN001, ANN202
    for i, turn in enumerate(d.turns, 1):
        cassette = CASSETTES / d.id / f"turn{i}.json"
        if not live:
            if not cassette.exists():
                return [f"missing cassette {cassette.relative_to(GOLDEN_DIR)}"]
            for role, outs in json.loads(cassette.read_text(encoding="utf-8")).items():
                llm.queue(role, *outs)
        if turn.user is not None:
            result = await runner.run_turn(chat_id, turn.user)
        else:
            result = await runner.resume(chat_id, {"choice": turn.confirm, "text": None})
        _, case, _ = await ports.cases.latest(chat_id)
        searches = int(result.usage.get("search_calls", 0))
        obs = TurnObservation(
            result,
            case or {},
            await variants_of(case or {}),
            searches,
            await researched_cars(result.turn_id, case or {}),
            energy_report=await energy_report(result.turn_id),
        )
        if os.environ.get("GOLDEN_VERBOSE"):
            async with sessionmaker()() as ss:
                dur = (await ss.get(m.Turn, result.turn_id)).duration_ms
            print(
                f"\n[{d.id} turn {i}] status={result.status} action={result.action} duration_ms={dur} "
                f"usage={result.usage}"
            )
            print(
                "  case:", json.dumps({k: obs.case.get(k) for k in ("persona", "priorities", "pending")}, default=str)
            )
            print(
                "  cars:",
                [(c["key"], c["condition"], c.get("year"), c["resolution"]) for c in obs.case.get("cars", [])],
            )
            print("  variants:", {k: v["label"] for k, v in obs.variants.items()})
            print("  reply:", (result.reply_text or (result.confirm or {}).get("text", ""))[:160].replace("\n", " "))
            print("  blocks:", [b.get("type") for b in result.blocks])
        failures += [f"{d.id} turn {i}: {e}" for e in check_turn(obs, turn.expect)]
        if not live:
            left = {r: len(q) for r, q in llm.queues.items() if q}
            if left:
                failures.append(f"{d.id} turn {i}: unconsumed cassette outputs {left}")
            llm.queues.clear()
        elif record:
            cassette.parent.mkdir(parents=True, exist_ok=True)
            cassette.write_text(json.dumps(llm.turn, ensure_ascii=False, indent=2), encoding="utf-8")
            llm.turn = {}
    return failures


def _clock() -> Any:
    from tests.graph.conftest import FixedClock

    return FixedClock()


def _estimator(live: bool) -> Any:
    if live:
        from automind.infrastructure.adapters import LiveEstimator

        return LiveEstimator()
    return FixedEstimator()
