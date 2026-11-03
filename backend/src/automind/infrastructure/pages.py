"""Page store (spec 003 FR-005, FR-007, FR-008; research R3, R4).

Cache-first: a page fetched within its lifetime (the research area's freshness) is served from
`documents` without any request. Otherwise it is fetched under the fetch policy (deny-list, robots incl.
Crawl-delay, rate and size limits), reduced to its main content (HTML → markdown with tables kept,
PDF → text) and stored with its status. Refused and empty pages are stored too, with the reason, so
they are not retried on every turn.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from automind.application.ports import Page
from automind.domain.research_plan import FRESHNESS_DAYS
from automind.infrastructure.db import Document, sessionmaker, uid
from automind.infrastructure.fetch import Fetcher, FetchPolicy, FetchRefused, RawPage, html_to_text

log = logging.getLogger(__name__)

MIN_CONTENT_CHARS = 400
MAX_STORED_CHARS = 60_000
PDF_MAX_PAGES = 30
REFUSED_TTL = timedelta(days=30)
ERROR_TTL = timedelta(hours=6)


def normalise_url(url: str) -> str:
    u = urlsplit(url.strip())
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path or "/", u.query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalise_url(url).encode()).hexdigest()


def pdf_text(body: bytes) -> str:
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(io.BytesIO(body))
    parts = []
    for page in reader.pages[:PDF_MAX_PAGES]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one broken page never fails the document
            continue
    return "\n".join(p.strip() for p in parts if p.strip())


def main_content(html: str, url: str) -> tuple[str, str]:
    """(title, text): trafilatura main content as markdown with tables; falls back to plain text."""
    title, plain = html_to_text(html)
    try:
        import trafilatura  # noqa: PLC0415

        text = trafilatura.extract(
            html, url=url, include_tables=True, include_comments=False, output_format="markdown", favor_recall=True
        )
        meta = trafilatura.extract_metadata(html)
        if meta is not None and meta.title:
            title = meta.title
    except Exception:  # noqa: BLE001 - a parser failure falls back to the simple converter
        text = None
    if not text or len(text) < MIN_CONTENT_CHARS <= len(plain):
        text = plain
    return title.strip(), text.strip()


def _expiry(area: str | None, now: datetime) -> datetime:
    return now + timedelta(days=FRESHNESS_DAYS.get(area or "", 30))


class DbPageStore:
    def __init__(self, fetcher: Fetcher | None = None, policy: FetchPolicy | None = None) -> None:
        self.fetcher = fetcher or Fetcher(policy or FetchPolicy())
        self._reasons: dict[str, str] = {}

    def last_reason(self, url: str) -> str | None:
        return self._reasons.get(url)

    async def _store(self, url: str, **values: object) -> str:
        h = url_hash(url)
        now = datetime.now(UTC)
        row = {"url": url, "url_hash": h, "retrieved_at": now, "fetched_at": now, **values}
        async with sessionmaker()() as s:
            stmt = insert(Document).values(id=uid(), **row)
            stmt = stmt.on_conflict_do_update(index_elements=["url_hash"], set_={k: v for k, v in row.items()})
            res = await s.execute(stmt.returning(Document.id))
            await s.commit()
            return str(res.scalar_one())

    async def get(self, url: str, *, area: str | None = None) -> Page | None:
        now = datetime.now(UTC)
        async with sessionmaker()() as s:
            row = (await s.execute(select(Document).where(Document.url_hash == url_hash(url)))).scalar_one_or_none()
        if row is not None and row.expires_at is not None and row.expires_at > now:
            if row.status != "OK":
                self._reasons[url] = row.fail_reason or row.status
                return None
            return Page(url=row.final_url or row.url, title=row.title or url, text=row.text,
                        content_type=row.content_type or "text/html", reader=row.reader or "main_content",
                        fetched_at=row.fetched_at, from_cache=True, document_id=row.id)  # fmt: skip
        try:
            raw = await self.fetcher.fetch_raw(url)
        except FetchRefused as e:
            self._reasons[url] = e.reason
            # 429/5xx after the retries: remembered briefly like network errors, not for a month
            status, ttl = ("ERROR", ERROR_TTL) if e.transient else ("REFUSED", REFUSED_TTL)
            await self._store(url, title=None, text="", status=status, fail_reason=e.reason,
                              expires_at=now + ttl)  # fmt: skip
            return None
        except Exception as e:  # noqa: BLE001 - network errors: remember briefly, never fail the job
            self._reasons[url] = f"{type(e).__name__}"
            await self._store(url, title=None, text="", status="ERROR", fail_reason=type(e).__name__,
                              expires_at=now + ERROR_TTL)  # fmt: skip
            return None
        return await self._from_raw(url, raw, area, now)

    async def _from_raw(self, url: str, raw: RawPage, area: str | None, now: datetime) -> Page | None:
        html: str | None = None
        if raw.content_type == "application/pdf":
            title, text, reader = url.rsplit("/", 1)[-1], pdf_text(raw.body), "pdf"
        elif raw.content_type == "text/html":
            html = raw.text()
            (title, text), reader = main_content(html, raw.url), "main_content"
        else:
            title, text, reader = url, raw.text(), "text"
        text = text[:MAX_STORED_CHARS]
        common = {"final_url": raw.url, "content_type": raw.content_type, "bytes": len(raw.body), "reader": reader,
                  "content_sha256": hashlib.sha256(text.encode()).hexdigest()}  # fmt: skip
        if len(text) < MIN_CONTENT_CHARS:
            self._reasons[url] = "no content (page needs JavaScript or is empty)"
            await self._store(url, title=title, text=text, status="NO_CONTENT", fail_reason=self._reasons[url],
                              expires_at=now + REFUSED_TTL, **common)  # fmt: skip
            return None
        doc_id = await self._store(url, title=title, text=text, status="OK", fail_reason=None,
                                   expires_at=_expiry(area, now), **common)  # fmt: skip
        return Page(url=raw.url, title=title or url, text=text, content_type=raw.content_type, reader=reader,
                    fetched_at=now, from_cache=False, html=html, document_id=doc_id)  # fmt: skip
