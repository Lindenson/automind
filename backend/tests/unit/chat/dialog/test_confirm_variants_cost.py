"""Spec 012 S9 (T074): characterisation of the CONFIRM_VARIANTS and CONFIRM_COST confirmations (prepare → apply),
which no graph scenario reaches since the intake card (spec 005 R7) comes first. Pinned before the dialog's logic
moves into services. Nodes run with an in-memory case store, event log and messages; the catalogue is the test
database (test-only makes "S9…", removed before each test)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete

from automind.chat.application.services.identification import catalogue
from automind.chat.application.services.identification.contracts import VariantIdentity
from automind.chat.dialog.nodes import confirm
from automind.chat.dialog.prompts import load_all
from automind.chat.dialog.runner import TurnContext
from automind.chat.domain.case import CaseCar, CaseFile, Pending
from automind.delivery.bootstrap import reference
from automind.shared.infrastructure import db

MAKE = "S9Confirm"


@dataclass
class Store:
    """Cases, events and messages of one chat, in memory."""

    case: dict[str, Any] | None = None
    versions: list[list[str]] = field(default_factory=list)
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    messages: list[tuple[str, str, Any]] = field(default_factory=list)

    async def latest(self, chat_id: str) -> tuple[int, dict[str, Any] | None, str | None]:
        return len(self.versions), self.case, None

    async def save_version(self, chat_id: str, data: dict[str, Any], changed_by: str, change_log: list[str]) -> int:
        self.case = data
        self.versions.append(change_log)
        return len(self.versions)

    async def publish(self, chat_id: str, turn_id: str | None, type_: str, payload: dict[str, Any]) -> int:
        self.events.append((type_, payload))
        return len(self.events)

    async def save(self, chat_id: str, role: str, text: str, blocks: Any, turn_id: str | None = None) -> Any:
        self.messages.append((role, text, blocks))
        return SimpleNamespace(id=f"m{len(self.messages)}", created_at=datetime(2026, 11, 1, tzinfo=UTC))


class LLM:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)

    async def structured(self, name: str, schema: Any, prompt: str, user: str) -> Any:
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def _runtime(store: Store, case: CaseFile, llm: LLM | None = None) -> SimpleNamespace:
    store.case = case.model_dump(mode="json")
    clock = SimpleNamespace(now=lambda: datetime(2026, 11, 1, tzinfo=UTC))
    ports = SimpleNamespace(ref=reference(load_all()), cases=store, events=store, messages=store, llm=llm or LLM(),
                            acquisition=None, clock=clock)  # fmt: skip
    return SimpleNamespace(context=TurnContext(ports=ports, chat_id="chat-s9", turn_id="turn-s9", budget=None))  # type: ignore[arg-type]


def _case(store: Store) -> CaseFile:
    return CaseFile.model_validate(store.case)


def _ident(**kw: Any) -> VariantIdentity:
    base: dict[str, Any] = dict(make=MAKE, model="Cx", generation="G1", generation_years_from=2019,
                                generation_years_to=None, variant_name="2.0 diesel 150 CV", powertrain="ICE",
                                certainty="exact", engine_cc=1998, power_kw=110, fuel="diesel")  # fmt: skip
    return VariantIdentity(**{**base, **kw})


def _car(**kw: Any) -> CaseCar:
    base: dict[str, Any] = dict(key="car#1", request_text=f"{MAKE} Cx", make=MAKE, model="Cx", condition="USED",
                                year=2021)  # fmt: skip
    return CaseCar(**{**base, **kw})


@pytest.fixture(autouse=True)
async def _db() -> None:
    await db.init_db()
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.Variant).where(db.Variant.make.like("S9%")))
        await s.commit()


# --- CONFIRM_VARIANTS ------------------------------------------------------------------------------------------


async def test_prepare_variants_proposes_the_best_candidate_with_its_options() -> None:
    store = Store()
    v = await catalogue.upsert_variant(_ident(), reference(load_all()))
    cands = [catalogue.variant_dict(v)]
    state = {"decision": {"cars": ["car#1"]}, "assessments": {"car#1": {"candidates": cands}}, "language": "en"}
    out = await confirm.prepare_variants(state, _runtime(store, CaseFile(cars=[_car()])))  # type: ignore[arg-type]
    p = out["confirm_payload"]
    assert (p["kind"], p["action"]) == ("variants", "CONFIRM_VARIANTS")
    ids = [o["id"] for o in p["options"]]
    assert ids == [f"option:car#1:{v.id}", "remove:car#1", "choose"]
    assert p["options"][0]["label"] == f"{v.label} (2019–now)" and p["options"][0]["detail"] == "used, ~2021"
    case = _case(store)
    assert (case.car("car#1").variant_id, case.car("car#1").resolution) == (v.id, "PROPOSED")
    assert case.pending is not None and case.pending.kind == "CONFIRM_VARIANTS"
    assert store.versions[-1] == [f"car#1 proposed: {v.label} (2019–now)"]


async def test_prepare_variants_asks_the_resolver_on_a_catalogue_miss() -> None:
    store = Store()
    llm = LLM(_ident(note="Not on the Spanish line-up."))
    state = {"decision": {"cars": ["car#1"]}, "assessments": {}, "language": "en"}
    out = await confirm.prepare_variants(state, _runtime(store, CaseFile(cars=[_car()]), llm))  # type: ignore[arg-type]
    assert out["confirm_payload"]["options"][0]["id"].startswith("option:car#1:")
    assert any("Not on the Spanish line-up." in n["text"] for n in out["notices"])


async def test_prepare_variants_with_only_unknown_models_goes_back_to_assess() -> None:
    store = Store()
    llm = LLM(_ident(model="Zzz", generation=None, known_model=False))
    state = {"decision": {"cars": ["car#1"]}, "assessments": {}, "language": "en"}
    out = await confirm.prepare_variants(state, _runtime(store, CaseFile(cars=[_car(model="Qqq")]), llm))  # type: ignore[arg-type]
    assert (out["route"], out["confirm_payload"]) == ("assess", None)
    assert _case(store).car("car#1").resolution == "UNKNOWN_MODEL"
    assert store.versions[-1] == ["car#1: unknown model"]


async def test_prepare_variants_warns_about_a_generation_of_another_year() -> None:
    store = Store()
    llm = LLM(_ident(generation="G0", generation_years_from=2001, generation_years_to=2006))
    state = {"decision": {"cars": ["car#1"]}, "assessments": {}, "language": "en"}
    out = await confirm.prepare_variants(state, _runtime(store, CaseFile(cars=[_car()]), llm))  # type: ignore[arg-type]
    assert out["route"] == "assess"
    assert any(n["level"] == "warning" and "Please tell me the generation or year" in n["text"] for n in out["notices"])


def _pending_case(vid: str, label: str) -> CaseFile:
    return CaseFile(cars=[_car(variant_id=vid, label=label, resolution="PROPOSED")],
                    pending=Pending(kind="CONFIRM_VARIANTS", items=[{"car": "car#1"}]))  # fmt: skip


async def test_apply_variants_free_text_is_interpreted() -> None:
    store = Store()
    state = {"resume": {"choice": "text", "text": "no, the 1.5"}}
    out = await confirm.apply_variants(state, _runtime(store, _pending_case("x", "X")))  # type: ignore[arg-type]
    assert (out["route"], out["user_text"]) == ("interpret", "no, the 1.5")


async def test_apply_variants_skip_unsets_the_proposals() -> None:
    store = Store()
    out = await confirm.apply_variants({"resume": {"choice": "skip"}, "language": "en"},
                                       _runtime(store, _pending_case("x", "X")))  # type: ignore[arg-type]  # fmt: skip
    assert out["route"] == "end" and out["action"] == "CONFIRM_VARIANTS"
    car = _case(store).car("car#1")
    assert (car.variant_id, car.resolution) == (None, "UNRESOLVED") and _case(store).pending is None


async def test_apply_variants_remove_drops_the_car() -> None:
    store = Store()
    out = await confirm.apply_variants({"resume": {"choice": "remove:car#1"}},
                                       _runtime(store, _pending_case("x", "X")))  # type: ignore[arg-type]  # fmt: skip
    assert out["route"] == "assess" and _case(store).cars == [] and store.versions[-1] == ["car#1 removed"]


async def test_apply_variants_option_confirms_that_version_and_says_agreed() -> None:
    store = Store()
    v = await catalogue.upsert_variant(_ident(), reference(load_all()))
    other = await catalogue.upsert_variant(_ident(variant_name="1.5 petrol 130 CV", engine_cc=1498, power_kw=96,
                                                  fuel="petrol"), reference(load_all()))  # fmt: skip
    out = await confirm.apply_variants({"resume": {"choice": f"option:car#1:{other.id}"}, "language": "en"},
                                       _runtime(store, _pending_case(v.id, v.label)))  # type: ignore[arg-type]  # fmt: skip
    car = _case(store).car("car#1")
    assert out["route"] == "assess" and (car.variant_id, car.resolution) == (other.id, "CONFIRMED")
    assert store.versions[-1] == [f"car#1 confirmed: {other.label}"]
    assert store.messages and store.messages[-1][2][0]["type"] == "agreed"
    assert any(t == "agreed" for t, _ in store.events)


# --- CONFIRM_COST ----------------------------------------------------------------------------------------------


async def test_prepare_cost_states_the_estimate_and_the_cap() -> None:
    store = Store()
    car = _car(variant_id="x", label="S9Confirm Cx 2.0")
    state = {"decision": {"cars": ["car#1"], "over_cap": True}, "cost_estimate": 1.234, "language": "en",
             "research_plan": {"jobs": [["car#1", "x", "price"], ["car#1", "x", "specs"]]}}  # fmt: skip
    out = await confirm.prepare_cost(state, _runtime(store, CaseFile(cars=[car])))  # type: ignore[arg-type]
    p = out["confirm_payload"]
    assert (p["kind"], p["action"]) == ("cost", "CONFIRM_COST")
    assert p["estimate"] == {"eur": 1.234, "cars": 1, "areas": ["price", "specs"], "depth": "STANDARD"}
    assert "1.23" in p["text"] and "S9Confirm Cx 2.0" in p["text"]
    assert _case(store).pending is not None and _case(store).pending.kind == "CONFIRM_COST"
    assert store.events[-1] == ("status", {"stage": "estimating", "text": "Estimated research cost €1.23"})


async def test_apply_cost_approves_or_remembers_the_refusal() -> None:
    store = Store()
    pending = CaseFile(cars=[_car()], pending=Pending(kind="CONFIRM_COST", items=[]))
    out = await confirm.apply_cost({"resume": {"choice": "run"}}, _runtime(store, pending))  # type: ignore[arg-type]
    assert (out["cost_approved"], out["research_declined"]) == (True, False) and _case(store).pending is None
    out = await confirm.apply_cost({"resume": {"choice": "stop"}, "research_plan": {"key": "plan-1"}},
                                   _runtime(store, pending))  # type: ignore[arg-type]  # fmt: skip
    assert (out["cost_approved"], out["research_declined"]) == (False, True)
    assert _case(store).declined_plan == "plan-1" and store.versions[-1] == ["research declined"]
    out = await confirm.apply_cost({"resume": {"choice": "text", "text": "only specs"}}, _runtime(store, pending))  # type: ignore[arg-type]
    assert (out["route"], out["user_text"]) == ("interpret", "only specs")


def test_routes_after_prepare_and_apply() -> None:
    assert confirm.route_after_prepare({"confirm_payload": {"kind": "cost"}}) == "wait"  # type: ignore[typeddict-item]
    assert confirm.route_after_prepare({}) == "assess"  # type: ignore[typeddict-item]
    assert confirm.route_after_apply({"route": "end"}) == "end"  # type: ignore[typeddict-item]
    assert confirm.route_after_apply({}) == "assess"  # type: ignore[typeddict-item]
