"""Repositories for the conversation tables (chats, case files, turns, events, jobs, usage).

They implement the application ports (application/ports.py). Each method opens its own short
session, so callers never hold a transaction across LLM or web calls.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Unpack
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

from automind.chat.application.ports import (
    JobChanges,
    JobRecord,
    MessageRecord,
    TurnBusy,
    TurnChanges,
    TurnRecord,
    VersionConflict,
)
from automind.chat.domain.assessment.metrics import intake_summary
from automind.chat.domain.turn import FINAL, OPEN, JobStatus, Role, TurnStatus
from automind.chat.infrastructure.persistence.errors import store_errors
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.models import (
    CaseFileRow,
    Chat,
    ChatMessage,
    Claim,
    DeletedChat,
    FeasibilityCheck,
    Feedback,
    IntakeEvent,
    LLMCall,
    ReportRating,
    ResearchJob,
    ResearchRun,
    SearchCall,
    Simulation,
    SiteReaderStat,
    TcoEstimateRow,
    Turn,
    TurnEvent,
    TurnOutcome,
    ValueChallenge,
    now,
    uid,
)
from automind.shared.infrastructure.db.session import sessionmaker


class ChatRepo:
    CHAT_SCOPED = (ChatMessage, CaseFileRow, TurnEvent, ResearchJob, LLMCall, SearchCall, FeasibilityCheck,
                   ReportRating, ValueChallenge, IntakeEvent, TurnOutcome, Feedback)  # fmt: skip

    async def is_deleted(self, chat_id: str) -> bool:
        async with sessionmaker()() as s:
            return await s.get(DeletedChat, chat_id) is not None

    async def delete(self, chat_id: str) -> dict[str, int]:
        """Hard-delete everything scoped to the chat in one transaction and leave a tombstone (FR-028, FR-030).
        Shared knowledge (catalog, documents, evidence, claims, selected values, research runs) stays (FR-029)."""
        counts: dict[str, int] = {}
        async with sessionmaker()() as s:
            turn_ids = select(Turn.id).where(Turn.chat_id == chat_id).scalar_subquery()
            for model in (TcoEstimateRow, Simulation):
                res = await s.execute(delete(model).where(model.turn_id.in_(turn_ids)))
                counts[model.__tablename__] = res.rowcount or 0
            for model in self.CHAT_SCOPED:
                res = await s.execute(delete(model).where(model.chat_id == chat_id))
                counts[model.__tablename__] = res.rowcount or 0
            for model, col in ((Turn, Turn.chat_id), (Chat, Chat.id)):
                res = await s.execute(delete(model).where(col == chat_id))
                counts[model.__tablename__] = res.rowcount or 0
            existed = counts["chats"] > 0 or any(counts.values())
            if existed and await s.get(DeletedChat, chat_id) is None:
                s.add(DeletedChat(chat_id=chat_id, counts=counts))
            await s.commit()
        return counts if existed else {}

    async def owns(self, chat_id: str, owner: str | None) -> bool:
        """May this owner open the chat? A chat not created yet: yes (it is created with this owner). A chat from
        before owners existed: claimed by the first owner that opens it. No owner (isolation off): yes."""
        if owner is None:
            return True
        async with sessionmaker()() as s:
            chat = await s.get(Chat, chat_id)
            if chat is None:
                return True
            if chat.owner is None:
                await s.execute(update(Chat).where(Chat.id == chat_id, Chat.owner.is_(None)).values(owner=owner))
                await s.commit()
                await s.refresh(chat)
            return chat.owner == owner

    async def ensure(self, chat_id: str, title: str | None = None, owner: str | None = None) -> Chat:
        async with sessionmaker()() as s:
            chat = await s.get(Chat, chat_id)
            if chat is None:
                chat = Chat(id=chat_id, title=(title or "New chat")[:60], owner=owner)
                s.add(chat)
                try:
                    await s.commit()
                except IntegrityError:  # created concurrently
                    await s.rollback()
                    chat = await s.get(Chat, chat_id)
                    assert chat is not None
            return chat

    async def title_from_first_message(self, chat_id: str, text: str) -> None:
        """Set the title from the first user message (≤60 chars); bump updated_at otherwise."""
        title = " ".join(text.split())
        title = title if len(title) <= 60 else title[:57].rstrip() + "…"
        async with sessionmaker()() as s:
            await s.execute(
                update(Chat).where(Chat.id == chat_id, Chat.title == "New chat").values(title=title, updated_at=now())
            )
            await s.execute(update(Chat).where(Chat.id == chat_id).values(updated_at=now()))
            await s.commit()

    async def claim_unowned(self, owner: str) -> int:
        """Chats from before owners existed go to the first browser that lists chats after the upgrade."""
        async with sessionmaker()() as s:
            res = await s.execute(update(Chat).where(Chat.owner.is_(None)).values(owner=owner))
            await s.commit()
            return res.rowcount or 0

    async def list(self, limit: int = 100, owner: str | None = None) -> list[Chat]:
        """Newest first; with an owner, only that owner's chats."""
        q = select(Chat).order_by(Chat.updated_at.desc()).limit(limit)
        if owner is not None:
            q = q.where(Chat.owner == owner)
        async with sessionmaker()() as s:
            return list((await s.execute(q)).scalars())


