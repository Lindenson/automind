"""Cached make line-ups that are not the make's range (spec 013 T015): list them, or remove them.

    python -m automind.delivery.cli.lineups audit [--min-models 5]
    python -m automind.delivery.cli.lineups purge [--min-models 5]

The rule is the sanity gate's (`chat.domain.intake.lineup_sanity`): kept when the maker's site is a source, else
at least `--min-models` models from two pages. `audit` prints one line per faulty line-up (make, market, models,
fault, sources) and changes nothing; `purge` prints the same lines and deletes those rows (take a backup first:
`scripts/deploy.sh backup`). A store failure propagates (exit code ≠ 0); nothing is half-deleted per row.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from automind.acquisition import api as acquisition
from automind.acquisition.api import StoredLineup
from automind.chat.domain.intake.lineup_sanity import MIN_MODELS, LineupFault, lineup_fault


@dataclass(frozen=True)
class Faulty:
    """A cached line-up that is not the range, and why."""

    lineup: StoredLineup
    fault: LineupFault

    def line(self) -> str:
        """make | market | n models (names) | fault | source urls."""
        lu = self.lineup
        names = ", ".join(str(m.get("model")) for m in lu.models)
        urls = " ".join(str(s.get("url")) for s in lu.sources)
        return f"{lu.make} | {lu.market} | {len(lu.models)} ({names}) | {self.fault.value} | {urls}"


def faulty(lineups: list[StoredLineup], min_models: int) -> list[Faulty]:
    """The line-ups the sanity gate rejects."""
    out = []
    for lu in lineups:
        if (f := lineup_fault([m.get("source_url") for m in lu.models], lu.sources, min_models)) is not None:
            out.append(Faulty(lu, f))
    return out


async def main_async(argv: list[str]) -> int:
    """Audit or purge; 0 on success."""
    args = parse(argv)
    bad = faulty(await acquisition.all_lineups(), args.min_models)
    for f in bad:
        print(f.line())
        if args.command == "purge":
            await acquisition.delete_lineup(f.lineup.make, f.lineup.market)
    verb = "removed" if args.command == "purge" else "found"
    print(f"{len(bad)} line-up(s) not the range {verb} (min models {args.min_models})", file=sys.stderr)
    return 0


def parse(argv: list[str]) -> argparse.Namespace:
    """The command line."""
    p = argparse.ArgumentParser(prog="python -m automind.delivery.cli.lineups", description=__doc__)
    p.add_argument("command", choices=["audit", "purge"])
    p.add_argument("--min-models", type=int, default=MIN_MODELS)
    return p.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(sys.argv[1:])))
