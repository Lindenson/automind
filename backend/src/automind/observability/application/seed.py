"""Known flaws as the first issues (spec 010 US5, T046): from config/seed_issues.yaml, idempotent by slug."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db.models import InsightIssue, now
from automind.shared.infrastructure.db.session import sessionmaker

SEED_IMPACT = 5.0  # fixed until real failures of the same kind are counted


async def seed_issues() -> int:
    entries: list[dict[str, Any]] = list(load_yaml("seed_issues.yaml").get("issues") or [])
    added = 0
    async with sessionmaker()() as s:
        for e in entries:
            fp = f"seed:{e['slug']}"
            if (await s.execute(select(InsightIssue.id).where(InsightIssue.fingerprint == fp))).first():
                continue
            t = now()
            example = {"chat_id": e.get("chat"), "quote": e.get("quote")}
            s.add(
                InsightIssue(
                    fingerprint=fp,
                    component=e["component"],
                    klass=e["klass"],
                    key=f"{e['component']}/{e['klass']}/{e['slug']}",
                    title=str(e["title"])[:200],
                    count_total=1,
                    count_7d=1,
                    chats_7d=1 if e.get("chat") else 0,
                    impact=SEED_IMPACT,
                    first_seen=t,
                    last_seen=t,
                    examples=[{k: v for k, v in example.items() if v}],
                    diagnosis={
                        "summary": e["title"],
                        "likely_cause": "Known from a live chat or the UI audit.",
                        "fix": {
                            "files": [],
                            "config_file": None,
                            "config_key": None,
                            "suggested_value": None,
                            "direction": None,
                            **e["fix"],
                        },
                        "verify": e.get("verify", ""),
                    },
                    diagnosed_at=t,
                    status="open",
                    source="seed:009" if e["component"] != "ui" else "seed:ux",
                    status_history=[{"at": t.isoformat(), "status": "open", "by": "seed"}],
                )
            )
            added += 1
        await s.commit()
    return added
