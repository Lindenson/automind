"""Delivery · automind.delivery.mcp: the MCP server that gives analyst agents deterministic tools over validated data.

Owns:
- `server` — the tools (`get_case`, `list_catalog`, `get_vehicle_specs`, `compute_metrics`, `score_criteria`,
  `simulate_drag_race`, `compute_tco`, `get_reliability`, `get_reviews`, …) and `main` (stdio transport).
Flow: delivery.web.app starts `python -m automind.delivery.mcp.server` as a subprocess → an analyst agent calls a
tool → the tool reads the database and computes; no model inside, no web fetch, no research started.
Depends on: chat (application, domain, infrastructure), shared.infrastructure, the MCP SDK.
Must not depend on: acquisition internals, observability. Must not be imported by other packages (tests only).
Public API: the modules in __all__ (run as a program, not imported).
"""

__all__ = ["server"]
