"""Run Alembic migrations programmatically (startup, tests, scripts/dev.sh)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from automind.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[4]
BASELINE = "0001"


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["url"] = url or settings().database_url
    cfg.attributes["configure_logger"] = False
    return cfg


async def _needs_baseline_stamp(url: str) -> bool:
    """A demo DB created by `create_all` has the tables but no alembic_version: stamp the baseline."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    finally:
        await engine.dispose()
    return "vehicle_variants" in names and "alembic_version" not in names


async def upgrade_head(url: str | None = None) -> None:
    cfg = alembic_config(url)
    if await _needs_baseline_stamp(cfg.attributes["url"]):
        await asyncio.to_thread(command.stamp, cfg, BASELINE)
    await asyncio.to_thread(command.upgrade, cfg, "head")


def main() -> None:
    asyncio.run(upgrade_head())
    print("migrations: at head")


if __name__ == "__main__":
    main()
