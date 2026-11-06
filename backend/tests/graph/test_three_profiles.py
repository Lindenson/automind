"""Spec 007 SC-005 (US4, FR-016 to FR-019): the same pair and the same data, three different people. The period,
the km, the limits and the persona change the verdict, and the verdict card says why — all from code."""

from automind.chat.domain.case.casefile import RunningLimit
from automind.delivery.web.rest import CasePatch, ProfilePatch
from tests.fakes.fake_llm import FakeLLM

from .test_rescore import _patch, _reported
from .test_weights_recompute import runner

PROFILES = {
    "racer": CasePatch(persona="PERFORMANCE", ownership_years=3, profile=ProfilePatch(driving_style="SPORTY")),
    "family": CasePatch(persona="BUYER", ownership_years=8, annual_km=20000,
                        profile=ProfilePatch(family="FAMILY", driving_style="CALM")),
    # €180 a month: one of the two fits (fixture at 12,000 km: about €172 and €194 a month to run at the
    # October 2026 fuel price in config/energy.yaml)
    "used_buyer": CasePatch(persona="BUYER", ownership_years=5, annual_km=12000,
                            profile=ProfilePatch(family="SINGLE", driving_style="MIXED"),
                            running_cost_limit=RunningLimit(amount_eur=180, period="MONTH")),
}  # fmt: skip


def _block(r, kind):
    return next(b for b in r.blocks if b.get("type") == kind)


def _key(v):
    return (v["pick_car_id"], v["tie"], v["best_if_budget"])


async def test_three_profiles_same_data(saver, chat_id):
    llm = FakeLLM()
    await _reported(saver, chat_id, llm)
    out = {}
    for name, patch in PROFILES.items():
        changes = await _patch(chat_id, patch)
        llm.queue("reporter", f"Text for the {name}.")
        r = await runner(saver, llm).run_turn(chat_id, "↻ edit", preset={"kind": "rescore", "changes": changes})
        assert r.usage["search_calls"] == 0  # same data: no search
        out[name] = (_block(r, "verdict"), _block(r, "tco"), r)
    racer, family, used = (out[n] for n in PROFILES)
    # the ownership cost covers each person's period and km
    assert (racer[1]["years"], family[1]["years"], used[1]["years"]) == (3, 8, 5)
    assert family[1]["annual_km"] == 20000 and used[1]["annual_km"] == 12000
    assert "8 years" in family[1]["title"]
    # at least two of the three verdicts differ
    assert len({_key(v) for v, _, _ in out.values()}) >= 2
    # each verdict card names the profile reason, with the user's numbers
    assert any("you plan 3" in n for n in racer[0]["profile_notes"])
    assert any("you plan 8" in n or "Over your 8 years" in n for n in family[0]["profile_notes"])
    assert any("over your limit of €180" in n for n in used[0]["profile_notes"])
    # the writer receives the profile facts to lead with
    focus = used[2].facts["profile_focus"] if hasattr(used[2], "facts") else None
    if focus is not None:
        assert focus["ownership_years"] == 5 and focus["top_criteria"]
