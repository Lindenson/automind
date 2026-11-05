"""The insight loop (spec 010 US3): daily, and earlier when failures pile up. In-process, like retention.

python -m automind.insight.loop --once     # one analysis now (operator, tests)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from automind.infrastructure.config import load_yaml
from automind.infrastructure.db.models import now
from automind.infrastructure.db.session import sessionmaker
from automind.insight.application.analyse import run_once
from automind.insight.infrastructure.repo import IssueRepo, failures
from automind.insight.metrics import heartbeat

log = logging.getLogger(__name__)
PROMPT = Path(__file__).parent / "prompts" / "analyst_issue.md"  # insight owns its prompt (no orchestration import)
TZ = ZoneInfo("Europe/Madrid")


async def _spent_by_analyst(since: datetime) -> float:
    async with sessionmaker()() as s:
        q = text("SELECT coalesce(sum(cost_eur),0) FROM llm_calls WHERE role = 'analyst' AND created_at >= :s")
        return float((await s.execute(q, {"s": since})).scalar() or 0)


def _llm() -> Any:
    from automind.infrastructure.adapters import LiveLLM  # noqa: PLC0415

    return LiveLLM()


async def analyse(kind: str = "daily", llm: Any = "live") -> dict[str, int]:
    cfg = load_yaml("insight.yaml")
    severity = load_yaml("outcome.yaml").get("severity") or {}
    repo = IssueRepo(cfg)
    from automind.insight.application.seed import seed_issues  # noqa: PLC0415

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


async def insight_loop() -> None:
    cfg = load_yaml("insight.yaml")
    wake = int((cfg.get("schedule") or {}).get("wake_minutes", 10)) * 60
    heartbeat.register("insight", wake)
    repo = IssueRepo(cfg)
    while True:
        try:
            kind = await _due(repo, cfg)
            if kind:
                stats = await analyse(kind)
                log.info("insight.run kind=%s %s", kind, stats)
            heartbeat.beat("insight", True)  # healthy: checked on schedule, ran when due
        except Exception:  # noqa: BLE001 - the loop must never stop the service
            log.exception("insight.run_failed")
            heartbeat.beat("insight", False)
        await asyncio.sleep(wake)


def main() -> None:
    if "--once" not in sys.argv:
        print(__doc__)
        return
    from automind.infrastructure.config import configure_domain  # noqa: PLC0415

    configure_domain()
    print(asyncio.run(analyse("manual")))


if __name__ == "__main__":
    main()
