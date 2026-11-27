"""`python -m automind.delivery.cli.turn show <turn_id>` (spec 013 T035): the whole chain of one turn — the input,
what the model read, what code dropped and corrected, the intent (and, during the S3 shadow, what the old
interpreter read), then the policy's passes as `policy why` prints them (spec 015 T223). Exit 1 when the turn has
neither an understanding nor a policy pass; a database that cannot be reached raises `StoreUnavailable`."""

from __future__ import annotations

import argparse
import asyncio
import sys

from automind.chat.dialog.policy import render_why
from automind.chat.domain.understanding.render import render_understanding
from automind.chat.infrastructure.persistence.decisions import DecisionRepo
from automind.chat.infrastructure.persistence.understanding import UnderstandingRepo


async def main_async(argv: list[str]) -> int:
    """Print the turn; 0 when something is recorded for it, 1 otherwise."""
    ap = argparse.ArgumentParser(prog="turn", description="What a turn understood and why the dialog did what it did")
    ap.add_argument("command", choices=("show",))
    ap.add_argument("turn_id")
    args = ap.parse_args(argv)
    understood = await UnderstandingRepo().for_turn(args.turn_id)
    passes = await DecisionRepo().for_turn(args.turn_id)
    print(render_understanding(understood))
    print()
    print(render_why(passes))
    return 0 if understood is not None or passes else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async(sys.argv[1:])))
