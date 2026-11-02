"""Repositories for the conversation tables (chats, case files, turns, events, jobs, usage).

They implement the application ports (application/ports.py). Each method opens its own short
session, so callers never hold a transaction across LLM or web calls.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .models import (
    CaseFileRow,
    Chat,
    ChatMessage,
    LLMCall,
    ResearchJob,
    SearchCall,
    Turn,
    TurnEvent,
    now,
    uid,
)
from .session import sessionmaker


class ChatRepo:
    async def ensure(self, chat_id: str, title: str | None = None) -> Chat:
        async with sessionmaker()() as s:
            chat = await s.get(Chat, chat_id)
            if chat is None:
                chat = Chat(id=chat_id, title=(title or "New chat")[:60])
                s.add(chat)
                try:
                    await s.commit()
                except IntegrityError:  # created concurrently
                    await s.rollback()
                    chat = await s.get(Chat, chat_id)
                    assert chat is not None
            return chat

    async def touch(self, chat_id: str, *, language: str | None = None, title: str | None = None) -> None:
        values: dict[str, Any] = {"updated_at": now()}
        if language:
            values["language"] = language
        if title:
            values["title"] = title[:60]
        async with sessionmaker()() as s:
            await s.execute(update(Chat).where(Chat.id == chat_id).values(**values))
            await s.commit()

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

    async def list(self, limit: int = 100) -> list[Chat]:
        async with sessionmaker()() as s:
            rows = await s.execute(select(Chat).order_by(Chat.updated_at.desc()).limit(limit))
            return list(rows.scalars())


class CaseRepo:
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

    async def get(self, chat_id: str, version: int) -> dict[str, Any] | None:
        async with sessionmaker()() as s:
            row = await s.get(CaseFileRow, (chat_id, version))
            return dict(row.data) if row else None

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


class TurnRepo:
    async def start(self, chat_id: str, user_message_id: str | None, case_version: int) -> Turn:
        async with sessionmaker()() as s:
            seq = (await s.execute(select(func.max(Turn.seq)).where(Turn.chat_id == chat_id))).scalar()
            turn = Turn(
                id=uid(),
                chat_id=chat_id,
                seq=int(seq or 0) + 1,
                user_message_id=user_message_id,
                case_version_before=case_version,
                status="RUNNING",
            )
            s.add(turn)
            await s.commit()
            return turn

    async def get(self, turn_id: str) -> Turn | None:
        async with sessionmaker()() as s:
            return await s.get(Turn, turn_id)

    async def update(self, turn_id: str, **values: Any) -> None:
        if values.get("status") in ("DONE", "CANCELLED", "FAILED") and "finished_at" not in values:
            values["finished_at"] = now()
        async with sessionmaker()() as s:
            await s.execute(update(Turn).where(Turn.id == turn_id).values(**values))
            await s.commit()

    async def active(self, chat_id: str) -> Turn | None:
        """The turn that is RUNNING or WAITING_CONFIRMATION, if any."""
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(Turn)
                .where(Turn.chat_id == chat_id, Turn.status.in_(("RUNNING", "WAITING_CONFIRMATION")))
                .order_by(Turn.seq.desc())
                .limit(1)
            )
            return rows.scalar_one_or_none()

    async def last_report_fingerprint(self, chat_id: str) -> str | None:
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(Turn.fingerprint)
                .where(Turn.chat_id == chat_id, Turn.action == "REPORT", Turn.status == "DONE")
                .order_by(Turn.seq.desc())
                .limit(1)
            )
            return rows.scalar_one_or_none()

    async def running(self) -> list[Turn]:
        async with sessionmaker()() as s:
            rows = await s.execute(select(Turn).where(Turn.status == "RUNNING"))
            return list(rows.scalars())


class EventRepo:
    async def append(self, chat_id: str, turn_id: str | None, type_: str, payload: dict[str, Any]) -> int:
        """Persist an event with the next per-chat seq. Retries on a concurrent seq collision."""
        for _ in range(5):
            async with sessionmaker()() as s:
                seq = (await s.execute(select(func.max(TurnEvent.seq)).where(TurnEvent.chat_id == chat_id))).scalar()
                nxt = int(seq or 0) + 1
                s.add(TurnEvent(chat_id=chat_id, seq=nxt, turn_id=turn_id, type=type_, payload=payload))
                try:
                    await s.commit()
                    return nxt
                except IntegrityError:
                    await s.rollback()
        raise RuntimeError(f"could not allocate event seq for chat {chat_id}")

    async def since(self, chat_id: str, after_seq: int) -> list[TurnEvent]:
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(TurnEvent).where(TurnEvent.chat_id == chat_id, TurnEvent.seq > after_seq).order_by(TurnEvent.seq)
            )
            return list(rows.scalars())


class JobRepo:
    async def create(self, chat_id: str, turn_id: str, variant_id: str, area: str, round_: int) -> ResearchJob:
        async with sessionmaker()() as s:
            job = ResearchJob(
                id=uid(), chat_id=chat_id, turn_id=turn_id, variant_id=variant_id, area=area, round=round_
            )
            s.add(job)
            await s.commit()
            return job

    async def get(self, job_id: str) -> ResearchJob | None:
        async with sessionmaker()() as s:
            return await s.get(ResearchJob, job_id)

    async def for_turn(self, turn_id: str) -> list[ResearchJob]:
        async with sessionmaker()() as s:
            rows = await s.execute(select(ResearchJob).where(ResearchJob.turn_id == turn_id))
            return list(rows.scalars())

    async def skip_open(self, turn_id: str, reason: str = "cancelled") -> int:
        """Mark PENDING/RUNNING jobs of a turn as SKIPPED (cancel). Returns how many."""
        async with sessionmaker()() as s:
            res = await s.execute(
                update(ResearchJob)
                .where(ResearchJob.turn_id == turn_id, ResearchJob.status.in_(("PENDING", "RUNNING")))
                .values(status="SKIPPED", error=reason, finished_at=now())
            )
            await s.commit()
            return int(res.rowcount or 0)

    async def mark(self, job_id: str, status: str, **values: Any) -> None:
        if status == "RUNNING":
            values.setdefault("started_at", now())
            values["attempts"] = ResearchJob.attempts + 1
        if status in ("DONE", "FAILED", "SKIPPED"):
            values.setdefault("finished_at", now())
        async with sessionmaker()() as s:
            await s.execute(update(ResearchJob).where(ResearchJob.id == job_id).values(status=status, **values))
            await s.commit()


class MessageRepo:
    async def history(self, chat_id: str) -> list[ChatMessage]:
        async with sessionmaker()() as s:
            rows = await s.execute(
                select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(ChatMessage.created_at)
            )
            return list(rows.scalars())

    async def save(
        self,
        chat_id: str,
        role: str,
        text: str,
        blocks: list[Any] | None = None,
        *,
        message_id: str | None = None,
        turn_id: str | None = None,
    ) -> ChatMessage:
        async with sessionmaker()() as s:
            m = ChatMessage(
                id=message_id or uid(), chat_id=chat_id, turn_id=turn_id, role=role, text=text, blocks=blocks or []
            )
            s.add(m)
            await s.commit()
            return m


class UsageRepo:
    async def record_llm(
        self,
        *,
        chat_id: str | None,
        turn_id: str | None,
        role: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        cost_eur: float,
        job_id: str | None = None,
        area: str | None = None,
    ) -> None:
        async with sessionmaker()() as s:
            s.add(
                LLMCall(
                    chat_id=chat_id,
                    turn_id=turn_id,
                    role=role,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    cost_eur=cost_eur,
                    job_id=job_id,
                    area=area,
                )
            )
            await s.commit()

    async def record_search(
        self,
        *,
        chat_id: str | None,
        turn_id: str | None,
        kind: str,
        credits: float,
        cost_eur: float,
        job_id: str | None = None,
        area: str | None = None,
    ) -> None:
        async with sessionmaker()() as s:
            s.add(
                SearchCall(
                    chat_id=chat_id, turn_id=turn_id, kind=kind, credits=credits, cost_eur=cost_eur, job_id=job_id,
                    area=area,
                )
            )  # fmt: skip
            await s.commit()

    async def area_averages(self, min_jobs: int = 3) -> dict[str, tuple[float, float, float]]:
        """Per area: (avg input tokens, avg output tokens, avg searches) per research job (R12).

        Areas with fewer than `min_jobs` recorded jobs are left out (the default applies).
        """
        async with sessionmaker()() as s:
            llm = await s.execute(
                select(
                    LLMCall.area,
                    func.count(func.distinct(LLMCall.job_id)),
                    func.sum(LLMCall.input_tokens),
                    func.sum(LLMCall.output_tokens),
                )
                .where(LLMCall.job_id.is_not(None))
                .group_by(LLMCall.area)
            )
            srch = await s.execute(
                select(SearchCall.area, func.count(func.distinct(SearchCall.job_id)), func.count(SearchCall.id))
                .where(SearchCall.job_id.is_not(None))
                .group_by(SearchCall.area)
            )
            searches = {a: (int(j), int(n)) for a, j, n in srch.all()}
        out: dict[str, tuple[float, float, float]] = {}
        for area, jobs, tin, tout in llm.all():
            if area and jobs >= min_jobs:
                sj, sn = searches.get(area, (jobs, 0))
                out[area] = (int(tin or 0) / jobs, int(tout or 0) / jobs, sn / max(sj, 1))
        return out

    async def turn_totals(self, turn_id: str) -> dict[str, Any]:
        """Sum of recorded usage for a turn (used to verify the live counters, SC-012)."""
        async with sessionmaker()() as s:
            llm = (
                await s.execute(
                    select(
                        func.count(LLMCall.id),
                        func.coalesce(func.sum(LLMCall.input_tokens), 0),
                        func.coalesce(func.sum(LLMCall.output_tokens), 0),
                        func.coalesce(func.sum(LLMCall.cost_eur), 0),
                    ).where(LLMCall.turn_id == turn_id)
                )
            ).one()
            srch = (
                await s.execute(
                    select(func.count(SearchCall.id), func.coalesce(func.sum(SearchCall.cost_eur), 0)).where(
                        SearchCall.turn_id == turn_id
                    )
                )
            ).one()
        return {
            "llm_calls": int(llm[0]),
            "input_tokens": int(llm[1]),
            "output_tokens": int(llm[2]),
            "search_calls": int(srch[0]),
            "cost_eur": round(float(llm[3]) + float(srch[1]), 5),
        }
