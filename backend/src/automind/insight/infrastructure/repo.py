"""Failures from the journals and the issue table (spec 010 US3, research R6).

Reads only. The one table it writes is `insight_issues` (and `insight_runs`): diagnosis never touches code,
configuration, prompts or parsers (FR-010).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from automind.infrastructure.db.models import InsightIssue, InsightRun, now
from automind.infrastructure.db.session import sessionmaker
from automind.insight.domain.clusters import Failure, Group

WINDOW_DAYS = 30
COMPONENT_OF = {
    "not_understood": "dialogue",
    "wrong_car": "wrong_car",
    "bad_text": "report",
    "process_failure": "process",
    "too_costly": "cost",
}
TITLES = {
    "dialogue": "Users had to rephrase or correct",
    "wrong_car": "Wrong car or version",
    "report": "Bad answer text (guard removed sentences or the user complained)",
    "process": "Turns failed (error, timeout, provider)",
    "cost": "Turns hit the budget",
    "nodata": "No data",
    "data": "Values shown wrong",
    "check": "A check rejects values other sources confirm",
    "relevance": "Pages rejected as not about the car",
    "parser": "A site reader reads fewer pages",
    "model": "Model calls answered by a fallback model",
}


def title_of(key: str) -> str:
    parts = key.split("/")
    rest = " / ".join(p for p in parts[2:] if p)
    return f"{TITLES.get(parts[0], parts[0])}" + (f": {rest}" if rest else "")


async def _rows(sql: str, **p: Any) -> list[Any]:
    async with sessionmaker()() as s:
        return list((await s.execute(text(sql), p)).all())


async def failures(cfg: Mapping[str, Any], at: datetime | None = None) -> list[Failure]:
    t = at or now()
    since = t - timedelta(days=WINDOW_DAYS)
    out: list[Failure] = []
    # dialogue, wrong car, text, process, cost, no data — from turn outcomes
    for chat, turn, created, kind, lang, classes, sig, said in await _rows(
        "SELECT o.chat_id, o.turn_id, o.created_at, coalesce(o.request_kind,'unknown'), coalesce(o.language,'?'), "
        "o.failure_classes, o.signals, m.text FROM turn_outcomes o LEFT JOIN turns t ON t.id = o.turn_id "
        "LEFT JOIN chat_messages m ON m.id = t.user_message_id "
        "WHERE o.created_at >= :since AND jsonb_array_length(o.failure_classes) > 0",
        since=since,
    ):
        for cls in classes or []:
            if cls in COMPONENT_OF:
                comp = COMPONENT_OF[cls]
                out.append(Failure(comp, cls, f"{comp}/{cls}/{kind}/{lang}", created, chat, turn, said))
        if "no_data" in (classes or []):
            for area in sorted({i.get("area") for i in (sig or {}).get("nodata_items") or [] if i.get("area")}):
                out.append(Failure("nodata", "no_data", f"nodata/no_data/{area}", created, chat, turn, said))
    # values shown wrong — from feedback ("wrong?" that corrected or removed, "bad source")
    for chat, turn, created, kind, attr, area, domain, url, claim, txt in await _rows(
        "SELECT chat_id, turn_id, created_at, kind, attribute, area, domain, url, claim_id, text FROM feedback "
        "WHERE created_at >= :since AND (kind = 'bad_source' OR (kind = 'wrong_value' AND outcome IN "
        "('CORRECTED','REMOVED')))",
        since=since,
    ):
        what = attr or area or "value"
        key = f"data/wrong_data/{what}" + (f"/{domain}" if kind == "bad_source" and domain else "")
        out.append(Failure("data", "wrong_data", key, created, chat, turn, txt, url, claim))
    # a check rejected a value that another source later confirmed (within 10 %)
    for created, rule, attr, excerpt, url, claim in await _rows(
        "SELECT r.created_at, r.reject_rule, r.attribute, r.excerpt, e.url, r.id FROM claims r "
        "JOIN evidence e ON e.id = r.evidence_id WHERE r.created_at >= :since AND r.status LIKE 'REJECTED%' "
        "AND r.reject_rule IS NOT NULL AND r.value_num IS NOT NULL AND EXISTS (SELECT 1 FROM claims a "
        "JOIN evidence ea ON ea.id = a.evidence_id WHERE a.variant_id = r.variant_id AND a.attribute = r.attribute "
        "AND a.status = 'ACCEPTED' AND ea.domain <> e.domain AND a.value_num IS NOT NULL "
        "AND abs(a.value_num - r.value_num) <= 0.1 * greatest(abs(a.value_num), 1))",
        since=since,
    ):
        out.append(Failure("check", str(rule), f"check/{rule}/{attr}", created, None, None, excerpt, url, claim))
    # pages rejected by the rule-based relevance check, grouped by reason
    for created, verdict, reason, url in await _rows(
        "SELECT p.created_at, p.verdict, p.reason, d.url FROM page_relevance p "
        "JOIN documents d ON d.id = p.document_id "
        "WHERE p.created_at >= :since AND p.method = 'RULES' AND p.verdict IN ('OTHER_VARIANT','NOT_ABOUT_CAR')",
        since=since,
    ):
        short = (reason or "").split(":")[0].strip()[:60] or "no reason"
        out.append(
            Failure(
                "relevance",
                str(verdict).lower(),
                f"relevance/{str(verdict).lower()}/{short}",
                created,
                None,
                None,
                reason,
                url,
            )
        )
    out += await _parser_failures(cfg, t)
    out += await _model_failures(cfg, t)
    return out


async def _parser_failures(cfg: Mapping[str, Any], t: datetime) -> list[Failure]:
    drop = float(cfg.get("parser_drop", 0.2))
    stats: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"7": [0, 0], "30": [0, 0]})
    for domain, day, ok, failed in await _rows(
        "SELECT domain, day, ok, failed FROM site_reader_stats WHERE day >= :since",
        since=(t - timedelta(days=30)).date(),
    ):
        recent = day >= (t - timedelta(days=7)).date()
        for w in ("7", "30") if recent else ("30",):
            stats[domain][w][0] += int(ok)
            stats[domain][w][1] += int(ok) + int(failed)
    out: list[Failure] = []
    for domain, s in stats.items():
        (ok7, n7), (ok30, n30) = s["7"], s["30"]
        if n7 >= 3 and n30 > n7 and ok7 / n7 < ok30 / n30 - drop:
            for _ in range(n7 - ok7):
                out.append(
                    Failure(
                        "parser", "drop", f"parser/drop/{domain}", t, quote=f"7d ok {ok7}/{n7}, 30d ok {ok30}/{n30}"
                    )
                )
    return out


async def _model_failures(cfg: Mapping[str, Any], t: datetime) -> list[Failure]:
    share = float(cfg.get("model_fallback_share", 0.2))
    out: list[Failure] = []
    for role, fb, n in await _rows(
        "SELECT role, sum(CASE WHEN fallback THEN 1 ELSE 0 END), count(*) FROM llm_calls WHERE created_at >= :since "
        "GROUP BY 1",
        since=t - timedelta(days=7),
    ):
        if n and int(fb or 0) / int(n) > share:
            q = f"{int(fb)} of {int(n)} calls answered by a fallback model in 7 days"
            out.append(Failure("model", "fallback", f"model/fallback/{role}", t, quote=q))
    return out


class IssueRepo:
    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self.cfg = cfg

    async def upsert(self, groups: list[Group], impacts: Mapping[str, float]) -> tuple[int, int]:
        """(new issues, reopened as regression). Status rules of data-model.md; wontfix never reopens."""
        new = reopened = 0
        regress = int(self.cfg.get("regression_after_fix", 2))
        async with sessionmaker()() as s:
            for g in groups:
                row = (
                    await s.execute(select(InsightIssue).where(InsightIssue.fingerprint == g.fingerprint))
                ).scalar_one_or_none()
                if row is None:
                    s.add(
                        InsightIssue(
                            fingerprint=g.fingerprint,
                            component=g.component,
                            klass=g.klass,
                            key=g.key,
                            title=title_of(g.key)[:200],
                            count_total=g.count_total,
                            count_7d=g.count_7d,
                            chats_7d=g.chats_7d,
                            impact=impacts.get(g.key, 0.0),
                            first_seen=g.first_seen,
                            last_seen=g.last_seen,
                            examples=g.examples,
                            status="open",
                            status_history=[{"at": now().isoformat(), "status": "open", "by": "system"}],
                        )
                    )
                    new += 1
                    continue
                row.count_total, row.count_7d, row.chats_7d = g.count_total, g.count_7d, g.chats_7d
                row.impact, row.last_seen, row.examples = impacts.get(g.key, 0.0), g.last_seen, g.examples
                if row.status == "fixed" and row.fixed_at is not None:
                    after = sum(1 for e in g.examples if e.get("at") and e["at"] > row.fixed_at.isoformat())
                    if after >= regress:
                        row.status = "regression"
                        row.status_history = [
                            *row.status_history,
                            {
                                "at": now().isoformat(),
                                "status": "regression",
                                "by": "system",
                                "failures_after_fix": after,
                            },
                        ]
                        row.diagnosis, row.diagnosed_at = None, None  # diagnose again with the new examples
                        reopened += 1
            await s.commit()
        return new, reopened

    async def to_diagnose(self, limit: int) -> list[InsightIssue]:
        async with sessionmaker()() as s:
            q = (
                select(InsightIssue)
                .where(InsightIssue.diagnosis.is_(None), InsightIssue.status.in_(("open", "regression")))
                .order_by(InsightIssue.impact.desc())
                .limit(limit)
            )
            return list((await s.execute(q)).scalars())

    async def set_diagnosis(self, issue_id: str, diagnosis: dict[str, Any]) -> None:
        async with sessionmaker()() as s:
            row = await s.get(InsightIssue, issue_id)
            if row is not None:
                row.diagnosis, row.diagnosed_at = diagnosis, now()
                await s.commit()

    async def start_run(self, kind: str) -> str:
        async with sessionmaker()() as s:
            r = InsightRun(kind=kind)
            s.add(r)
            await s.commit()
            return r.id

    async def finish_run(self, run_id: str, **fields: Any) -> None:
        async with sessionmaker()() as s:
            r = await s.get(InsightRun, run_id)
            if r is not None:
                for k, v in fields.items():
                    setattr(r, k, v)
                r.finished_at = now()
                await s.commit()

    async def last_run(self) -> datetime | None:
        async with sessionmaker()() as s:
            q = select(InsightRun.started_at).where(InsightRun.error.is_(None)).order_by(InsightRun.started_at.desc())
            return (await s.execute(q.limit(1))).scalar_one_or_none()

    async def spent_today(self, since: datetime) -> float:
        rows = await _rows("SELECT coalesce(sum(cost_eur),0) FROM insight_runs WHERE started_at >= :s", s=since)
        return float(rows[0][0] or 0)

    async def new_failures_since(self, since: datetime) -> int:
        rows = await _rows(
            "SELECT (SELECT count(*) FROM turn_outcomes WHERE updated_at >= :s AND "
            "jsonb_array_length(failure_classes) > 0) + (SELECT count(*) FROM feedback WHERE created_at >= :s)",
            s=since,
        )
        return int(rows[0][0] or 0)
