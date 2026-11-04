"""Market incentives (spec 006 US5, quickstart D): stored once per market with evidence, reused by every car
for 30 days, status from the dates, only active subsidies with an amount reduce the break-even."""

from datetime import date, timedelta

from sqlalchemy import delete

from automind.application import incentives_research as ir
from automind.application.extraction import IncentiveEntry, IncentiveFacts
from automind.application.ports import WebDoc
from automind.domain import research_plan
from automind.infrastructure import db
from automind.infrastructure.db.repositories import MarketFactRepo

TEXT = ("El Plan MOVES III ofrece hasta 7.000 euros por la compra de un turismo eléctrico, con solicitudes hasta "
        "el 31 de diciembre de 2026. La deducción del 15 % en el IRPF se aplica hasta el 31 de diciembre de 2025. "
        "El Plan Auto+ andaluz suma 1.500 euros.")  # fmt: skip
DOC = WebDoc(
    url="https://www.idae.es/ayudas-y-financiacion/moves-iii", title="IDAE MOVES III", text=TEXT, snippet_only=False
)


def facts() -> IncentiveFacts:
    return IncentiveFacts(facts=[
        IncentiveEntry(key="subsidy.purchase", label="Plan MOVES III", amount_eur=7000, valid_to="2026-12-31",
                       excerpt="El Plan MOVES III ofrece hasta 7.000 euros por la compra de un turismo eléctrico"),
        IncentiveEntry(key="irpf.ev_deduction", label="Deducción IRPF", percent=15, valid_to="2025-12-31",
                       excerpt="La deducción del 15 % en el IRPF se aplica hasta el 31 de diciembre de 2025"),
        IncentiveEntry(key="subsidy.region", label="Plan Auto+", amount_eur=1500, scope="regional",
                       region_code="AN", valid_to="2026-12-31", excerpt="El Plan Auto+ andaluz suma 1.500 euros."),
        IncentiveEntry(key="charger.subsidy", label="Wallbox", amount_eur=900,  # the amount is not in the excerpt
                       excerpt="El Plan MOVES III ofrece hasta 7.000 euros por la compra"),
    ])  # fmt: skip


async def test_stored_once_reused_and_viewed():
    await db.init_db()
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.MarketFact).where(db.MarketFact.market == "ES"))
        await s.execute(delete(db.ResearchRun).where(db.ResearchRun.area == "incentives"))
        await s.commit()
    eid = db.uid()
    repo = MarketFactRepo()
    rows, rejected = ir.accept(facts(), DOC)
    assert (len(rows), rejected) == (3, 1)
    await repo.upsert(rows, eid)
    await repo.upsert(rows, eid)  # the same page again: updated, not doubled
    when = await repo.done()
    rows = await repo.load()
    assert sorted(r["key"] for r in rows) == ["irpf.ev_deduction", "subsidy.purchase", "subsidy.region.AN"]

    # a second chat with another car within 30 days: the market is fresh, no job
    assert when is not None
    last = {"other-variant": {"incentives": when}}
    cars = [research_plan.CarToPlan("a", "other-variant", "NEW", electrified=True)]
    p = research_plan.plan(cars, persona="BUYER", criteria=[], depth="STANDARD", last_done=last,
                           now=when + timedelta(days=10))  # fmt: skip
    assert not [j for j in p.jobs if j.area == "incentives"]
    p = research_plan.plan(cars, persona="BUYER", criteria=[], depth="STANDARD", last_done=last,
                           now=when + timedelta(days=31))  # fmt: skip
    assert [j.area for j in p.jobs].count("incentives") == 1

    seville = ir.view(rows, date(2026, 11, 4), "AN", "BEV")
    status = {i["key"]: i["status"] for i in seville}
    assert status == {"subsidy.purchase": "ACTIVE", "subsidy.region.AN": "ACTIVE", "irpf.ev_deduction": "EXPIRED"}
    assert ir.subsidy(seville) == 8500  # the expired deduction and the percent never count
    madrid = ir.view(rows, date(2026, 11, 4), "MD", "BEV")
    assert ir.subsidy(madrid) == 7000 and all(i["key"] != "subsidy.region.AN" for i in madrid)
    assert ir.subsidy(ir.view(rows, date(2027, 1, 2), "AN", "BEV")) == 0  # after the deadline: expired