class CaseRepo:
    @store_errors
    async def latest(self, chat_id: str) -> tuple[int, dict[str, Any] | None, str | None]:
        """(version, data, changed_by); version 0 and data None when the chat has no case yet."""
        async with sessionmaker()() as s:
            row = (
                await s.execute(
                    select(CaseFileRow)
                    .where(CaseFileRow.chat_id == chat_id)
                    .order_by(CaseFileRow.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return 0, None, None
            return row.version, dict(row.data), row.changed_by

    @store_errors
    async def get(self, chat_id: str, version: int) -> dict[str, Any] | None:
        async with sessionmaker()() as s:
            row = await s.get(CaseFileRow, (chat_id, version))
            return dict(row.data) if row else None

    @store_errors
    async def save_version(self, chat_id: str, data: dict[str, Any], changed_by: str, change_log: list[str]) -> int:
        """Append a new version (optimistic: the PK (chat_id, version) rejects a concurrent writer)."""
        async with sessionmaker()() as s:
            current = (
                await s.execute(select(func.max(CaseFileRow.version)).where(CaseFileRow.chat_id == chat_id))
            ).scalar()
            version = int(current or 0) + 1
            s.add(
                CaseFileRow(chat_id=chat_id, version=version, data=data, changed_by=changed_by, change_log=change_log)
            )
            await s.commit()
            return version

    @store_errors
    async def save_if_idle(
        self, chat_id: str, data: dict[str, Any], changed_by: str, change_log: list[str], *, expected_version: int
    ) -> int:
        """A panel edit (spec 007 J, T076): under the same per-chat lock as a turn start, so no turn can start
        between the read and the write. Raises TurnBusy when a turn runs (the edit is queued and applied after
        it) and VersionConflict when the case moved on since `expected_version` (re-read and apply again)."""
        async with sessionmaker()() as s:
            await s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"turns:{chat_id}"})
            running = await s.execute(
                select(Turn.id).where(Turn.chat_id == chat_id, Turn.status == TurnStatus.RUNNING).limit(1)
            )
            if running.scalar_one_or_none() is not None:
                raise TurnBusy("a turn is running in this chat")
            current = int(
                (await s.execute(select(func.max(CaseFileRow.version)).where(CaseFileRow.chat_id == chat_id))).scalar()
                or 0
            )
            if current != expected_version:
                raise VersionConflict(current)
            s.add(CaseFileRow(chat_id=chat_id, version=current + 1, data=data, changed_by=changed_by,
                              change_log=change_log))  # fmt: skip
            await s.commit()
            return current + 1


_JOB_FINAL = frozenset({JobStatus.DONE, JobStatus.FAILED, JobStatus.SKIPPED})


class TurnRepo:
    @store_errors
    async def start(self, chat_id: str, user_message_id: str | None, case_version: int) -> TurnRecord:
        async with sessionmaker()() as s:
            # two tabs / a double click: the check and the insert happen under one per-chat lock (reviewer 2026-11-03)
            await s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"turns:{chat_id}"})
            running = await s.execute(
                select(Turn.id).where(Turn.chat_id == chat_id, Turn.status == TurnStatus.RUNNING).limit(1)
            )
            if running.scalar_one_or_none() is not None:
                raise TurnBusy("a turn is already running in this chat")  # also the unique index (migration 0009)
            seq = (await s.execute(select(func.max(Turn.seq)).where(Turn.chat_id == chat_id))).scalar()
            turn = Turn(
                id=uid(),
                chat_id=chat_id,
                seq=int(seq or 0) + 1,
                user_message_id=user_message_id,
                case_version_before=case_version,
                status=TurnStatus.RUNNING,
            )
            s.add(turn)
            try:
                await s.commit()
            except IntegrityError as e:  # uq_turns_one_running_per_chat
                raise TurnBusy("a turn is already running in this chat") from e
            return _turn(turn)

    @store_errors
    async def get(self, turn_id: str) -> TurnRecord | None:
        async with sessionmaker()() as s:
            row = await s.get(Turn, turn_id)
            return _turn(row) if row is not None else None

    @store_errors
    async def spent_today(self, exclude_turn: str | None = None, tz: str = "Europe/Madrid") -> float:
        """€ spent since local midnight across all chats (model and search calls), without the given turn."""
        start = datetime.now(ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0)
        total = 0.0
        async with sessionmaker()() as s:
            for model in (LLMCall, SearchCall):
                q = select(func.coalesce(func.sum(model.cost_eur), 0)).where(model.created_at >= start)
                if exclude_turn:
                    q = q.where(or_(model.turn_id.is_(None), model.turn_id != exclude_turn))
                total += float((await s.execute(q)).scalar() or 0)
        return round(total, 4)

    @store_errors
    async def update(self, turn_id: str, **changes: Unpack[TurnChanges]) -> None:
        values: dict[str, object] = dict(changes)
        if changes.get("status") in FINAL:
            values["finished_at"] = now()
        async with sessionmaker()() as s:
            await s.execute(update(Turn).where(Turn.id == turn_id).values(**values))
            await s.commit()

    @store_errors
    async def active(self, chat_id: str) -> TurnRecord | None:
        """The turn that is RUNNING or WAITING_CONFIRMATION, if any."""
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(Turn)
                .where(Turn.chat_id == chat_id, Turn.status.in_(list(OPEN)))
                .order_by(Turn.seq.desc())
                .limit(1)
            )
            row = rows.scalar_one_or_none()
            return _turn(row) if row is not None else None

    @store_errors
    async def last_report_fingerprint(self, chat_id: str) -> str | None:
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(Turn.fingerprint)
                .where(Turn.chat_id == chat_id, Turn.action == "REPORT", Turn.status == TurnStatus.DONE)
                .order_by(Turn.seq.desc())
                .limit(1)
            )
            return rows.scalar_one_or_none()

    @store_errors
    async def running(self) -> list[TurnRecord]:
        async with sessionmaker()() as s:
            rows = await s.execute(select(Turn).where(Turn.status == TurnStatus.RUNNING))
            return [_turn(t) for t in rows.scalars()]


