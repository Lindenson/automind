"""Seed the registry (spec 010 US8, T050): favourites, the 009 survey and learned domains. Idempotent.

python -m automind.acquisition.registry.application.seed
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from automind.acquisition.registry.domain.seed_rules import from_favourite, from_learned, from_survey
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db.models import LearnedSource
from automind.infrastructure.db.session import sessionmaker


async def seed() -> dict[str, int]:
    sources = load_yaml("sources.yaml")
    deny = tuple(str(x).lower() for x in sources.get("denylist") or [])
    reg = load_yaml("registry.yaml")
    fam = reg.get("families") or {}
    learned_cfg = load_yaml("search.yaml").get("learned") or {}
    repo = RegistryRepo()
    out = {
        "favourites": await repo.seed(
            (from_favourite(f, deny, fam) for f in sources.get("favourites") or []),
            "seed: config/sources.yaml favourite",
        )
    }
    survey = _survey_list()  # a YAML list, not a mapping: read directly
    out["survey"] = await repo.seed((from_survey(e, deny, fam) for e in survey), "seed: 009 survey (robots and terms)")
    async with sessionmaker()() as s:
        rows = [
            {
                "domain": r.domain,
                "area": r.area,
                "market": r.market,
                "source_type": r.source_type,
                "accepted_runs": r.accepted_runs,
                "misses": r.misses,
            }
            for r in (await s.execute(select(LearnedSource))).scalars()
        ]
    items = []
    for r in rows:
        cap = from_learned(r, deny, int(learned_cfg.get("min_runs", 3)), int(learned_cfg.get("max_misses", 5)))
        src, _ = from_favourite(
            {"domain": r["domain"], "source_type": r["source_type"], "areas": [], "markets": [r["market"]]}, deny, fam
        )
        src.access = "unknown"
        items.append((src, [cap]))
    out["learned"] = await repo.seed(items, "seed: learned sources (spec 007)")
    return out


def _survey_list() -> list[dict[str, Any]]:
    import yaml  # noqa: PLC0415

    from automind.infrastructure.config import config_dir  # noqa: PLC0415

    data = yaml.safe_load((config_dir() / "registry_seed_survey.yaml").read_text(encoding="utf-8"))
    return list(data or [])


async def seed_if_empty() -> dict[str, int] | None:
    return await seed() if await RegistryRepo().is_empty() else None


if __name__ == "__main__":
    print(asyncio.run(seed()))
