"""The evaluator (spec 011 US5 T103, research R13): daily, code only — no model, no lever. It changes nothing but the
fate of changes already behind the gates:
- the accuracy KPI against gold, separately for sources (`capabilities`) and for processing (`component_reputation`);
- canary progress: every change in shadow is decided on time (`gates/shadow.decide_all`);
- the watch: every accepted change is kept or rolled back (`gates/watch.check_all`);
- the gauges of open changes and agent spend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text

from automind.acquisition.domain.replay import wilson_lb
from automind.infrastructure.db import sessionmaker

_KPI = {
    "sources": "SELECT coalesce(sum(right_w), 0), coalesce(sum(wrong_w), 0) FROM capabilities",
    "processing": "SELECT coalesce(sum(right_w), 0), coalesce(sum(wrong_w), 0) FROM component_reputation",
}


async def accuracy_kpi() -> dict[str, dict[str, float | None]]:
    """Decayed right/wrong weight against gold and the other accuracy signals, for sources and for processing."""
    out: dict[str, dict[str, float | None]] = {}
    async with sessionmaker()() as s:
        for name, sql in _KPI.items():
            right, wrong = (float(x) for x in (await s.execute(text(sql))).one())
            n = right + wrong
            out[name] = {"right_w": round(right, 3), "wrong_w": round(wrong, 3),
                         "accuracy": round(right / n, 4) if n else None,
                         "accuracy_lb": round(lb, 4) if (lb := wilson_lb(round(right), round(n))) is not None
                         else None}  # fmt: skip
    return out


async def run(now: datetime | None = None) -> dict[str, Any]:
    from automind.acquisition.gates import journal, shadow, watch  # noqa: PLC0415

    kpi = await accuracy_kpi()
    shadows = await shadow.decide_all(now)
    watched = await watch.check_all(now)
    await journal.publish_gauges()
    return {"kpi": kpi, "shadow": shadows, "watch": watched}
