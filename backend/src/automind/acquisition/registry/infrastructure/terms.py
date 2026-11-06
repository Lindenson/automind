"""Facts for the admission check (spec 010 US7, FR-019): robots for a sample page, readable content, and the
terms of use read by the `terms_reader` web reader (no tools; its quote must occur on the page)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from automind.acquisition.infrastructure.config import fetch_policy
from automind.acquisition.infrastructure.fetch import Fetcher, FetchPolicy, FetchRefused
from automind.acquisition.registry.domain.admission import AdmissionFacts
from automind.shared.evidence import evidence as ev
from automind.shared.infrastructure.llm import gateway as llm_gateway

log = logging.getLogger(__name__)
PROMPT = Path(__file__).parents[1] / "prompts" / "terms_reader.md"
TERMS_PATHS = (
    "/terms",
    "/terms-of-use",
    "/terms-and-conditions",
    "/legal",
    "/legal-notice",
    "/aviso-legal",
    "/condiciones",
    "/condiciones-de-uso",
    "/impressum",
    "/nutzungsbedingungen",
    "/agb",
    "/mentions-legales",
    "/cgu",
    "/condizioni-d-uso",
    "/note-legali",
)
LEGAL_WORDS = (
    "terms",
    "conditions",
    "legal",
    "aviso",
    "condiciones",
    "impressum",
    "nutzungsbedingungen",
    "mentions",
    "condizioni",
    "agb",
)


class TermsVerdict(BaseModel):
    forbids_automated: bool
    clause: str = ""


def _fetcher() -> Fetcher:
    return Fetcher(FetchPolicy.from_config(fetch_policy()))


async def _get(f: Fetcher, url: str) -> tuple[str, str] | None:
    try:
        d = await f.fetch(url)
        return d.title or "", d.text or ""
    except FetchRefused as e:
        if "robots" in str(e):
            raise
        return None
    except Exception:  # noqa: BLE001 - a missing page is not a verdict
        return None


async def facts(domain: str, sample_url: str | None = None, llm: Any = None) -> AdmissionFacts:
    f = _fetcher()
    robots: bool | None = None
    title, chars = "", None
    try:
        page = await _get(f, sample_url or f"https://{domain}/")
        robots = True
        if page is not None:
            title, chars = page[0], len(page[1])
    except FetchRefused:
        robots = False
    terms_forbid: bool | None = None
    clause = terms_url = None
    if robots is not False:
        for path in TERMS_PATHS:
            url = f"https://{domain}{path}"
            try:
                got = await _get(f, url)
            except FetchRefused:
                continue
            if got is None or len(got[1]) < 300 or not any(w in (got[0] + got[1][:400]).lower() for w in LEGAL_WORDS):
                continue
            terms_url = url
            try:
                v = await (llm or llm_gateway).structured(
                    "terms_reader", TermsVerdict, PROMPT.read_text(encoding="utf-8"), got[1][:20000]
                )
            except Exception:  # noqa: BLE001 - no verdict: stays unknown
                log.exception("registry.terms_reader_failed domain=%s", domain)
                break
            if v.forbids_automated and v.clause and ev.occurs(v.clause, got[1]):
                terms_forbid, clause = True, v.clause
            else:
                terms_forbid = False  # no clause, or a quote that is not on the page: not proof of a prohibition
            break
        else:
            terms_forbid = False  # no terms page found at the usual places: nothing forbids it
    if f.client is not None:
        await f.aclose()
    return AdmissionFacts(domain, robots, terms_forbid, clause, terms_url, chars, title)
