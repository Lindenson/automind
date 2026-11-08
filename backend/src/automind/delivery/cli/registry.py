"""The source registry's commands: `seed` (favourites and the 009 survey; idempotent, so it adds favourites added to
`config/sources.yaml` after the first start) and `review --once` (one review now, only with `registry.autonomy:
true`; the worker runs the daily one, `python -m automind.cli worker --once registry_review`). Prints JSON.

    python -m automind.delivery.cli.registry seed
    python -m automind.delivery.cli.registry review --once
"""

from __future__ import annotations

import asyncio
import json
import sys

from automind.delivery import registry
from automind.delivery.bootstrap import configure_domain


def main(argv: list[str]) -> int:
    """Run one command; prints this module's usage for anything else."""
    if argv[:1] == ["seed"]:
        configure_domain()
        print(json.dumps(asyncio.run(registry.seed()), ensure_ascii=False))
        return 0
    if argv[:1] == ["review"] and "--once" in argv:
        configure_domain()
        print(json.dumps(asyncio.run(registry.review_now()), ensure_ascii=False))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
