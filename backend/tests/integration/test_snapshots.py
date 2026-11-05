"""Snapshots and producer identity (spec 011 T034, FR-001, FR-002, SC-002)."""

import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, func, select
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.graph.conftest import make_ports, open_web_reference

from automind.acquisition.domain import served
from automind.acquisition.domain.versions import prompt_key_from_header
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.acquisition.snapshots import codec, store
from automind.acquisition.snapshots.retention import run_snapshot_retention
from automind.application import research
from automind.infrastructure import db
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db import models as m
from automind.infrastructure.fetch import Fetcher, FetchPolicy
from automind.infrastructure.pages import DbPageStore
from automind.infrastructure.site_readers import Registry

PAGES = Path(__file__).resolve().parents[1] / "fixtures" / "pages"
KM77 = {"domain": "km77.com", "source_type": "SPEC_DATABASE", "areas": ["specs"], "markets": ["ES"], "priority": 1,
        "reader": "km77", "tos_checked": "2026-11-02"}  # fmt: skip


def _store() -> DbPageStore:
    body = (PAGES / "spec_page.html").read_text(encoding="utf-8")

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path.startswith("/empty"):
            return httpx.Response(200, html="<html><body><div id=app></div><script>x()</script></body></html>")
        return httpx.Response(200, html=body)

    f = Fetcher(FetchPolicy(min_interval_per_host_s=0.0), httpx.AsyncClient(transport=httpx.MockTransport(h)))
    return DbPageStore(f)


async def _snapshots(*urls: str) -> list[m.PageSnapshot]:
    async with db.sessionmaker()() as s:
        q = select(m.PageSnapshot).where(m.PageSnapshot.url.in_(urls)).order_by(m.PageSnapshot.fetched_at)
        return list((await s.execute(q)).scalars())


async def _blobs(sha: str) -> int:
    async with db.sessionmaker()() as s:
        return int((await s.execute(select(func.count()).where(m.SnapshotBlob.sha256 == sha))).scalar_one())


async def test_fetch_writes_snapshot_and_blob_cache_hit_writes_nothing():
    await db.init_db()
    tag = db.uid()[:8]
    a, b, empty = (f"https://snap-{tag}.example/{p}" for p in ("a", "b", "empty"))
    ps = _store()
    page = await ps.get(a, area="specs")
    assert page is not None and page.snapshot_id
    (snap,) = await _snapshots(a)
    assert snap.id == page.snapshot_id and snap.status == "OK" and snap.replayable and snap.document_id
    assert snap.retention_class == "plain" and snap.keep_until is not None and snap.domain == f"snap-{tag}.example"
    raw, _url = await store.load(snap.id)
    assert raw == (PAGES / "spec_page.html").read_bytes() and codec.sha256(raw) == snap.blob_sha256
    assert await _blobs(snap.blob_sha256) == 1

    again = await ps.get(a, area="specs")  # cache hit: no new snapshot, the last fetch's snapshot is named
    assert again is not None and again.from_cache and again.snapshot_id == snap.id
    assert len(await _snapshots(a)) == 1

    other = await ps.get(b, area="specs")  # the same body under another URL: a new snapshot, the same blob
    assert other is not None
    (snap_b,) = await _snapshots(b)
    assert snap_b.blob_sha256 == snap.blob_sha256 and await _blobs(snap.blob_sha256) == 1

    assert await ps.get(empty, area="specs") is None  # JavaScript-only page: metadata only
    (snap_e,) = await _snapshots(empty)
    assert snap_e.status == "NO_CONTENT" and not snap_e.replayable and snap_e.blob_sha256 is None


class SnapshottingSearch(FixtureSearch):
    """The fixture page store, writing a snapshot for every page like the real page store."""

    async def get(self, url, *, area=None):  # noqa: ANN001
        p = await super().get(url, area=area)
        if p is None:
            return None
        sid = await store.write(url, url, (p.html or p.text).encode(), "text/html", 200, "OK", None)
        return dataclasses.replace(p, snapshot_id=sid)


class ServedLLM(FakeLLM):
    """A fake model that, like the gateway, says which model and prompt version answered."""

    async def structured(self, role, schema, system, user):  # noqa: ANN001
        served.begin(role)
        out = await super().structured(role, schema, system, user)
        name, version = prompt_key_from_header(system) or (role, None)
        served.record(served.ServedCall(role, "fake:served-model", name, f"v{version}" if version else None, "h"))
        return out


def _extractor(system, user):  # noqa: ANN001
    claim = {"attribute": "max_power", "raw_value": "190", "unit": "CV", "excerpt": "190 CV", "scope": "VARIANT"}
    return {"is_about_variant": True, "claims": [claim]}


async def _purge(ids: list[str]) -> None:
    async with db.sessionmaker()() as s:
        for t in (m.SpecValue, m.Claim, m.ResearchRun, m.PageRelevance, m.GoldValueRow):
            await s.execute(delete(t).where(t.variant_id.in_(ids)))
        await s.execute(delete(m.Evidence).where(m.Evidence.variant_id.in_(ids)))
        await s.execute(delete(m.Variant).where(m.Variant.id.in_(ids)))
        await s.commit()


