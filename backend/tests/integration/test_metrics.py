"""Research metrics for the operator (spec 003 T034, FR-017)."""

from automind.infrastructure import db
from automind.infrastructure.db.repositories import MetricsRepo


async def test_metrics_aggregate_jobs_and_search_calls():
    await db.init_db()
    before = await MetricsRepo().research(1)
    async with db.sessionmaker()() as s:
        v = db.Variant(canonical_key=f"metricsmake|m|{db.uid()}", make="MetricsMake", model="M", variant_name="x",
                       powertrain="ICE")  # fmt: skip
        s.add(v)
        await s.flush()
        s.add(db.ResearchJob(chat_id="metrics", turn_id="metrics", variant_id=v.id, area="specs", status="DONE",
                             started_at=db.now(), accepted=5, rejected=2, pages_found=9, pages_cached=3,
                             pages_rejected={"other_variant": 2}, values_rejected={"implausible": 1},
                             reader_values=4, search_cost_eur=0.004))  # fmt: skip
        s.add(db.SearchCall(chat_id="metrics", turn_id="metrics", kind="search", provider="serper", cost_eur=0.001))
        s.add(db.SearchCall(chat_id="metrics", turn_id="metrics", kind="search", provider="serper", cost_eur=0,
                            cached=True))  # fmt: skip
        await s.commit()
    after = await MetricsRepo().research(1)
    a, b = before["areas"].get("specs", {}), after["areas"]["specs"]
    assert b["jobs"] == a.get("jobs", 0) + 1
    assert b["pages_rejected"]["other_variant"] >= 2 and b["reader_values"] >= 4
    assert after["search"]["cache_hits"] == before["search"]["cache_hits"] + 1
    assert after["search"]["paid_calls"] == before["search"]["paid_calls"] + 1
