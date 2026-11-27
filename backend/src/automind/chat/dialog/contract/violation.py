"""What a broken node contract does (spec 014 §G2, T107): an error in tests, a log line and a metric in production.

The switch is `AUTOMIND_CONTRACT_STRICT` (`Settings.contract_strict`): on in the tests (tests/conftest.py), off in
production during the transition, where a violation is logged with node, key and kind and counted in
`automind_graph_contract_violation_total{node,key,kind}`; the turn goes on. The owner turns production strict after
a week at 0 (spec 014 T132).
"""

from __future__ import annotations

import logging
from enum import StrEnum

from automind.shared.infrastructure.config.settings import settings
from automind.shared.infrastructure.metrics import prom

log = logging.getLogger(__name__)


class ViolationKind(StrEnum):
    """How a node broke its contract."""

    MISSING = "missing"  # a required input key is not in the state
    INVALID = "invalid"  # an input key holds a value of another type
    UNKNOWN = "unknown"  # a node reads or writes a key the turn state does not declare (an ad-hoc key)
    FOREIGN = "foreign"  # a node declares a write of a key it does not own (contract/owners.py)
    APPEND = "append"  # a write of an append-only key dropped earlier items
    TYPE = "type"  # a node body returned something other than its Out model


class ContractError(Exception):
    """A node broke its contract (strict mode). `node`, `key` and `kind` say where and how."""

    def __init__(self, node: str, key: str, kind: ViolationKind, detail: str = "") -> None:
        super().__init__(f"{node}: {kind} {key}" + (f" ({detail})" if detail else ""))
        self.node, self.key, self.kind = node, key, kind


def strict() -> bool:
    """True when a violation raises (tests; production after the owner's switch)."""
    return settings().contract_strict


def violated(node: str, key: str, kind: ViolationKind, detail: str = "") -> None:
    """Report a violation: raises `ContractError` in strict mode; otherwise logs it and counts the metric (never
    raises, so a production turn goes on exactly as before the contract existed)."""
    if strict():
        raise ContractError(node, key, kind, detail)
    log.warning("graph.contract_violation node=%s key=%s kind=%s %s", node, key, kind, detail)
    prom.inc("graph_contract_violations", node=node, key=key, kind=kind)