class EventRepo:
    @store_errors
    async def append(self, chat_id: str, turn_id: str | None, type_: str, payload: dict[str, Any]) -> int:
        """Persist an event with the next per-chat seq. Concurrent writers of one chat are serialised by a
        transaction-scoped advisory lock, so parallel research jobs never collide on the seq."""
        async with sessionmaker()() as s:
            await s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"events:{chat_id}"})
            seq = (await s.execute(select(func.max(TurnEvent.seq)).where(TurnEvent.chat_id == chat_id))).scalar()
            nxt = int(seq or 0) + 1
            s.add(TurnEvent(chat_id=chat_id, seq=nxt, turn_id=turn_id, type=type_, payload=payload))
            await s.commit()
            return nxt

    @store_errors
    async def since(self, chat_id: str, after_seq: int) -> list[TurnEvent]:
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(TurnEvent).where(TurnEvent.chat_id == chat_id, TurnEvent.seq > after_seq).order_by(TurnEvent.seq)
            )
            return list(rows.scalars())


async def latest_event(chat_id: str, turn_id: str, type_: str) -> TurnEvent | None:
    async with sessionmaker()() as s:
        rows = await s.execute(
            select(TurnEvent)
            .where(TurnEvent.chat_id == chat_id, TurnEvent.turn_id == turn_id, TurnEvent.type == type_)
            .order_by(TurnEvent.seq.desc())
            .limit(1)
        )
        return rows.scalar_one_or_none()


