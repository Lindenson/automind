"""The journal and the gates wired over the database, the worker's queue and gauges, the agents' budgets and the
config (`agents.yaml` gates). Built per task: the config is read when the task starts."""

from __future__ import annotations

from collections.abc import Mapping

from automind.acquisition.domain import gates, relevance_audit
from automind.acquisition.gates.application.journal import ChangeJournal
from automind.acquisition.gates.application.replay_gate import ReplayGate
from automind.acquisition.gates.application.shadow_gate import ShadowGate
from automind.acquisition.gates.application.watch import Watch
from automind.acquisition.gates.infrastructure.change_store import ChangeRepo
from automind.acquisition.gates.infrastructure.engine_ports import AgentBudgets, EngineEvents, SystemClock, WorkerQueue
from automind.acquisition.gates.infrastructure.experiments import ExperimentRepo
from automind.acquisition.gates.infrastructure.lever_state import LeverStateRepo
from automind.acquisition.gates.infrastructure.measure import PageMeasure
from automind.acquisition.gates.infrastructure.objects import ObjectRepo
from automind.acquisition.gates.infrastructure.relevance_measure import RelevancePages
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.infrastructure import overrides


def change_journal() -> ChangeJournal:
    """The change journal."""
    return ChangeJournal(ChangeRepo(), ObjectRepo(), LeverStateRepo(), WorkerQueue(), EngineEvents(), SystemClock())


def replay_gate() -> ReplayGate:
    """The replay gate."""
    return ReplayGate(change_journal(), ExperimentRepo(), PageMeasure(), RelevancePages(), AgentBudgets(),
                      WorkerQueue(), EngineEvents(), SystemClock(), gate_config(), relevance_config())  # fmt: skip


def shadow_gate() -> ShadowGate:
    """The shadow gate."""
    return ShadowGate(change_journal(), ChangeRepo(), ExperimentRepo(), PageMeasure(), RelevancePages(),
                      AgentBudgets(), WorkerQueue(), EngineEvents(), SystemClock(), gate_config(),
                      relevance_config())  # fmt: skip


class LiveShadowFeed:
    """The live pipeline's feed of the shadow gate (`AcqPorts.shadow`): a gate built per call, like `shadow_gate()`."""

    async def notify_extracted(self, prompt_name: str | None, snapshot_ids: list[str]) -> int:
        """Queue the extracted pages for the prompt and extractor-model changes in shadow."""
        return await shadow_gate().notify_extracted(prompt_name, snapshot_ids)

    async def notify_read(self, read: Mapping[str, str]) -> None:
        """Queue the snapshots the site readers read (id → version key) for the parser and rule changes in shadow;
        the gate is built only while such a change is in shadow."""
        if overrides.in_shadow("parser") or overrides.in_shadow("rule"):  # spec 011 T102
            await shadow_gate().notify_read(read)


def watch() -> Watch:
    """The watch after acceptance."""
    return Watch(change_journal(), ChangeRepo(), ExperimentRepo(), PageMeasure(), WorkerQueue(), SystemClock(),
                 gate_config())  # fmt: skip


def gate_config() -> gates.GateConfig:
    """The gates' thresholds (`agents.yaml`)."""
    return gates.GateConfig.from_mapping(acq_config.agents_config())


def relevance_config() -> relevance_audit.RelevanceGateConfig:
    """The relevance keyword gate's thresholds (`agents.yaml`)."""
    return relevance_audit.RelevanceGateConfig.from_mapping(acq_config.agents_config())
