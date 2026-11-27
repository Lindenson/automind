"""The graph's contract as a whole (spec 014 T103, T105), from the types: every node has one; the owners registry is
exactly what the nodes declare; a key with several writers is a known one with the step that ends it; every key a
node requires is written on every path from START to it."""

from __future__ import annotations

from automind.chat.dialog.contract.models import required_reads
from automind.chat.dialog.contract.owners import OWNERS, RESET_NODE, RUNNER, Merge, may_write
from automind.chat.dialog.graph import build_graph, contracted_nodes
from automind.chat.dialog.state import PER_TURN_RESET, TurnState

STATE_KEYS = TurnState.__required_keys__ | TurnState.__optional_keys__
RUNNER_INPUT = frozenset({"chat_id", "turn_id", "user_text", "preset"})  # runner.py: the new turn's state
# today's keys with more than one writer (spec 014 B4); each is listed in owners.py with the step that ends it
SHARED = {"action", "blocks", "confirm_payload", "cost_approved", "done", "jobs", "limit_hit",
          "not_understood", "reply_text", "research_declined", "resume", "round", "route", "user_text"}  # fmt: skip


def _writers() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for n in contracted_nodes():
        for key in n.writes.model_fields:
            out.setdefault(key, set()).add(n.name)
    return out


def test_every_graph_node_has_a_contract() -> None:
    graph_nodes = {n for n in build_graph().get_graph().nodes if n not in ("__start__", "__end__")}
    assert [n.name for n in contracted_nodes()] and {n.name for n in contracted_nodes()} == graph_nodes
    assert len(contracted_nodes()) == len(graph_nodes) == 32


def test_every_state_key_has_an_owner_and_no_owner_names_an_unknown_key() -> None:
    assert set(OWNERS) == STATE_KEYS  # an ad-hoc key (e.g. provider_down) is a TurnState key with an owner


def test_the_registry_is_exactly_what_the_nodes_declare() -> None:
    declared = _writers()
    for key, owner in OWNERS.items():
        nodes = {w for w in owner.writers if w != RUNNER}
        reset = {RESET_NODE} if key in PER_TURN_RESET else set()
        assert declared.get(key, set()) - reset == nodes - reset, key
    for key, writers in declared.items():
        assert all(may_write(w, key) for w in writers), key


def test_request_kind_has_one_writer_the_request_as_code_settled_it() -> None:
    assert _writers()["request_kind"] - {RESET_NODE} == {"apply_delta"}


def test_the_case_version_is_written_by_load_case_only() -> None:
    """C2 (T110): nodes save the case through `TurnContext.save_case`, which keeps the version; the state holds only
    the version the turn started from."""
    assert _writers()["case_version"] == {RESET_NODE} and OWNERS["case_version"].writers == {RESET_NODE}


def test_keys_with_several_writers_are_the_known_ones_each_with_its_step() -> None:
    several = {k for k, o in OWNERS.items() if len(o.writers - {RESET_NODE}) > 1 and o.merge is Merge.REPLACE}
    several -= {"chat_id", "turn_id"}  # the runner's ids, repeated by load_case
    assert several == SHARED
    assert all(OWNERS[k].until for k in SHARED) and not any(o.until for k, o in OWNERS.items() if k not in SHARED)


def test_the_reducer_keys_are_append_only() -> None:
    assert {k for k, o in OWNERS.items() if o.merge is not Merge.REPLACE} == {"notices", "research_results"}
    assert OWNERS["research_results"].merge is Merge.APPEND_DELTA and OWNERS["notices"].merge is Merge.APPEND_ALL


def test_every_key_a_node_reads_or_writes_is_a_state_key() -> None:
    for n in contracted_nodes():
        if not n.sent:
            assert set(n.reads.model_fields) <= STATE_KEYS, n.name
        assert set(n.writes.model_fields) <= STATE_KEYS, n.name


def test_every_required_input_is_written_on_every_path_from_start() -> None:
    """A must-be-written analysis over the compiled graph: what a node is sure to find is what every predecessor
    is sure to leave (its own input plus the keys it writes on every branch)."""
    nodes = {n.name: n for n in contracted_nodes()}
    edges = [(e.source, e.target) for e in build_graph().get_graph().edges]
    leaves = {name: n.writes.always_written() | (PER_TURN_RESET.keys() if name == RESET_NODE else set())
              for name, n in nodes.items()}  # fmt: skip
    found: dict[str, frozenset[str]] = {name: frozenset(STATE_KEYS) for name in nodes}
    changed = True
    while changed:
        changed = False
        for name in nodes:
            preds = [s for s, t in edges if t == name]
            sure = [RUNNER_INPUT if s == "__start__" else found[s] | leaves[s] for s in preds]
            new = frozenset.intersection(*map(frozenset, sure)) if sure else frozenset()
            if new != found[name]:
                found[name], changed = new, True
    for name, n in nodes.items():
        if not n.sent:
            assert required_reads(n.reads) <= found[name], (name, required_reads(n.reads) - found[name])
