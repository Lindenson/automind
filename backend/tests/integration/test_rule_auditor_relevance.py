"""The "manuales" class of mistake fixed by the engine itself (spec 011 US5 gap): automatic BMW 5 Series pages whose
title says "manual del vehículo" (the owner's manual, not a gearbox) were rejected by the relevance rule "other
gearbox: manual"; two other families later confirmed the values those pages write. The rule auditor clusters them,
the role suggests the stop phrase, code checks it, the replay gate re-runs the relevance stage on the stored pages
(flipped pages, their values against gold, junk pages that must stay rejected), the shadow gate on the pages judged
after, and the change is accepted and journalled in one sentence. A proposal that would accept junk pages (pages of
another engine that do name a manual gearbox) is rejected at replay. Real Postgres, stored snapshots, km77 reader
offline, fake model."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select, update
from tests.fakes.fake_llm import FakeLLM

from automind.acquisition.agents import rule_auditor
from automind.acquisition.agents.levers import RuleProposal
from automind.acquisition.domain import relevance as rel
from automind.acquisition.gates.infrastructure.wiring import change_journal, replay_gate, shadow_gate
from automind.acquisition.gold import repo
from automind.acquisition.gold.domain.match import GoldValue
from automind.acquisition.infrastructure import overrides
from automind.acquisition.parsing import migrate_v1
from automind.acquisition.snapshots import store
from automind.shared.infrastructure import db

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "html" / "km77_three"
HTML = {c: (FIX / f"car_{c}.html").read_text(encoding="utf-8") for c in "abc"}
CARS = {"520d": ("a", 140.0, 400.0, 1615.0, 1995.0), "530d": ("b", 195.0, 620.0, 1735.0, 2993.0),
        "520i": ("c", 135.0, 290.0, 1540.0, 1998.0)}  # fmt: skip
UNITS = {"max_power": "kW", "max_torque": "N·m", "curb_mass": "kg", "displacement": "cm3"}
TOL = {"max_power": ("rel", 0.02), "max_torque": ("rel", 0.03), "curb_mass": ("rel", 0.03), "displacement": ("abs", 10)}
PATH = "relevance.keywords.not_manual"
PHRASE = "manual del vehículo"
TAG = "ra-manuales"


def _page(car: str, title: str) -> bytes:
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", HTML[car], count=1, flags=re.S)
    return html.encode("utf-8")


class Corpus:
    def __init__(self) -> None:
        self.vids: dict[str, str] = {}
        self.docs: list[str] = []
        self.sids: list[str] = []

    async def page(self, vid: str, car: str, title: str, at: datetime, verdict: str, reason: str) -> str:
        """A km77 page fetched and judged by the relevance rules at `at` (stored snapshot + page_relevance)."""
        url = f"https://www.km77.com/coches/bmw/serie-5/2017/{TAG}-{db.uid()[:8]}/datos"
        async with db.sessionmaker()() as s:
            doc = db.Document(url=url, title=title, text="", url_hash=db.uid().replace("-", "") * 2)
            s.add(doc)
            await s.flush()
            s.add(db.PageRelevance(document_id=doc.id, variant_id=vid, verdict=verdict, reason=reason,
                                   method="RULES", created_at=at))  # fmt: skip
            await s.commit()
        self.docs.append(doc.id)
        sid = await store.write(url, url, _page(car, title), "text/html", 200, "OK", doc.id)
        await store.mark(sid, 0, vid)
        async with db.sessionmaker()() as s:
            await s.execute(update(db.PageSnapshot).where(db.PageSnapshot.id == sid).values(fetched_at=at))
            await s.commit()
        self.sids.append(sid)
        return sid

    async def confirmed(self, vid: str, values: dict[str, float], at: datetime) -> None:
        """Two other families accept the variant's values after the rejection."""
        for dom in ("ra-spec-a.example", "ra-spec-b.example"):
            url = f"https://{dom}/{TAG}/{db.uid()[:8]}"
            async with db.sessionmaker()() as s:
                doc = db.Document(url=url, title=dom, text="x", url_hash=db.uid().replace("-", "") * 2)
                s.add(doc)
                await s.flush()
                self.docs.append(doc.id)
                e = db.Evidence(variant_id=vid, document_id=doc.id, url=url, source_name=dom, domain=dom,
                                source_type="SPEC_DATABASE")  # fmt: skip
                s.add(e)
                await s.flush()
                for a, x in values.items():
                    s.add(db.Claim(variant_id=vid, evidence_id=e.id, attribute=a, raw_value=str(x), raw_unit=UNITS[a],
                                   value_num=x, excerpt=f"{a} {x}", provenance="SOURCED_FACT", status="ACCEPTED",
                                   created_at=at))  # fmt: skip
                await s.commit()