async def _bmw() -> str:
    """A BMW 520d of its own (the bmw520 pages are about a BMW); removed again by the test."""
    async with db.sessionmaker()() as s:
        v = m.Variant(canonical_key=f"bmw|5 series|g30|520d 190 cv|ice|snap-{db.uid()}", make="BMW", model="5 Series",
                      generation="G30", variant_name="520d 190 CV", powertrain="ICE", body_class="SEDAN",
                      generation_years_from=2017, generation_years_to=2023)  # fmt: skip
        s.add(v)
        await s.commit()
        return v.id


async def test_research_job_names_producer_version_model_and_snapshot():
    await db.init_db()
    vid = await _bmw()
    llm = ServedLLM()
    llm.responders["extractor"] = _extractor
    llm.responders["validator"] = lambda s, u: {"verdicts": [{"index": 0, "verdict": "SAME_VARIANT"}]}
    fx = SnapshottingSearch("bmw520")
    ports = make_ports(llm=llm, search=fx)
    ports.ref = open_web_reference(
        favourites=[KM77], favourite_queries={"specs": "{make} {model} {generation} {variant} {sites}"}
    )
    ports.readers = Registry(load_yaml("site_readers.yaml"), [KM77])
    cfg = {**load_yaml("registry.yaml"), "autonomy": False}
    ports.registry = RegistryService(RegistryRepo(cfg), cfg)

    async def emit(stage: str, text: str) -> None:
        return None

    try:
        await _check_job(ports, vid, emit)
    finally:
        await _purge([vid])


async def _check_job(ports, vid, emit):  # noqa: ANN001
    res = await research.run_job(ports, research.JobSpec(job_id=db.uid(), variant_id=vid, area="specs"), emit)
    assert res.ok, res.error
    async with db.sessionmaker()() as s:
        claims = list((await s.execute(select(m.Claim).where(m.Claim.variant_id == vid))).scalars())
        attempts = list(
            (await s.execute(select(m.RegistryAttempt).where(m.RegistryAttempt.variant_id == vid))).scalars()
        )
    readers = [c for c in claims if c.producer == "reader"]
    extracted = [c for c in claims if c.producer == "extractor"]
    assert readers and all(c.producer_version == "km77@v1" and c.model is None for c in readers)
    assert extracted and all(c.producer_version == "extract_specs@v2" for c in extracted)
    assert all(c.model == "fake:served-model" for c in extracted)
    assert all(c.snapshot_id for c in claims)  # SC-002: every value names its stored page
    assert attempts and all(a.snapshot_id for a in attempts)
    km77 = [a for a in attempts if "km77.com" in (a.url or "")]
    assert km77 and all(a.producer_version == "km77@v1" for a in km77 if a.outcome == "accepted")
    accepted = [a.snapshot_id for a in attempts if a.outcome == "accepted"]
    async with db.sessionmaker()() as s:
        snaps = list((await s.execute(select(m.PageSnapshot).where(m.PageSnapshot.id.in_(accepted)))).scalars())
    assert snaps and all(x.retention_class == "accepted" and vid in x.variant_ids for x in snaps)
    assert all(x.keep_until - x.fetched_at >= timedelta(days=179) for x in snaps)


@pytest.mark.parametrize("cap_bytes", [0])
async def test_retention_honours_the_cap_and_never_drops_pinned(cap_bytes):
    await db.init_db()
    tag = db.uid()[:8]
    now = datetime.now(UTC)
    ids = []
    for i, cls in enumerate(("plain", "accepted", "pinned")):
        sid = await store.write(f"https://ret-{tag}.example/{i}", None, f"<html>{tag}{i}</html>".encode() * 50,
                                "text/html", 200, "OK", None)  # fmt: skip
        ids.append(sid)
        async with db.sessionmaker()() as s:
            row = await s.get(m.PageSnapshot, sid)
            row.retention_class = cls
            row.keep_until = None if cls == "pinned" else now + timedelta(days=30)
            await s.commit()
    cfg = codec.RetentionCfg(max_bytes=cap_bytes)
    await run_snapshot_retention(cfg, now=now)
    async with db.sessionmaker()() as s:
        left = {
            r.id: r.retention_class
            for r in (await s.execute(select(m.PageSnapshot).where(m.PageSnapshot.id.in_(ids)))).scalars()
        }
        used = select(m.PageSnapshot.blob_sha256).where(m.PageSnapshot.blob_sha256.is_not(None))
        orphans = (await s.execute(select(func.count()).where(m.SnapshotBlob.sha256.not_in(used)))).scalar_one()
    assert "plain" not in left.values() and "pinned" in left.values()  # over the cap: plain goes, pinned stays
    assert "accepted" in left.values()  # accepted pages younger than 180 days stay
    assert orphans == 0
    async with db.sessionmaker()() as s:
        await s.execute(delete(m.PageSnapshot).where(m.PageSnapshot.id.in_(ids)))
        await s.commit()
