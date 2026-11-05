"""Registered versions of a model from the open datasets (spec 011 identity reader `dataset_versions`).

Offline first: the EEA CO2 group keys stored with the gold values of the model's catalogue variants
(`gold_values.record_key`), then the dataset rows cached for the make (`search_cache`, provider `dataset`). Only
when neither has the model, one bounded live query of the make through the loader (`gold/loaders/eea_co2.py`,
through the engine port `AcqPorts.datasets`), cached for the dataset's refresh period. Never raises: a failure is
an empty list (the caller asks without these options).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.gold.domain.match import DatasetRow, MatchCfg, norm_text
from automind.acquisition.gold.domain.versions import IdRow, RegisteredVersion, group, rows_of_keys
from automind.infrastructure import config
from automind.infrastructure.db import GoldValueRow, SearchCache, Variant, sessionmaker

log = logging.getLogger(__name__)
DATASET = "eea_co2"
PROVIDER = "dataset"
TIMEOUT_S = 20.0  # default; config/search.yaml intake.dataset_versions_timeout_s
MIN_REGISTRATIONS = 10  # default; config/search.yaml intake.dataset_versions_min_registrations


def _cfg() -> dict[str, Any]:
    return dict((config.gold_datasets_config().get("datasets") or {}).get(DATASET) or {})


def _match_cfg() -> MatchCfg:
    return MatchCfg.from_config(config.gold_datasets_config(), config.load_yaml("makes.yaml"))


def _intake(ports: Any) -> dict[str, Any]:
    return dict((getattr(getattr(ports, "ref", None), "search", None) or {}).get("intake") or {})


def _key(make: str) -> str:
    return hashlib.sha256(f"dataset_rows|{DATASET}|{norm_text(make)}".encode()).hexdigest()


def _id_row(r: DatasetRow) -> IdRow:
    return IdRow(r.dataset, r.make, r.model, r.fuel, r.power_kw, r.displacement_cc, r.year_from, r.year_to,
                 r.registrations)  # fmt: skip


def _to_json(r: IdRow) -> list[Any]:
    return [r.dataset, r.make, r.model, r.fuel, r.engine_kw, r.displacement_cc, r.year_from, r.year_to, r.registrations]


def _of_json(x: list[Any]) -> IdRow:
    return IdRow(*x)


async def stored_rows(make: str, model: str) -> list[IdRow]:
    """The EEA groups matched to the model's catalogue variants by the last gold load."""
    async with sessionmaker()() as s:
        q = (
            select(GoldValueRow.record_key).distinct()
            .join(Variant, Variant.id == GoldValueRow.variant_id)
            .where(func.lower(Variant.make) == make.lower(), func.lower(Variant.model) == model.lower(),
                   GoldValueRow.dataset_id.like(f"{DATASET}%"), GoldValueRow.record_key.is_not(None))
        )  # fmt: skip
        keys = [k for k in (await s.execute(q)).scalars() if k]
    return rows_of_keys(keys, DATASET)


async def cached_rows(make: str) -> list[IdRow] | None:
    """The make's dataset rows cached by an earlier live query; None when not cached (or expired)."""
    async with sessionmaker()() as s:
        row = await s.get(SearchCache, _key(make))
    if row is None or row.expires_at <= datetime.now(UTC):
        return None
    return [_of_json(x) for x in row.hits or []]


async def cache_rows(make: str, rows: list[IdRow]) -> None:
    now = datetime.now(UTC)
    days = float(_cfg().get("refresh_days", 30)) if rows else 1.0  # an empty answer is retried the next day
    values = {"key": _key(make), "provider": PROVIDER, "query": f"{DATASET} {make}"[:2000], "gl": "-", "hl": "-",
              "hits": [_to_json(r) for r in rows], "fetched_at": now, "empty": not rows,
              "expires_at": now + timedelta(days=days)}  # fmt: skip
    async with sessionmaker()() as s:
        await s.execute(insert(SearchCache).values(**values).on_conflict_do_update(index_elements=["key"], set_=values))
        await s.commit()


async def live_rows(make: str) -> list[DatasetRow]:
    """The live dataset query of one make (the engine port `AcqPorts.datasets` in production)."""
    from automind.acquisition.gold.loaders import eea_co2  # noqa: PLC0415 - httpx only when a query runs

    return await eea_co2.fetch_rows(_cfg(), make=norm_text(make).upper())


def _group(rows: list[IdRow], make: str, model: str, fuel: str | None, year_from: int | None,
           min_regs: int) -> list[RegisteredVersion]:  # fmt: skip
    m = _match_cfg()
    return group(rows, make, model, fuel=fuel, year_from=year_from, aliases=m.aliases, strip_words=m.strip_words,
                 min_registrations=min_regs)  # fmt: skip


async def registered_versions(
    ports: Any, make: str, model: str, generation: str | None = None, fuel: str | None = None,
    year_from: int | None = None,
) -> list[RegisteredVersion]:  # fmt: skip
    """Distinct registered versions of `make` `model` (`fuel`, from `year_from`); the generation is not in the
    datasets, `year_from` (its first year) bounds it. Stored gold first, then the cache, then one live query."""
    lim = _intake(ports)
    min_regs = int(lim.get("dataset_versions_min_registrations", MIN_REGISTRATIONS))
    try:
        found = _group(await stored_rows(make, model), make, model, fuel, year_from, 1)
        if found:
            return found
        rows = await cached_rows(make)
        live = getattr(ports, "datasets", None)
        if rows is None and live is not None:
            try:
                async with asyncio.timeout(float(lim.get("dataset_versions_timeout_s", TIMEOUT_S))):
                    rows = [_id_row(r) for r in await live(make)]
            except Exception:
                await cache_rows(make, [])  # a slow or failed dataset is not waited for again until tomorrow
                raise
            await cache_rows(make, rows)
        return _group(rows or [], make, model, fuel, year_from, min_regs)
    except Exception:  # noqa: BLE001 - the datasets only add options; the question is asked without them
        log.warning("dataset_versions.failed make=%s model=%s", make, model, exc_info=True)
        return []


def source_url() -> str:
    cfg = _cfg()
    return str(cfg.get("datahub") or cfg.get("url") or "")
