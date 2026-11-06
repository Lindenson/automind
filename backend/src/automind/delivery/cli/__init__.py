"""Delivery · cli: the stable command line of AutoMind (spec 012 research R14).

`python -m automind.cli <command> [args]` stays the same whatever the package tree looks like; each command hands its
arguments to the module that implements it. Commands: worker, replay, baseline, fit-physics, gold-load, migrate.

Depends on: the entry modules it names. Must not be imported by any other package (it is outermost).
Public API: see __all__.
"""

from automind.delivery.cli.main import COMMANDS, main

__all__ = ["COMMANDS", "main"]
