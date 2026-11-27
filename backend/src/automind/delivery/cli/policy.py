"""`python -m automind.delivery.cli.policy why <turn_id> [--replay] | export <turn_id>` (spec 015 T223).

`why` prints every recorded pass of the turn: each rule asked and why, the rule that decided, the action and the
node. `--replay` decides each pass again from the case at its version and the stored config and says whether today's
rules decide the same. `export` prints the passes as YAML golden fixtures (the person's words and region masked) for
`tests/unit/chat/dialog/policy/golden/`. Exit 1 when the turn has no recorded pass; a database that cannot be
reached raises `StoreUnavailable`."""

from __future__ import annotations

import argparse
import asyncio
import sys

import yaml

from automind.chat.dialog.policy import Decision, fixture, render_why, replay
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import DecisionRecord, PolicyConfig
from automind.chat.infrastructure.persistence.decisions import DecisionRepo
from automind.chat.infrastructure.persistence.repositories import CaseRepo
from automind.shared.contracts.json import JsonObject


async def main_async(argv: list[str]) -> int:
    """Run one command; 0 when the turn has recorded passes, 1 otherwise."""
    ap = argparse.ArgumentParser(prog="policy", description="Why the dialog's policy did what it did in a turn")
    ap.add_argument("command", choices=("why", "export"))
    ap.add_argument("turn_id")
    ap.add_argument("--replay", action="store_true", help="decide every pass again with today's rules")
    args = ap.parse_args(argv)
    decisions = DecisionRepo()
    records = await decisions.for_turn(args.turn_id)
    if not records:
        print(render_why(records), file=sys.stderr)
        return 1
    if args.command == "export":
        fixtures = [fixture(r, await _case(r), await _config(decisions, r)) for r in records]
        print(yaml.safe_dump(fixtures, allow_unicode=True, sort_keys=False), end="")
        return 0
    replays = await _replays(decisions, records) if args.replay else None
    print(render_why(records, replays))
    return 0


async def _replays(decisions: DecisionRepo, records: list[DecisionRecord]) -> dict[int, Decision]:
    out: dict[int, Decision] = {}
    for r in records:
        out[r.pass_no] = replay(r, await _case(r), PolicyConfig.model_validate(await _config(decisions, r)))
    return out


async def _case(r: DecisionRecord) -> CaseFile:
    data = await CaseRepo().get(r.chat_id, r.case_version)
    return CaseFile.model_validate(data) if data else CaseFile()


async def _config(decisions: DecisionRepo, r: DecisionRecord) -> JsonObject:
    config = await decisions.config(r.config_hash)
    if config is None:
        raise LookupError(f"config {r.config_hash} of turn {r.turn_id} is not stored")
    return config


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async(sys.argv[1:])))
