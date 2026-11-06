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
