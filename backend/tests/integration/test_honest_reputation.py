"""US3 independent test (spec 011 T074, SC-006): a high-yield source with 30 % wrong values against gold never
becomes active and ranks below an honest one with lower yield; a wrong value whose right number was on the page lowers
the parser's reputation, not the source's; agreement counts once per family; a physics outlier signals against the
outlier's capability.

40 simulated jobs over the stored tables (claims, selections, gold) with `autonomy: true` in this test's config only;
signals come from the worker's `reputation_signals` scan, statuses from the daily review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.fakes.reputation_world import World

from automind.acquisition.domain.thompson import seed_of
from automind.acquisition.registry.api import Attempt
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.wiring import daily_review, registry_service
from automind.acquisition.reputation.infrastructure.component_store import ComponentRepo
from automind.acquisition.reputation.infrastructure.wiring import signal_scan
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.loader import load_yaml

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios" / "honest"
FAST, HONEST, MIRROR_A, MIRROR_B = "fastwrong.example", "honest.example", "mirror-a.example", "mirror-b.example"
GOLD_ATTRS = ("max_power", "curb_mass", "displacement")


def _scenario() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    gold = yaml.safe_load((FIX / "gold.yaml").read_text(encoding="utf-8"))
    pages = {}
    for q in json.loads((FIX / "search.json").read_text(encoding="utf-8"))["queries"]:
        r = q["results"][0]
        domain = q["match"][0].removeprefix("site:")
        pages[domain] = {**r, "template": (FIX / "docs" / r["doc"]).read_text(encoding="utf-8")}
    return gold, pages


def _text(page: dict[str, Any], car: str, values: dict[str, float], extra: dict[str, float]) -> str:
    fmt = {k: (int(v) if float(v).is_integer() else v) for k, v in {**extra, **values}.items()}
    return page["template"].format(car=car, **fmt)


@pytest.fixture
async def world():
    await db.init_db()
    w = World("t074")
    await w.clear_registry()
    yield w
    await w.cleanup()


async def _job(w: World, svc: RegistryService, cfg: dict[str, Any], i: int, gold: dict[str, Any],
               pages: dict[str, dict[str, Any]]) -> tuple[str, dict[str, int]]:  # fmt: skip
    kw, kg, cc = gold["variants"][i]
    truth = {"max_power": kw, "curb_mass": kg, "displacement": cc}
    car = f"V{i:02d}"
    vid = await w.variant(car)
    await w.gold(vid, truth)
    stats: dict[str, int] = {}
    # fastwrong: every job, five values, 30 % of the gold-checked ones off by +25 % (and its page says so)
    stated = {a: (round(v * gold["wrong_factor"]) if (3 * i + j + 1) % 10 in gold["wrong_every"] else v)
              for j, (a, v) in enumerate(truth.items())}  # fmt: skip
    text = _text(pages[FAST], car, stated, gold["extra"])
    claims = [(a, v, f"{a} {v}") for a, v in {**stated, **gold["extra"]}.items()]
    await w.page(vid, FAST, "SPEC_DATABASE", text, claims)
    attempts = [Attempt(domain=FAST, area="specs", market="ES", url=f"https://{FAST}/{car}", outcome="accepted",
                        values=5, job_id=f"job-{i}", variant_id=vid)]  # fmt: skip
    await w.select(vid)
    for k, n in (await signal_scan(cfg, svc).scan([vid], judge=False)).items():
        stats[k] = stats.get(k, 0) + n
    # honest: three jobs in four, every value right; its source type (a publication) outranks a spec database
    if i % gold["honest_skips_every"] != 3:
        await w.page(vid, HONEST, "PUBLICATION", _text(pages[HONEST], car, truth, {}),
                     [(a, v, f"{a}: {v}") for a, v in truth.items()])  # fmt: skip
        attempts.append(Attempt(domain=HONEST, area="specs", market="ES", url=f"https://{HONEST}/{car}",
                                outcome="accepted", values=3, job_id=f"job-{i}", variant_id=vid))  # fmt: skip
    else:
        attempts.append(Attempt(domain=HONEST, area="specs", market="ES", url=f"https://{HONEST}/{car}",
                                outcome="empty", job_id=f"job-{i}", variant_id=vid))  # fmt: skip
    if i == 0:  # two mirrors of one family agree with everyone on the power
        for d in (MIRROR_A, MIRROR_B):
            await w.page(vid, d, "SPEC_DATABASE", _text(pages[d], car, truth, {}), [("max_power", kw, f"Power {kw}")])
    await svc.record(attempts)
    await w.select(vid)
    for k, n in (await signal_scan(cfg, svc).scan([vid], judge=False)).items():
        stats[k] = stats.get(k, 0) + n
    return vid, stats


async def test_fastwrong_never_active_and_ranks_below_honest(world: World) -> None:
    w = world
    gold, pages = _scenario()
    cfg = {**load_yaml("registry.yaml"), "autonomy": True}  # this test only; config/registry.yaml stays false
    assert load_yaml("registry.yaml")["autonomy"] is False
    svc = registry_service(cfg)
    await w.source(FAST, "SPEC_DATABASE")
    await w.source(HONEST, "PUBLICATION")
    for d in (MIRROR_A, MIRROR_B):
        await w.source(d, "SPEC_DATABASE", family="mirrorfam")
    totals: dict[str, int] = {}
    first_vid = ""
    honest_active_at = None
    for i in range(40):
        vid, stats = await _job(w, svc, cfg, i, gold, pages)
        first_vid = first_vid or vid
        for k, n in stats.items():
            totals[k] = totals.get(k, 0) + n
        await daily_review(cfg).run(kind="test", admit_sites=False)
        fast, honest = await w.cap(FAST), await w.cap(HONEST)
        assert fast.status != "active", f"job {i}: fastwrong promoted (acc_lb {fast.acc_lb:.3f})"
        if honest.status == "active" and honest_active_at is None:
            honest_active_at = i
    fast, honest = await w.cap(FAST), await w.cap(HONEST)
    assert honest.status == "active" and honest_active_at is not None and honest_active_at < 20
    assert fast.yield_ > honest.yield_  # the liar answers more often ...
    assert fast.acc_lb < cfg["lifecycle"]["promote"]["min_acc_lb"] < honest.acc_lb  # ... but is wrong more often
    assert fast.score < honest.score
    plan = await svc.plan("specs", ["ES"], None, seed=seed_of("job-final", "specs"))
    order = [p.domain for p in plan.sources]
    assert order.index(HONEST) < order.index(FAST) if FAST in order else HONEST in order
    # 30 % of fastwrong's 120 gold-checked values are wrong, all blamed on the source (its pages say so)
    wrong = [s for s in await w.signals(kind="gold", verdict="wrong") if (s.details or {}).get("domain") == FAST]
    assert len(wrong) == 36 and all(s.blame_vector == {"source": 1.0} for s in wrong)
    assert totals["gold_right"] == 84 + 90 + 2  # fastwrong (84), honest (30 jobs x 3), the two mirrors
    assert totals["replacement"] > 0  # honest's later, more confident values replaced fastwrong's shown ones
    # agreement on job 0's power: fastwrong, honest and the mirror family -> three signals, the mirrors count once
    agree = [s for s in await w.signals(kind="agreement", variant_id=first_vid, attribute="max_power")]
    fams = sorted(str(s.details["family"]) for s in agree)
    assert fams == sorted([FAST, HONEST, "mirrorfam"])
    assert len({s.details["domain"] for s in agree} & {MIRROR_A, MIRROR_B}) == 1
    print("signals over 40 jobs:", dict(sorted(totals.items())))


async def test_parser_blame_and_physics_outlier(world: World) -> None:
    w = world
    gold, _ = _scenario()
    cfg = {**load_yaml("registry.yaml"), "autonomy": True}
    svc = registry_service(cfg)
    await w.source(FAST, "SPEC_DATABASE")
    await svc.record([Attempt(domain=FAST, area="specs", market="ES", url=f"https://{FAST}/x", outcome="accepted")])
    # a wrong value whose right number is on the page: the reader km77@v1 is blamed, not fastwrong
    p = gold["parser_case"]
    vid = await w.variant("P01")
    await w.gold(vid, dict(zip(GOLD_ATTRS, p["variant"], strict=True)))
    page = f"Ficha técnica. {p['excerpt']}. Potencia 110 kW."
    await w.page(vid, FAST, "SPEC_DATABASE", page, [("curb_mass", p["read"], p["excerpt"])], producer="reader",
                 producer_version="km77@v1")  # fmt: skip
    await w.select(vid)
    before = (await w.cap(FAST)).wrong_w
    out = await signal_scan(cfg, svc).scan([vid], judge=False)
    assert out["gold_wrong"] == 1
    assert (await w.cap(FAST)).wrong_w == pytest.approx(before)  # the source is not punished
    rep = await ComponentRepo().get("parser", "km77@v1")
    assert rep is not None and rep.wrong_w == pytest.approx(1.0) and rep.right_w == 0
    (sig,) = await w.signals(kind="gold", variant_id=vid)
    assert sig.blame == "parser" and sig.component == "parser:km77@v1" and sig.capability_id is None
    # a hybrid's engine-only torque next to its system power: a physics signal against fastwrong's capability
    ph = gold["physics_case"]
    hv = await w.variant("H01", powertrain="HEV", fuel="hybrid")
    await w.page(hv, FAST, "SPEC_DATABASE", f"Potencia {ph['max_power']} kW. Par máximo {ph['max_torque']} Nm.",
                 [("max_power", ph["max_power"], f"Potencia {ph['max_power']} kW"),
                  ("max_torque", ph["max_torque"], f"Par máximo {ph['max_torque']} Nm")])  # fmt: skip
    await w.select(hv)
    out = await signal_scan(cfg, svc).scan([hv], judge=False)
    assert out["physics"] == 1
    (phys,) = await w.signals(kind="physics", variant_id=hv)
    assert phys.attribute == "max_torque" and phys.verdict == "wrong"
    assert phys.capability_id == (await w.cap(FAST)).id and phys.details["check"] == "torque_power"
    assert await signal_scan(cfg, svc).scan([hv], judge=False) == {"variants": 1, "disputed": 0}  # once only
