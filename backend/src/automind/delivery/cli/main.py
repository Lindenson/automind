"""The commands of `python -m automind.cli`: each one assembles the application (delivery.bootstrap) where it needs
the configuration, then hands its arguments to the module that does the work."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        print("usage: python -m automind.cli {" + ",".join(COMMANDS) + "} [args]", file=sys.stderr)
        return 2
    return COMMANDS[args[0]](args[1:])


def worker(argv: list[str]) -> int:
    """The acquisition worker: background tasks from the queue (`--once KIND` runs one task and exits)."""
    from automind.acquisition.worker import entry  # noqa: PLC0415

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    _configure()
    return asyncio.run(entry.run(entry.parse_args(argv)))


def replay(argv: list[str]) -> int:
    """Offline replay of a reader or extractor version over stored pages, scored against gold."""
    from automind.acquisition.replay import command  # noqa: PLC0415

    _configure()
    return asyncio.run(command.main_async(argv))


def gold_load(argv: list[str]) -> int:
    """Load gold values from the open datasets."""
    from automind.acquisition.gold import load  # noqa: PLC0415

    _configure()
    return asyncio.run(load.main_async(load.parse(argv)))


def parsers_migrate_v1(argv: list[str]) -> int:
    """Today's site readers become version 1 of their parser specs (idempotent)."""
    from automind.acquisition.parsing import migrate_v1  # noqa: PLC0415

    _configure()
    print(json.dumps(asyncio.run(migrate_v1.seed()), ensure_ascii=False))
    return 0


def insight(argv: list[str]) -> int:
    """One insight analysis run now (`--once`)."""
    from automind.observability import loop  # noqa: PLC0415

    if "--once" not in argv:
        print(loop.__doc__)
        return 0
    _configure()
    print(asyncio.run(loop.analyse("manual")))
    return 0


def baseline(argv: list[str]) -> int:
    """KPI baseline before registry autonomy: start | status | close --name NAME."""
    from automind.acquisition.reputation import baseline as module  # noqa: PLC0415

    return int(asyncio.run(module.main_async(argv)) or 0)


def fit_physics(argv: list[str]) -> int:
    """Fit the power-mass-acceleration envelope of config/physics.yaml."""
    from automind.acquisition.reputation import fit_physics as module  # noqa: PLC0415

    return int(asyncio.run(module.main_async(argv)) or 0)


def migrate(argv: list[str]) -> int:
    """Database migrations to head."""
    from automind.shared.infrastructure.db import migrate as module  # noqa: PLC0415

    module.main()
    return 0


COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "worker": worker,
    "replay": replay,
    "gold-load": gold_load,
    "parsers-migrate-v1": parsers_migrate_v1,
    "insight": insight,
    "baseline": baseline,
    "fit-physics": fit_physics,
    "migrate": migrate,
}


def _configure() -> None:
    from automind.delivery.bootstrap import configure_domain  # noqa: PLC0415

    configure_domain()