REJECT = ("OTHER_VARIANT", "other gearbox: manual (wanted automatic)")


@pytest.fixture
async def world():
    """Automatic 520d/530d/520i (G30) with gold; 2 days ago: 4 pages "… manual del vehículo" rejected (their values
    later confirmed by 2 families) and 3 junk pages "520d manual 6 velocidades" carrying 520i values, rejected."""
    await db.init_db()
    await migrate_v1.seed()
    overrides.clear()
    started = datetime.now(UTC)
    w = Corpus()
    await repo.upsert_dataset(repo.DatasetInfo(repo.REFERENCE_SET, "Reference vehicles", "reference_set", "internal"))
    for name, (_, kw, nm, kg, cc) in CARS.items():
        async with db.sessionmaker()() as s:
            v = db.Variant(canonical_key=f"{TAG}|bmw|{name}|{db.uid()}", make="BMW", model="Serie 5", generation="G30",
                           variant_name=name, powertrain="ICE", fuel="diesel" if name.endswith("d") else "petrol",
                           transmission="automatic", generation_years_from=2017, generation_years_to=2023)  # fmt: skip
            s.add(v)
            await s.commit()
        w.vids[name] = v.id
        vals = {"max_power": kw, "max_torque": nm, "curb_mass": kg, "displacement": cc}
        await repo.replace(repo.REFERENCE_SET, v.id, [
            GoldValue(variant_id=v.id, attribute=a, value_num=x, unit=UNITS[a], tolerance=TOL[a][1],
                      tolerance_kind=TOL[a][0], origin="reference_set", match_rule="reference_set", confidence="HIGH",
                      dataset_id=repo.REFERENCE_SET) for a, x in vals.items()])  # fmt: skip
    judged = started - timedelta(days=2)
    for i, name in enumerate(("520d", "530d", "520i", "520d")):
        car = CARS[name][0]
        await w.page(w.vids[name], car, f"BMW Serie 5 G30 {name} Manual del vehículo | km77.com",
                     judged + timedelta(minutes=i), *REJECT)  # fmt: skip
    for i in range(3):  # junk: a manual 520i page filed under the automatic 520d — rejecting it was right
        await w.page(w.vids["520d"], "c", f"BMW Serie 5 G30 520d manual 6 velocidades ({i + 1}) | km77.com",
                     judged + timedelta(minutes=10 + i), *REJECT)  # fmt: skip
    for name, (_, kw, nm, kg, cc) in CARS.items():
        await w.confirmed(w.vids[name], {"max_power": kw, "max_torque": nm, "curb_mass": kg, "displacement": cc},
                          judged + timedelta(hours=6))  # fmt: skip
    yield w, started
    rule_auditor.LLM_OVERRIDE = None
    overrides.clear()
    async with db.sessionmaker()() as s:
        ids = list(w.vids.values())
        await s.execute(delete(db.AcqChange).where(db.AcqChange.object_key == PATH,
                                                   db.AcqChange.created_at >= started))  # fmt: skip
        await s.execute(delete(db.RuleOverride).where(db.RuleOverride.path == PATH,
                                                      db.RuleOverride.created_at >= started))  # fmt: skip
        await s.execute(delete(db.AcqTask).where(db.AcqTask.kind.in_(("gate_replay", "gate_shadow")),
                                                 db.AcqTask.created_at >= started))  # fmt: skip
        await s.execute(delete(db.PageSnapshot).where(db.PageSnapshot.id.in_(w.sids)))
        await s.execute(delete(db.PageRelevance).where(db.PageRelevance.variant_id.in_(ids)))
        await s.execute(delete(db.Claim).where(db.Claim.variant_id.in_(ids)))
        await s.execute(delete(db.Evidence).where(db.Evidence.variant_id.in_(ids)))
        await s.execute(delete(db.Document).where(db.Document.id.in_(w.docs)))
        await s.execute(delete(db.GoldValueRow).where(db.GoldValueRow.variant_id.in_(ids)))
        await s.execute(delete(db.Variant).where(db.Variant.id.in_(ids)))
        await s.commit()


def _auditor_answer(phrase: str):
    def respond(system: str, user: str) -> dict:
        m = re.search(r"Rule path: (\S+)", user)
        if m and m.group(1) == PATH:
            return {"path": PATH, "value": [phrase],
                    "explanation": "the pages are owner's manuals of automatic cars, not manual gearboxes"}  # fmt: skip
        return {"path": "x", "value": 0, "explanation": "no"}  # other clusters of the shared database: refused

    return respond


