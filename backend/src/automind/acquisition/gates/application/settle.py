"""A gate's final verdict applied (spec 011 US5): the change closed in the journal and its experiment decided — its
pages unpinned unless another open experiment still holds them."""

from __future__ import annotations

from datetime import datetime

from automind.acquisition.domain import gates
from automind.acquisition.gates.application.journal import ChangeJournal
from automind.acquisition.gates.application.ports import Experiments
from automind.shared.contracts.json import JsonObject

DECISION = {
    gates.GateVerdict.PASS: "accepted",
    gates.GateVerdict.FAIL: "rejected",
    gates.GateVerdict.ABANDON: "abandoned",
}


async def settle(journal: ChangeJournal, experiments: Experiments, change_id: str, gate: str, verdict: gates.Verdict,
                 old: gates.Metrics, new: gates.Metrics, extra: JsonObject, now: datetime) -> None:  # fmt: skip
    """Accept (shadow only), reject or abandon the change at `gate`, then decide its experiment."""
    if verdict.verdict == gates.GateVerdict.PASS:
        await journal.accept(change_id, verdict, old, new, extra)
    elif verdict.verdict == gates.GateVerdict.FAIL:
        await journal.reject(change_id, gate, verdict, old, new, extra)
    else:
        await journal.abandon(change_id, gate, verdict, old, new, extra)
    await experiments.decide(change_id, DECISION[verdict.verdict], now)
