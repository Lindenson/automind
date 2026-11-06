"""Delivery · automind.delivery: adapters to the outside world: the web app, the MCP server, the command line.

Owns:
- `web` — the FastAPI app (composition root), REST, the chat WebSocket, the admin API, /metrics, access rules.
- `mcp` — the MCP server: deterministic read-and-compute tools for analyst agents (stdio).
- `cli` — the stable command line `python -m automind.cli <command>` and its dispatcher.
Flow: a request arrives (HTTP, WebSocket, MCP call, command) → the adapter checks access and parses it → it calls the
chat, the acquisition facades or observability → it returns the result. No business logic lives here.
Depends on: chat, acquisition (only its facades: api, admin_api, registry.api), observability, shared.
Must not be imported by any other package (target `delivery-is-outermost`).
Public API: the subpackages in __all__ (entry points; nothing else should import them).
"""

__all__ = ["cli", "mcp", "web"]