async def test_manuales_cluster_stop_phrase_passes_replay_and_shadow_and_is_accepted(world) -> None:
    w, started = world
    llm = FakeLLM()
    llm.responders["rule_auditor"] = _auditor_answer(PHRASE)
    out = await rule_auditor.run_auditor(llm=llm, now=started)
    mine = [p for p in out["proposed"] if p["path"] == PATH]
    assert mine and mine[0].get("change_id"), out
    assert mine[0]["value"] == [PHRASE]
    cluster = next(c for c in out["relevance_clusters"] if c["path"] == PATH)
    assert (cluster["rule"], cluster["word"]) == ("gearbox.manual", "manual") and cluster["pages"] == 4
    call = next(c for c in llm.calls if f"Rule path: {PATH}" in c.user)
    assert "manual del vehículo" in call.user.split("<untrusted_document", 1)[1].lower()
    cid = mine[0]["change_id"]

    rep = await replay_gate().run(cid, llm=FakeLLM(), now=started)
    assert rep["verdict"] == "pass", rep
    r = rep["relevance"]
    assert r["flipped"] == 4 and r["values_checked"] >= 16 and r["values_right"] == r["values_checked"], r
    assert (r["correct_rejections"], r["junk_accepted"]) == (3, 0), r
    c = await change_journal().load(cid)
    assert c is not None and c.status == "shadow"
    assert rel.KEYWORDS.get("not_manual") is None  # nothing in force before acceptance

    # the next pages the relevance rules reject live, during the shadow (the user still sees the old verdicts)
    live = started + timedelta(hours=1)
    for i, name in enumerate(("530d", "520i", "520d")):
        await w.page(w.vids[name], CARS[name][0], f"BMW Serie 5 G30 {name} manual del vehículo (pdf) | km77.com",
                     live + timedelta(minutes=i), *REJECT)  # fmt: skip
    sh = await shadow_gate().run(cid, llm=FakeLLM(), now=started + timedelta(days=4))
    assert sh["verdict"] == "pass", sh
    c = await change_journal().load(cid)
    assert c is not None and c.status == "watch"
    async with db.sessionmaker()() as s:
        active = (await s.execute(select(db.RuleOverride).where(db.RuleOverride.change_id == cid))).scalar_one()
    assert active.status == "active" and active.value == [PHRASE]
    assert rel.KEYWORDS["not_manual"] == (PHRASE,)  # in force for the relevance stage
    assert re.match(rf"rule {PATH} none→{PHRASE}: 4 pages rejected as \"other gearbox: manual", c.explanation)
    assert "replay flips 4/7 rejected pages to relevant" in c.explanation
    assert "junk accepted 0/3" in c.explanation


async def test_a_stop_word_that_accepts_junk_pages_is_rejected_at_replay(world) -> None:
    _, started = world
    # proposed as if it had come through the auditor: strip every "manual" from titles
    cid = await change_journal().propose("rule_auditor", RuleProposal(path=PATH, value=["manual"]), "relevance cluster",
                                {"trigger": "test: the bare word", "as_of": started.isoformat()})  # fmt: skip
    assert cid is not None
    rep = await replay_gate().run(cid, llm=FakeLLM(), now=started)
    assert rep["verdict"] == "fail", rep
    r = rep["relevance"]
    assert r["flipped"] == 7 and r["junk_accepted"] == 3 and r["correct_rejections"] == 3, r
    c = await change_journal().load(cid)
    assert c is not None and c.status == "rejected" and c.closed_at is not None
    assert "junk acceptance 3/3 correct rejections flipped" in c.explanation
    async with db.sessionmaker()() as s:
        cand = (await s.execute(select(db.RuleOverride).where(db.RuleOverride.change_id == cid))).scalar_one()
    assert cand.status == "rejected"


async def test_the_auditor_refuses_a_bare_word_or_a_phrase_not_on_the_pages(world) -> None:
    _, started = world
    for phrase, why in (("manual", "2 to 4 words"), ("manual de la radio", "occurs on 0")):
        llm = FakeLLM()
        llm.responders["rule_auditor"] = _auditor_answer(phrase)
        out = await rule_auditor.run_auditor(llm=llm, now=started)
        (mine,) = [p for p in out["proposed"] if p["path"] == PATH]
        assert "change_id" not in mine and why in mine["refused"], mine
