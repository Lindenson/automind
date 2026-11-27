"""The committed contract table (spec 014 T106) is the one the code renders: regenerate it with
`cd backend && uv run python -m automind.chat.dialog.contract > ../specs/014-node-contracts/contract.md`."""

from __future__ import annotations

from pathlib import Path

from automind.chat.dialog.contract.table import render
from automind.chat.dialog.graph import build_graph, contracted_nodes

TABLE = Path(__file__).resolve().parents[6] / "specs" / "014-node-contracts" / "contract.md"


def test_the_committed_contract_table_is_current() -> None:
    edges = [(e.source, e.target, bool(e.conditional)) for e in build_graph().get_graph().edges]
    assert TABLE.read_text(encoding="utf-8") == render(contracted_nodes(), edges), (
        "specs/014-node-contracts/contract.md is stale: regenerate it with python -m automind.chat.dialog.contract"
    )


def test_every_node_is_a_row_of_the_table() -> None:
    text = TABLE.read_text(encoding="utf-8")
    assert all(f"| {n.name} |" in text for n in contracted_nodes())
