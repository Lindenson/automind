"""The source registry's seed and review for the app's startup and the CLI. Composed here because the web API reaches
the engine only through its facades (contract `api-uses-engine-facades`)."""

from __future__ import annotations

from automind.acquisition.registry.infrastructure.wiring import daily_review, registry_seed


async def seed_if_empty() -> dict[str, int] | None:
    """Seed an empty registry from favourites and the 009 survey (spec 010 US8); None when it has sources."""
    return await registry_seed().run_if_empty()


async def seed() -> dict[str, int]:
    """Seed what is missing (idempotent)."""
    return await registry_seed().run()


async def review_now() -> dict[str, int]:
    """One review run now (kind "manual"); nothing happens with autonomy off."""
    return await daily_review().run(kind="manual")
