"""Spec 007 US3 (FR-012 to FR-014): an edit in the panel after a report recomputes it at once from the validated
data: no search, no interpreter, one short text about what changed, changed scores marked."""

import time

from automind.api.rest import CasePatch, apply_patch
from automind.domain.casefile import CaseFile
from automind.infrastructure.db.repositories import CaseRepo
from tests.fakes.fake_llm import FakeLLM
from tests.golden.runner import load, seed

from .test_weights_recompute import G6, runner, turn, weights


async def _reported(saver, chat_id, llm):
    await seed(load(G6 / "g6_no_repeat.yaml"))
    for role, outs in turn(1).items():
        llm.queue(role, *outs)
    r1 = await runner(saver, llm).run_turn(chat_id, "Golf GTI Mk8 vs i30 N for a race enthusiast")
    assert r1.action == "REPORT"
    return r1


async def _patch(chat_id, patch):
    repo = CaseRepo()
    _, data, _ = await repo.latest(chat_id)
    edited, changes = apply_patch(CaseFile.model_validate(data), patch, current_year=2026)
    await repo.save_version(chat_id, edited.model_dump(mode="json"), "user", changes)
    return changes


async def test_panel_persona_change_rescores_without_search_or_interpreter(saver, chat_id):
    llm = FakeLLM()
    r1 = await _reported(saver, chat_id, llm)
    w1, _ = weights(r1)
    changes = await _patch(chat_id, CasePatch(persona="BUYER"))
    llm.queue("reporter", "For a family buyer reliability and cost now weigh most.")
    interpreter_before = [c.role for c in llm.calls].count("interpreter")
    t0 = time.monotonic()
    r = await runner(saver, llm).run_turn(chat_id, "↻ " + "; ".join(changes), preset={"kind": "rescore",
                                                                                    "changes": changes})  # fmt: skip
    assert time.monotonic() - t0 < 2.5
    assert r.action == "REPORT" and r.usage["search_calls"] == 0
    assert [c.role for c in llm.calls].count("interpreter") == interpreter_before
    w2, block = weights(r)
    assert w2 != w1 and w2.get("reliability", 0) > w1.get("reliability", 0)
    assert any("delta" in c for c in block["criteria"])  # the weight changes are marked
    assert all("delta" in car for car in block["cars"] if car.get("total") is not None)


async def test_rescore_with_nothing_changed_is_nothing_new(saver, chat_id):
    llm = FakeLLM()
    await _reported(saver, chat_id, llm)
    llm.queue("answerer", "Nothing changed.")
    r = await runner(saver, llm).run_turn(chat_id, "↻", preset={"kind": "rescore", "changes": []})
    assert r.action == "ANSWER_FROM_CONTEXT" and r.usage["search_calls"] == 0
