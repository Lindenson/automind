"""The stored pages a relevance keyword change is measured on (spec 011 US5): the pages the relevance rules judged
in a period (only those whose title or address names a moved word), their text, and the references their values
are checked against (gold, else the accepted claims of other families)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

from automind.acquisition.gates.domain.relevance_change import References
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.infrastructure.fetch import decode_body
from automind.acquisition.infrastructure.pages import main_content
from automind.acquisition.replay import run as replay
from automind.acquisition.snapshots import store as snapshots
from automind.acquisition.snapshots.store import SnapshotRef
from automind.shared.infrastructure.db.session import sessionmaker

_JUDGED = """
SELECT pr.variant_id, pr.verdict, pr.reason, pr.created_at, d.title,
       ps.id, ps.url, ps.final_url, ps.domain, ps.fetched_at, ps.content_type, ps.blob_sha256
FROM page_relevance pr
JOIN documents d ON d.id = pr.document_id
JOIN LATERAL (SELECT * FROM page_snapshots s WHERE s.document_id = pr.document_id AND s.replayable
              AND s.blob_sha256 IS NOT NULL ORDER BY s.fetched_at DESC LIMIT 1) ps ON true
WHERE pr.method = 'RULES' AND (pr.created_at >= :since OR ps.fetched_at >= :since) AND pr.created_at <= :until
  {verdicts} {words}
ORDER BY pr.created_at DESC
LIMIT :limit
"""
_REJECTED = "AND pr.verdict IN ('OTHER_VARIANT', 'NOT_ABOUT_CAR')"
_NAMED = ("AND (coalesce(d.title, '') ILIKE ANY(:pats) OR d.url ILIKE ANY(:pats) "
          "OR coalesce(ps.final_url, ps.url) ILIKE ANY(:pats))")  # fmt: skip
_AGREED = text("""
SELECT c.variant_id, c.attribute, c.value_num, e.domain, coalesce(src.family, e.domain)
FROM claims c JOIN evidence e ON e.id = c.evidence_id LEFT JOIN sources src ON src.domain = e.domain
WHERE c.variant_id = ANY(:vids) AND c.status = 'ACCEPTED' AND c.value_num IS NOT NULL
""")  # fmt: skip


@dataclass(frozen=True)
class Judged:
    """A stored relevance verdict and the page it was given on."""

    ref: SnapshotRef
    variant_id: str
    verdict: str
    reason: str
    judged_at: datetime | None = None
    title: str = ""


async def judged(since: datetime, until: datetime, *, words: Sequence[str] = (), rejected_only: bool = False,
                 limit: int = 400) -> list[Judged]:  # fmt: skip
    """Pages judged by the relevance rules in the period (newest first); only those whose title or address names one
    of `words` when given (a keyword change can only move those)."""
    params: dict[str, Any] = {"since": since, "until": until, "limit": limit}
    cond = ""
    if words:
        params["pats"] = [f"%{w.split()[0]}%" for w in words if w.strip()]
        cond = _NAMED
    sql = text(_JUDGED.format(verdicts=_REJECTED if rejected_only else "", words=cond))
    async with sessionmaker()() as s:
        rows = (await s.execute(sql, params)).all()
    return [Judged(SnapshotRef(str(i), str(u), fu, str(dom), at, ct, (str(vid),), str(sha)), str(vid), str(v),
                   str(r or ""), jat, str(t or ""))
            for vid, v, r, jat, t, i, u, fu, dom, at, ct, sha in rows]  # fmt: skip


async def pages_text(refs: Sequence[SnapshotRef]) -> tuple[dict[str, tuple[str, str]], dict[str, bytes]]:
    """snapshot id → (title, main text) of the stored bodies, and the bodies by sha."""
    bodies = await snapshots.load_bodies(sorted({r.blob_sha256 for r in refs}))
    out = {r.id: main_content(decode_body(bodies[r.blob_sha256], None), r.final_url or r.url)
           for r in refs if r.blob_sha256 in bodies}  # fmt: skip
    return out, bodies


async def references(variant_ids: set[str]) -> References:
    """Gold of the versions, and their accepted numeric claims with each source's family."""
    gold = await replay.gold_values(variant_ids)
    claims: dict[tuple[str, str], list[tuple[float, str, str]]] = {}
    if variant_ids:
        async with sessionmaker()() as s:
            for vid, attr, x, dom, fam in (await s.execute(_AGREED, {"vids": sorted(variant_ids)})).all():
                claims.setdefault((str(vid), str(attr)), []).append((float(x), str(dom), str(fam)))
    return References(gold, claims, acq_config.gold_tolerances())