class JobRepo:
    @store_errors
    async def create(self, chat_id: str, turn_id: str, variant_id: str, area: str, round_: int) -> JobRecord:
        async with sessionmaker()() as s:
            job = ResearchJob(
                id=uid(), chat_id=chat_id, turn_id=turn_id, variant_id=variant_id, area=area, round=round_
            )
            s.add(job)
            await s.commit()
            return _job(job)

    @store_errors
    async def get(self, job_id: str) -> JobRecord | None:
        async with sessionmaker()() as s:
            row = await s.get(ResearchJob, job_id)
            return _job(row) if row is not None else None

    @store_errors
    async def for_turn(self, turn_id: str) -> list[JobRecord]:
        async with sessionmaker()() as s:
            rows = await s.execute(select(ResearchJob).where(ResearchJob.turn_id == turn_id))
            return [_job(j) for j in rows.scalars()]

    @store_errors
    async def skip_open(self, turn_id: str, reason: str = "cancelled") -> int:
        """Mark PENDING/RUNNING jobs of a turn as SKIPPED (cancel). Returns how many."""
        async with sessionmaker()() as s:
            res = await s.execute(
                update(ResearchJob)
                .where(ResearchJob.turn_id == turn_id, ResearchJob.status.in_((JobStatus.PENDING, JobStatus.RUNNING)))
                .values(status=JobStatus.SKIPPED, error=reason, finished_at=now())
            )
            await s.commit()
            return int(res.rowcount or 0)

    @store_errors
    async def mark(self, job_id: str, status: JobStatus, **changes: Unpack[JobChanges]) -> None:
        values: dict[str, object] = dict(changes)
        if status == JobStatus.RUNNING:
            values.setdefault("started_at", now())
            values["attempts"] = ResearchJob.attempts + 1
        if status in _JOB_FINAL:
            values.setdefault("finished_at", now())
        async with sessionmaker()() as s:
            await s.execute(update(ResearchJob).where(ResearchJob.id == job_id).values(status=status, **values))
            await s.commit()


class MessageRepo:
    @store_errors
    async def history(self, chat_id: str) -> list[MessageRecord]:
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(ChatMessage.created_at)
            )
            return [_message(m) for m in rows.scalars()]

    @store_errors
    async def save(
        self,
        chat_id: str,
        role: Role,
        text: str,
        blocks: list[JsonObject] | None = None,
        *,
        message_id: str | None = None,
        turn_id: str | None = None,
    ) -> MessageRecord:
        async with sessionmaker()() as s:
            m = ChatMessage(
                id=message_id or uid(), chat_id=chat_id, turn_id=turn_id, role=role, text=text, blocks=blocks or []
            )
            s.add(m)
            await s.commit()
            return _message(m)


class MetricsRepo:
    """Operator metrics for research quality (spec 003 FR-017, FR-031)."""

    async def research(self, days: int = 7) -> dict[str, Any]:
        since = now() - timedelta(days=days)
        async with sessionmaker()() as s:
            jobs = (await s.execute(select(ResearchJob).where(ResearchJob.started_at >= since))).scalars().all()
            runs = (await s.execute(select(ResearchRun).where(ResearchRun.completed_at >= since))).scalars().all()
            calls = (await s.execute(select(SearchCall).where(SearchCall.created_at >= since))).scalars().all()
            sites = (await s.execute(select(SiteReaderStat).where(SiteReaderStat.day >= since.date()))).scalars().all()
            sense_rows = (
                await s.execute(
                    select(Claim.reject_rule, func.count())
                    .where(Claim.created_at >= since, Claim.reject_rule.like("sense.%"))
                    .group_by(Claim.reject_rule)
                )
            ).all()
            ratings = (await s.execute(select(func.count(), func.avg(ReportRating.rating)).where(
                ReportRating.created_at >= since))).one()  # fmt: skip
            intake_rows = (await s.execute(select(IntakeEvent.chat_id, IntakeEvent.kind, IntakeEvent.details)
                                           .where(IntakeEvent.created_at >= since)
                                           .order_by(IntakeEvent.created_at))).all()  # fmt: skip
        areas: dict[str, dict[str, Any]] = {}
        for j in jobs:
            a = areas.setdefault(j.area, {"jobs": 0, "accepted": 0, "rejected": 0, "pages_found": 0, "pages_cached": 0,
                                          "pages_rejected": {}, "values_rejected": {}, "reader_values": 0,
                                          "search_cost_eur": 0.0})  # fmt: skip
            a["jobs"] += 1
            a["accepted"] += j.accepted or 0
            a["rejected"] += j.rejected or 0
            a["pages_found"] += j.pages_found or 0
            a["pages_cached"] += j.pages_cached or 0
            a["reader_values"] += j.reader_values or 0
            a["search_cost_eur"] += float(j.search_cost_eur or 0)
            for key in ("pages_rejected", "values_rejected"):
                for k, n in (getattr(j, key) or {}).items():
                    a[key][k] = a[key].get(k, 0) + int(n)
        # spec 007 FR-023: share of searches that found nothing, per area and market
        tried: dict[str, dict[str, list[bool]]] = {}
        for j in jobs:
            for q in j.queries or []:
                if isinstance(q, dict) and "empty" in q:
                    tried.setdefault(j.area, {}).setdefault(str(q.get("market", "ES")), []).append(bool(q["empty"]))
        empty_share = {a: {m: round(sum(v) / len(v), 3) for m, v in ms.items()} for a, ms in tried.items()}
        met: dict[str, list[bool]] = {}
        for r in runs:
            met.setdefault(r.area, []).append(bool(r.minimum_met))
        for area, flags in met.items():
            areas.setdefault(area, {})["minimum_met_share"] = round(sum(flags) / len(flags), 3)
        paid = [c for c in calls if not c.cached]
        return {
            "days": days,
            "areas": areas,
            "sense_rejections": {str(r): int(n) for r, n in sense_rows},  # spec 004 FR-027, per rule
            "empty_search_share": empty_share,
            "intake": intake_summary([(str(a), str(b), dict(c or {})) for a, b, c in intake_rows]),  # spec 005 R13
            "ratings": {"count": int(ratings[0] or 0), "average": round(float(ratings[1]), 2) if ratings[1] else None},
            "sites": [
                {"domain": x.domain, "day": x.day.isoformat(), "ok": x.ok, "failed": x.failed, "ambiguous": x.ambiguous}
                for x in sites
            ],  # fmt: skip
            "search": {
                "paid_calls": len(paid),
                "cache_hits": len(calls) - len(paid),
                "cost_eur": round(sum(float(c.cost_eur or 0) for c in paid), 4),
                "by_provider": {p: sum(1 for c in paid if c.provider == p) for p in {c.provider for c in paid}},
            },
        }


