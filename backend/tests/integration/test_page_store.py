"""Page store (spec 003 T016): main content with tables, PDF text, no-content pages, cache, refusals."""

from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete

from automind.acquisition.infrastructure.fetch import Fetcher, FetchPolicy
from automind.acquisition.infrastructure.pages import DbPageStore, url_hash
from automind.shared.infrastructure import db

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "pages"
URLS = ["https://pages.example/spec", "https://pages.example/list.pdf", "https://pages.example/empty",
        "https://www.coches.net/x", "https://pages.example/again"]  # fmt: skip


def store(seen):
    def h(req):
        seen.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path.endswith(".pdf"):
            return httpx.Response(200, content=(FIX / "price_list.pdf").read_bytes(),
                                  headers={"content-type": "application/pdf"})  # fmt: skip
        if req.url.path == "/empty":
            return httpx.Response(200, html="<html><body><div id=app></div><script>x()</script></body></html>")
        return httpx.Response(200, html=(FIX / "spec_page.html").read_text(encoding="utf-8"))

    f = Fetcher(FetchPolicy(min_interval_per_host_s=0.0), httpx.AsyncClient(transport=httpx.MockTransport(h)))
    return DbPageStore(f)


@pytest.fixture
async def clean():
    await db.init_db()
    async with db.sessionmaker()() as s:
        await s.execute(delete(db.Document).where(db.Document.url_hash.in_([url_hash(u) for u in URLS])))
        await s.commit()


async def test_main_content_keeps_table_and_drops_boilerplate(clean):
    p = await store([]).get(URLS[0], area="specs")
    assert p is not None and not p.from_cache and p.reader == "main_content"
    assert "Potencia máxima" in p.text and "140 kW" in p.text
    assert "Publicidad" not in p.text and "política de privacidad" not in p.text
    assert p.html and p.document_id


async def test_pdf_text(clean):
    p = await store([]).get(URLS[1], area="price")
    # tiny fixture: below the content minimum → stored as NO_CONTENT; the text extraction itself works
    from automind.acquisition.infrastructure.pages import pdf_text

    assert "58.900" in pdf_text((FIX / "price_list.pdf").read_bytes())
    assert p is None


async def test_javascript_only_page_is_no_content(clean):
    s = store([])
    assert await s.get(URLS[2]) is None
    assert "no content" in s.last_reason(URLS[2])


async def test_second_get_is_served_from_cache_without_request(clean):
    seen = []
    s = store(seen)
    await s.get(URLS[4], area="specs")
    n = len(seen)
    p = await s.get(URLS[4], area="specs")
    assert p is not None and p.from_cache and len(seen) == n


async def test_refused_url_is_stored_with_reason(clean):
    seen = []
    s = store(seen)
    assert await s.get(URLS[3]) is None
    assert "deny-list" in s.last_reason(URLS[3]) and seen == []
    async with db.sessionmaker()() as sess:
        from sqlalchemy import select

        row = (await sess.execute(select(db.Document).where(db.Document.url_hash == url_hash(URLS[3])))).scalar_one()
        assert row.status == "REFUSED"
