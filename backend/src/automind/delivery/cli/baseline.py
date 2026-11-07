"""`python -m automind.cli baseline start|status|close --name NAME [--note "..."]`: the KPI baseline window before
registry autonomy (spec 011 T073), over `KpiBaselines`. Prints JSON; a request that cannot be done (already open,
none open, younger than 7 days) prints why and exits 1."""

from __future__ import annotations

import argparse
import json
import sys

from automind.acquisition.reputation.application.baseline import BaselineError
from automind.delivery.baselines import kpi_baselines
from automind.shared.contracts.json import JsonObject


async def main_async(argv: list[str]) -> int:
    """Run one baseline action; 0 when done, 1 when the request cannot be done."""
    ap = argparse.ArgumentParser(prog="baseline", description="KPI baseline before registry autonomy")
    ap.add_argument("action", choices=("start", "status", "close"))
    ap.add_argument("--name", default="pre-autonomy")
    ap.add_argument("--note")
    args = ap.parse_args(argv)
    service = kpi_baselines()
    out: JsonObject | None
    try:
        if args.action == "start":
            out = {"started": await service.start(args.name, args.note)}
        elif args.action == "status":
            window = await service.status(args.name)
            out = window.to_json() if window is not None else None
        else:
            out = {"closed": args.name, "values": await service.close(args.name)}
    except BaselineError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0
