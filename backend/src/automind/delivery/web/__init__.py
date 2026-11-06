"""Delivery · automind.delivery.web: the HTTP and WebSocket face of AutoMind, and its composition root.

Owns:
- `app` — the FastAPI app: wires config, DB, checkpointer, MCP tools, ports and the `ChatRunner`; mounts the routers
  and the built frontend; starts the background loops (composition root).
- `ws` — the chat WebSocket, protocol v2: user messages, confirms, find, car edits in; EventBus events out.
- `rest` — REST under /api/v1: health, chats, messages, case file, weights (secrets never returned).
- `admin` — the admin API: top problems, sources, parsers, changes, accuracy, engine status (admin token).
- `metrics` — GET /metrics for Prometheus, served from memory (token or allowed networks).
- `access` — anonymous owner per browser (HttpOnly cookie, hashed), same-site origin check, admin check.
Flow: `app` builds the ports at startup → a browser connects to `ws` / `rest` → `access` checks owner and origin →
the chat runner handles the turn and streams events back.
Depends on: chat, observability, shared, acquisition.api, acquisition.admin_api and four registry modules (api,
application.seed, domain.model, domain.seed_rules).
Must not depend on: acquisition engine internals (import contract `api-uses-engine-facades`).
Note: `app` still starts the acquisition retention loop directly (explicit ignore in .importlinter; moves to the
worker in S12).
Public API: the modules in __all__ (`app:app` is the ASGI entry point; nothing else should import them).
"""

__all__ = ["access", "admin", "app", "metrics", "rest", "ws"]
