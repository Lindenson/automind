"""The command table of `python -m automind.cli` and its dispatcher."""

from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable

# command -> (module, how to run it with argv)
COMMANDS: dict[str, tuple[str, str]] = {
    "worker": ("automind.acquisition.worker.__main__", "main(argv)"),
    "replay": ("automind.acquisition.replay.__main__", "main(argv)"),
    "baseline": ("automind.acquisition.reputation.baseline", "main_async(argv)"),
    "fit-physics": ("automind.acquisition.reputation.fit_physics", "main_async(argv)"),
    "gold-load": ("automind.acquisition.gold.load", "__main__"),
    "migrate": ("automind.shared.infrastructure.db.migrate", "main()"),
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        print("usage: python -m automind.cli {" + ",".join(COMMANDS) + "} [args]", file=sys.stderr)
        return 2
    module, how = COMMANDS[args[0]]
    return _run(module, how, args[1:])


def _run(module: str, how: str, argv: list[str]) -> int:
    if how == "__main__":
        import runpy  # noqa: PLC0415 - a module that runs from its `if __name__ == "__main__"` block

        sys.argv = [module, *argv]
        runpy.run_module(module, run_name="__main__")
        return 0
    entry: Callable[..., object] = getattr(importlib.import_module(module), how.split("(")[0])
    if how == "main()":
        entry()
        return 0
    result = entry(argv)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return int(result or 0)
