"""Load gold values from open datasets (spec 011 T023, FR-003).

    python -m automind.acquisition.gold.load --dataset {reference_set,eea_co2,eea_obfcm,rdw,all}
        [--make M] [--recent] [--dry-run]

Candidate variants are all `vehicle_variants` (or, with `--recent`, those asked in the last 30 days); the dataset's
loader (`gold/loaders/<name>.py`) returns its rows, `gold/domain/match.py` matches them to each variant, and the
gold values of each (dataset, variant) replace the previous load. Prints counts by attribute and matching rule.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import logging
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from automind.acquisition.gold import repo
from automind.acquisition.gold.domain.match import GoldValue, MatchCfg, VariantKey, match, norm_text, tokens
from automind.acquisition.infrastructure import config as acq_config
from automind.infrastructure import config
from automind.infrastructure.db import ResearchJob, Variant, sessionmaker

log = logging.getLogger(__name__)
DATASETS = ("reference_set", "eea_co2", "eea_obfcm", "rdw")
_FUEL_BY_POWERTRAIN = {"BEV": "bev", "PHEV": "phev", "HEV": "hybrid", "MHEV": "mhev"}


def fuel_of_variant(v: Any) -> str | None:
    if v.fuel:
        return str(v.fuel).lower()
    pt = (v.powertrain or "").upper()
    if pt in _FUEL_BY_POWERTRAIN:
        return _FUEL_BY_POWERTRAIN[pt]
    from automind.acquisition.pipeline.validate import fuel_of  # noqa: PLC0415 - the research-time rule

    return fuel_of(v.variant_name, v.powertrain)


def variant_key(v: Any, cfg: MatchCfg) -> VariantKey:
    return VariantKey(
        variant_id=v.id, make=v.make, model=v.model, model_tokens=tokens(v.model, cfg.strip_words),
        fuel=fuel_of_variant(v), power_kw=float(v.power_kw) if v.power_kw else None,
        years=(v.generation_years_from, v.generation_years_to), displacement_cc=v.engine_cc,
    )  # fmt: skip


async def candidates(make: str | None = None, recent: bool = False) -> list[Variant]:
    async with sessionmaker()() as s:
        q = select(Variant)
        if make:
            q = q.where(Variant.make.ilike(make))
        if recent:
            since = datetime.now(UTC) - timedelta(days=30)
            q = q.where(Variant.id.in_(select(ResearchJob.variant_id).where(ResearchJob.started_at >= since)))
        return list((await s.execute(q)).scalars())


def dataset_cfg(name: str) -> dict[str, Any]:
    """The dataset's mapping under `datasets:` in config/gold_datasets.yaml (what the loaders take)."""
    return dict((acq_config.gold_datasets_config().get("datasets") or {}).get(name) or {})


async def _write(dataset_id: str, variants: list[Variant], gold: list[GoldValue], dry_run: bool) -> None:
    if dry_run:
        return
    per: dict[str, list[GoldValue]] = {v.id: [] for v in variants}
    for g in gold:
        per.setdefault(g.variant_id, []).append(g)
    for vid, values in per.items():
        await repo.replace(dataset_id, vid, values)


async def load_dataset(
    name: str, variants: list[Variant], dry_run: bool = False, transport: Any = None
) -> list[GoldValue]:
    """Run one dataset's loader (`fetch_rows`), match, write; returns the gold values written (or that would be).
    `transport` is passed to the loader (tests: `httpx.MockTransport`)."""
    if name not in DATASETS:
        raise ValueError(f"unknown dataset {name!r}")
    mod = importlib.import_module(f"automind.acquisition.gold.loaders.{name}")
    if name == "reference_set":
        entries = mod.read_entries()
        info: Any = mod.INFO
        gold, rows_read = mod.gold_values(entries, variants), len(entries)
    else:
        from automind.acquisition.gold.loaders import meta  # noqa: PLC0415

        cfg = dataset_cfg(name)
        rows = await mod.fetch_rows(
            cfg, makes=sorted({norm_text(v.make).upper() for v in variants}), transport=transport
        )
        info = meta(cfg, mod.version(cfg))
        mcfg = MatchCfg.from_config(acq_config.gold_datasets_config(), config.load_yaml("makes.yaml"))
        gold = [g for v in variants for g in match(rows, variant_key(v, mcfg), mcfg, dataset_id=info.id)]
        rows_read = len(rows)
    if not dry_run:
        await repo.upsert_dataset(info, rows_read=rows_read, rows_matched=len({g.variant_id for g in gold}))
    await _write(info.id, variants, gold, dry_run)
    return gold


def summary(name: str, gold: list[GoldValue]) -> str:
    by = Counter((g.attribute, g.match_rule) for g in gold)
    lines = [f"{name}: {len(gold)} gold values for {len({g.variant_id for g in gold})} variants"]
    lines += [f"  {attr:<22} {rule:<40} {n}" for (attr, rule), n in sorted(by.items())]
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    variants = await candidates(args.make, args.recent)
    names = DATASETS if args.dataset == "all" else (args.dataset,)
    rc = 0
    for name in names:
        if importlib.util.find_spec(f"automind.acquisition.gold.loaders.{name}") is None:
            print(f"{name}: no loader yet", file=sys.stderr)
            rc = 1
            continue
        try:
            gold = await load_dataset(name, variants, args.dry_run)
        except Exception as e:  # noqa: BLE001 - one failing dataset never stops the others
            log.exception("gold.load_failed dataset=%s", name)
            print(f"{name}: failed ({type(e).__name__}: {e})", file=sys.stderr)
            rc = 1
            continue
        print(summary(name, gold) + (" (dry run)" if args.dry_run else ""))
    return rc


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m automind.acquisition.gold.load", description=__doc__)
    p.add_argument("--dataset", required=True, choices=[*DATASETS, "all"])
    p.add_argument("--make")
    p.add_argument("--recent", action="store_true", help="only variants asked in the last 30 days")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from automind.infrastructure.config import configure_domain  # noqa: PLC0415

    configure_domain()
    return asyncio.run(main_async(parse(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