class FeasibilityRepo:
    """Storage for the feasibility check (spec 003 US3): editorial used-price ranges and persisted verdicts."""

    async def used_ranges(self, variant_id: str) -> list[tuple[Any, str]]:
        from automind.shared.infrastructure.db.models import Evidence, UsedPriceRange  # noqa: PLC0415

        async with sessionmaker()() as s:
            rows = await s.execute(
                select(UsedPriceRange, Evidence.url)
                .join(Evidence, UsedPriceRange.evidence_id == Evidence.id)
                .where(UsedPriceRange.variant_id == variant_id, UsedPriceRange.status == "ACCEPTED")
            )
            return [(r, str(u)) for r, u in rows.all()]

    async def save_checks(self, chat_id: str, turn_id: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        async with sessionmaker()() as s:
            for r in rows:
                s.add(FeasibilityCheck(chat_id=chat_id, turn_id=turn_id, **r))
            await s.commit()


class MarketFactRepo:
    """market_facts table (spec 006 US5): one row per market and key, the newest reading wins."""

    async def upsert(self, rows: list[dict[str, Any]], evidence_id: str, market: str = "ES") -> int:
        from automind.shared.infrastructure.db.models import MarketFact  # noqa: PLC0415

        if not rows:
            return 0
        async with sessionmaker()() as s:
            for r in rows:
                q = select(MarketFact).where(MarketFact.market == market, MarketFact.key == r["key"])
                row = (await s.execute(q)).scalar_one_or_none()
                if row is None:
                    row = MarketFact(market=market, key=r["key"])
                    s.add(row)
                row.value, row.evidence_ids, row.fetched_at = r["value"], [evidence_id], now()
                row.valid_from, row.valid_to = r["valid_from"], r["valid_to"]
            await s.commit()
        return len(rows)

    async def done(self, market: str = "ES") -> Any:
        """When the market was last researched: the newest fact or the newest run of the area."""
        from automind.shared.infrastructure.db.models import MarketFact  # noqa: PLC0415

        async with sessionmaker()() as s:
            fact = (await s.execute(select(func.max(MarketFact.fetched_at))
                                    .where(MarketFact.market == market))).scalar()  # fmt: skip
            run = (await s.execute(select(func.max(ResearchRun.completed_at))
                                   .where(ResearchRun.area == "incentives"))).scalar()  # fmt: skip
        dates = [x for x in (fact, run) if x is not None]
        return max(dates) if dates else None

    async def load(self, market: str = "ES") -> list[dict[str, Any]]:
        from automind.shared.infrastructure.db.models import MarketFact  # noqa: PLC0415

        async with sessionmaker()() as s:
            got = (await s.execute(select(MarketFact).where(MarketFact.market == market))).scalars().all()
        return [{"key": r.key, "value": dict(r.value or {}), "valid_from": r.valid_from, "valid_to": r.valid_to,
                 "evidence_ids": list(r.evidence_ids or []), "fetched_at": r.fetched_at} for r in got]  # fmt: skip


class RatingRepo:
    """Report ratings (spec 004 FR-026): one per assistant message, the latest wins."""

    async def save(self, chat_id: str, message_id: str, rating: int, note: str = "") -> None:
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        values = {"message_id": message_id[:36], "chat_id": chat_id, "rating": max(1, min(5, int(rating))),
                  "note": (note or "")[:1000]}  # fmt: skip
        async with sessionmaker()() as s:
            if await s.get(Chat, chat_id) is None:
                return
            stmt = insert(ReportRating).values(**values)
            await s.execute(stmt.on_conflict_do_update(index_elements=["message_id"], set_=values))
            await s.commit()


class ModelVersionsRepo:
    """The versions of model generations (spec 008 US6): the identification ladder's shared cache."""

    @staticmethod
    def _fits(row: Any, generation: str | None, year: int | None, new: bool) -> bool:
        from automind.shared.vehicle.identity import generation_matches  # noqa: PLC0415

        if generation:
            return str(row.generation).lower() == generation.lower()
        if year is not None:
            return row.years_from is None or generation_matches(year, row.years_from, row.years_to, 1)
        return new and row.years_to is None

    async def get(self, make: str, model: str, generation: str | None, year: int | None, new: bool,
                  ttl_days: int) -> Any:  # fmt: skip
        from automind.chat.domain.identification.ladder import Generation, version_of_json  # noqa: PLC0415
        from automind.shared.infrastructure.db.models import ModelVersions  # noqa: PLC0415

        async with sessionmaker()() as s:
            q = (
                select(ModelVersions)
                .where(func.lower(ModelVersions.make) == make.lower(), func.lower(ModelVersions.model) == model.lower(),
                       ModelVersions.market == "ES")
                .order_by(ModelVersions.years_from.desc().nulls_last())
            )  # fmt: skip
            rows = (await s.execute(q)).scalars().all()
        fresh = datetime.now(ZoneInfo("UTC")) - timedelta(days=ttl_days)
        for r in rows:
            if r.fetched_at >= fresh and self._fits(r, generation, year, new):
                return Generation(r.make, r.model, r.generation, r.years_from, r.years_to, r.body_class,
                                  [version_of_json(v) for v in r.versions], list(r.sources))  # fmt: skip
        return None

    async def put(self, g: Any) -> None:
        from automind.chat.domain.identification.ladder import version_to_json  # noqa: PLC0415
        from automind.shared.infrastructure.db.models import ModelVersions  # noqa: PLC0415

        async with sessionmaker()() as s:
            q = select(ModelVersions).where(
                ModelVersions.make == g.make, ModelVersions.model == g.model,
                ModelVersions.generation == g.generation, ModelVersions.market == "ES",
            )  # fmt: skip
            row = (await s.execute(q)).scalar_one_or_none()
            if row is None:
                row = ModelVersions(make=g.make, model=g.model, generation=g.generation, market="ES")
                s.add(row)
            row.years_from, row.years_to, row.body_class = g.years_from, g.years_to, g.body_class
            row.versions, row.sources = [version_to_json(v) for v in g.versions], g.sources
            row.fetched_at = datetime.now(ZoneInfo("UTC"))
            await s.commit()


def _turn(t: Turn) -> TurnRecord:
    return TurnRecord(id=t.id, chat_id=t.chat_id, seq=t.seq, status=TurnStatus(t.status), usage=dict(t.usage or {}))


def _message(m: ChatMessage) -> MessageRecord:
    return MessageRecord(id=m.id, chat_id=m.chat_id, turn_id=m.turn_id, role=Role(m.role), text=m.text,
                         blocks=list(m.blocks or []), created_at=m.created_at)  # fmt: skip


def _job(j: ResearchJob) -> JobRecord:
    return JobRecord(id=j.id, turn_id=j.turn_id, variant_id=j.variant_id, area=j.area, round=j.round,
                     status=JobStatus(j.status), attempts=j.attempts or 0, error=j.error)  # fmt: skip
