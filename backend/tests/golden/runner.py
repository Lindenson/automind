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
from automind.infrastructure.db.repositories import CaseRepo, EventRepo, JobRepo, MessageRepo, TurnRepo
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
    if exp.block_order_starts_with:
        types = [b.get("type") for b in r.blocks if b.get("type") != "notice"]
        if types[: len(exp.block_order_starts_with)] != exp.block_order_starts_with:
            errs.append(f"blocks start {types[:4]} != {exp.block_order_starts_with}")
    return errs


# --- seeding and observation ------------------------------------------------------------------


async def seed(d: Dialogue) -> None:
    from automind.domain.identity import Aliases, canonical_key
    from automind.infrastructure.config import aliases

    al = Aliases.from_config(aliases())

    async with sessionmaker()() as s:
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
                        "make": v.make,
                        "model": v.model,
                        "generation": v.generation,
                        "generation_years_from": v.generation_years_from,
                        "generation_years_to": v.generation_years_to,
                        "label": v.label,
                    }
    return out


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
    from automind.orchestration.graph import build_graph  # US1 (T035)

    d = load(path)
    await seed(d)
    chat_id = str(uuid.uuid4())
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
    )
    runner = ChatRunner(build_graph(saver), ports, budgets, messages=MessageRepo())
    failures: list[str] = []
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
