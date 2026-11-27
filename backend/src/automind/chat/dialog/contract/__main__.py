"""`python -m automind.chat.dialog.contract`: print the contract table of the turn graph (spec 014 T106).

cd backend && uv run python -m automind.chat.dialog.contract > ../specs/014-node-contracts/contract.md
"""

from __future__ import annotations

from automind.chat.dialog.contract.table import render
from automind.chat.dialog.graph import build_graph, contracted_nodes


def main() -> None:
    """Print the table for the current code (nodes in graph order, edges of the compiled graph)."""
    edges = [(e.source, e.target, bool(e.conditional)) for e in build_graph().get_graph().edges]
    print(render(contracted_nodes(), edges), end="")


if __name__ == "__main__":
    main()
