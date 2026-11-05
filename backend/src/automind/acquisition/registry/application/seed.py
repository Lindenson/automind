"""Seed the registry (spec 010 US8, T050): favourites and the 009 survey. Idempotent. (Spec 007's learned domains
were seeded once; the rule is gone since spec 011 T124 and the `learned_sources` table is no longer read.)

python -m automind.acquisition.registry.application.seed
"""

from __future__ import annotations

import asyncio
from typing import Any

from automind.acquisition.registry.domain.seed_rules import from_favourite, from_survey
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.infrastructure.config import load_yaml


async def seed() -> dict[str, int]:
    sources = load_yaml("sources.yaml")
    deny = tuple(str(x).lower() for x in sources.get("denylist") or [])
    reg = load_yaml("registry.yaml")
    fam = reg.get("families") or {}
    repo = RegistryRepo()
    out = {
        "favourites": await repo.seed(
            (from_favourite(f, deny, fam) for f in sources.get("favourites") or []),
            "seed: config/sources.yaml favourite",
        )
    }
    survey = _survey_list()  # a YAML list, not a mapping: read directly
    out["survey"] = await repo.seed((from_survey(e, deny, fam) for e in survey), "seed: 009 survey (robots and terms)")
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
