"""The turn graph keeps its node ids and transitions (spec 012 R4: pending interrupts resume by node id; the
restructuring of chat/dialog must not change the machine). The snapshot was taken before the restructuring."""

import json
from pathlib import Path

from automind.chat.dialog.graph import build_graph


def test_the_compiled_graph_has_the_recorded_nodes_and_edges():
    expected = json.loads((Path(__file__).parent / "graph_shape.json").read_text(encoding="utf-8"))
    g = build_graph().get_graph()
    assert sorted(g.nodes) == expected["nodes"]
    assert sorted([e.source, e.target, bool(e.conditional)] for e in g.edges) == expected["edges"]


def test_every_node_has_a_phase_and_the_confirmations_are_the_confirm_kinds():
    from automind.chat.dialog.graph import CONFIRMATIONS
    from automind.chat.dialog.phases import PHASE_OF, ConfirmKind

    nodes = {n for n in build_graph().get_graph().nodes if n not in ("__start__", "__end__")}
    assert nodes == set(PHASE_OF)
    assert {c.kind for c in CONFIRMATIONS} == {k.value for k in ConfirmKind}
