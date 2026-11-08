"""Load gold values from the open datasets and the reference set (spec 011 T023, FR-003).

    python -m automind.cli gold-load --dataset {reference_set,eea_co2,eea_obfcm,rdw,all}
        [--make M] [--recent] [--dry-run]

Candidate variants are all `vehicle_variants` (or, with `--recent`, those researched in the last 30 days); each
dataset's gold replaces its previous load (`acquisition.gold.application.load`). Prints counts by attribute and
matching rule. One failing dataset never stops the others; the exit code is 1 when any failed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from automind.acquisition.gold.domain.records import GoldValue
from automind.acquisition.gold.infrastructure import wiring

log = logging.getLogger(__name__)


async def main_async(argv: list[str]) -> int:
    """Load the asked datasets; 0 when every one loaded."""
    args = parse(argv)
    load = wiring.gold_load()
    variants = await wiring.candidates().variants(args.make, args.recent)
    rc = 0
    for name in load.names if args.dataset == "all" else (args.dataset,):
        try:
            gold = await load.run(name, variants, args.dry_run)
        except Exception as e:  # noqa: BLE001 - one failing dataset never stops the others
            log.exception("gold.load_failed dataset=%s", name)
            print(f"{name}: failed ({type(e).__name__}: {e})", file=sys.stderr)
            rc = 1
            continue
        print(summary(name, gold) + (" (dry run)" if args.dry_run else ""))
    return rc


def parse(argv: list[str]) -> argparse.Namespace:
    """The command line."""
    p = argparse.ArgumentParser(prog="python -m automind.cli gold-load", description=__doc__)
    p.add_argument("--dataset", required=True, choices=[*wiring.SOURCES, "all"])
    p.add_argument("--make")
    p.add_argument("--recent", action="store_true", help="only variants researched in the last 30 days")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def summary(name: str, gold: list[GoldValue]) -> str:
    """Counts of a load by attribute and matching rule."""
    by = Counter((g.attribute, g.match_rule) for g in gold)
    lines = [f"{name}: {len(gold)} gold values for {len({g.variant_id for g in gold})} variants"]
    lines += [f"  {attr:<22} {rule:<40} {n}" for (attr, rule), n in sorted(by.items())]
    return "\n".join(lines)
