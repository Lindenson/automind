"""The insight loop (spec 010 US3): daily, and earlier when failures pile up. Run by the acquisition worker
(spec 011 task `insight_run`), never in the API process.

python -m automind.cli insight --once     # one analysis now (operator, tests)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from automind.observability.application.analyse import run_once
from automind.observability.infrastructure.repo import IssueRepo, failures
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db.models import now
from automind.shared.infrastructure.db.session import sessionmaker

log = logging.getLogger(__name__)
PROMPT = Path(__file__).parent / "prompts" / "analyst_issue.md"  # insight owns its prompt (no orchestration import)
TZ = ZoneInfo("Europe/Madrid")


async def _spent_by_analyst(since: datetime) -> float:
    async with sessionmaker()() as s:
        q = text("SELECT coalesce(sum(cost_eur),0) FROM llm_calls WHERE role = 'analyst' AND created_at >= :s")
        return float((await s.execute(q, {"s": since})).scalar() or 0)


def _llm() -> Any:
    from automind.chat.infrastructure.adapters import LiveLLM  # noqa: PLC0415

    return LiveLLM()


async def analyse(kind: str = "daily", llm: Any = "live") -> dict[str, int]:
    cfg = load_yaml("insight.yaml")
    severity = load_yaml("outcome.yaml").get("severity") or {}
    repo = IssueRepo(cfg)
    from automind.observability.application.seed import seed_issues  # noqa: PLC0415

    await seed_issues()
    return await run_once(_llm() if llm == "live" else llm, PROMPT.read_text(encoding="utf-8"), repo, cfg, severity,
                          await failures(cfg), load_yaml, _spent_by_analyst, kind=kind)  # fmt: skip


async def _due(repo: IssueRepo, cfg: dict[str, Any]) -> str | None:
    last = await repo.last_run()
    t = now()
    sched = cfg.get("schedule") or {}
    local = t.astimezone(TZ)
    if last is None or (local.hour >= int(sched.get("daily_hour", 4)) and last.astimezone(TZ).date() < local.date()):
        return "daily"
    if await repo.new_failures_since(last) >= int(sched.get("early_new_failures", 10)):
        return "early"
    return None


async def run_if_due(llm: Any = "live") -> dict[str, Any]:
    """One check of the schedule (spec 011: the worker's `insight_run` task, every `wake_minutes`); runs when due."""
    cfg = load_yaml("insight.yaml")
    kind = await _due(IssueRepo(cfg), cfg)
    if not kind:
        return {"ran": None}
    stats = await analyse(kind, llm)
    log.info("insight.run kind=%s %s", kind, stats)
    return {"ran": kind, **stats}
