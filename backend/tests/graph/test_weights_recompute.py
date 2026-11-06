"""Weights change from chat and from the case panel: recomputed from cache, no research, < 5 s (FR-029, SC-009)."""

import json
import time
from pathlib import Path

from automind.chat.dialog.graph import build_graph
from automind.chat.dialog.runner import ChatRunner
from automind.chat.domain.case.casefile import CaseFile
from automind.chat.infrastructure.persistence.repositories import CaseRepo, MessageRepo
from automind.delivery.web.rest import CasePatch, apply_patch
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.golden.runner import load, seed

from .conftest import budget_factory, make_ports

G6 = Path(__file__).resolve().parents[1] / "golden"


def turn(n):
    return json.loads((G6 / "cassettes" / "g6_no_repeat" / f"turn{n}.json").read_text())


def runner(saver, llm):
    return ChatRunner(
        build_graph(saver, tools=[]),
        make_ports(llm=llm, search=FixtureSearch("empty")),
        budget_factory(),
        messages=MessageRepo(),
    )


def weights(result):
    block = next(b for b in result.blocks if b["type"] == "criteria_scores")
    return {c["key"]: c["weight"] for c in block["criteria"]}, block


async def test_status_wish_and_panel_edit_recompute_without_research(saver, chat_id):
    await seed(load(G6 / "g6_no_repeat.yaml"))
    llm = FakeLLM()
    for role, outs in turn(1).items():
        llm.queue(role, *outs)
    r1 = await runner(saver, llm).run_turn(chat_id, "Golf GTI Mk8 vs i30 N for a race enthusiast")
    assert r1.action == "REPORT"
    w1, _ = weights(r1)
    assert "status" not in w1

    llm.queue(
        "interpreter",
        {
            "request": "weights_change",
            "language": "en",
            "delta": {"add_priorities": [{"criterion": "status", "strength": "HIGH"}]},
        },
    )
    llm.queue("answerer", "With status weighted in, the result is shown in the scores.")
    t0 = time.monotonic()
    r2 = await runner(saver, llm).run_turn(chat_id, "if I prefer status, who wins?")
    assert time.monotonic() - t0 < 5
    assert r2.action == "ANSWER_FROM_CONTEXT" and r2.usage["search_calls"] == 0
    w2, block = weights(r2)
    assert w2["status"] > 0 and block["cars"][0]["parts"]["status"]["inputs"] is not None

    # the case panel sets weights explicitly; the next message uses them (FR-009)
    repo = CaseRepo()
    _, data, _ = await repo.latest(chat_id)
    edited, changes = apply_patch(
        CaseFile.model_validate(data), CasePatch(weights={"performance": 1}), current_year=2026
    )
    await repo.save_version(chat_id, edited.model_dump(mode="json"), "user", changes)
    llm.queue("interpreter", {"request": "follow_up_question", "language": "en", "delta": {}})
    llm.queue("answerer", "Now only performance counts.")
    r3 = await runner(saver, llm).run_turn(chat_id, "and now?")
    w3, _ = weights(r3)
    assert w3 == {"performance": 100.0} and r3.usage["search_calls"] == 0


async def test_persona_changed_in_panel_reorders_and_is_not_overwritten(saver, chat_id):
    """V1: the panel sets BUYER; "and now?" keeps it (no re-derivation from history) and reorders the report."""
    await seed(load(G6 / "g6_no_repeat.yaml"))
    llm = FakeLLM()
    for role, outs in turn(1).items():
        llm.queue(role, *outs)
    await runner(saver, llm).run_turn(chat_id, "Golf GTI Mk8 vs i30 N for a race enthusiast")
    repo = CaseRepo()
    _, data, _ = await repo.latest(chat_id)
    edited, changes = apply_patch(CaseFile.model_validate(data), CasePatch(persona="BUYER"), current_year=2026)
    await repo.save_version(chat_id, edited.model_dump(mode="json"), "user", changes)
    # the model tries to re-derive the persona from the first message; code drops it (no words in this message)
    llm.queue(
        "interpreter",
        {
            "request": "follow_up_question",
            "language": "en",
            "persona_evidence": "race enthusiast",
            "delta": {"set_persona": {"persona": "PERFORMANCE", "source": "ASKED"}},
        },
    )
    llm.queue("answerer", "For a buyer: see below.")
    r = await runner(saver, llm).run_turn(chat_id, "and now?")
    _, data, _ = await repo.latest(chat_id)
    assert data["persona"] == "BUYER"
    types = [b["type"] for b in r.blocks if b["type"] != "notice"]
    assert types[:5] == ["verdict", "suggestions", "case_summary", "criteria_scores", "tco"]
    assert r.usage["search_calls"] == 0
