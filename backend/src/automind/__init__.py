"""AutoMind: helps a person choose a car from validated data (spec 012 tree, five areas).

Areas (each package documents itself in its own `__init__.py`):
- `chat` — the conversation: case file, dialog machine, use cases, the answer; orders data only via acquisition.api.
- `acquisition` — the data engine: search, fetch, parse, validate, store; its worker, agents, registry, gold.
- `observability` — sees how both cycles do: turn outcomes, metrics, the insight loop over both journals.
- `shared` — the kernel both cycles speak: vehicle identity/specs/units, evidence, research order, contracts,
  metering, and the common infrastructure (config, database, LLM gateway).
- `delivery` — adapters to the outside world: web (FastAPI app, composition root), MCP server, command line.
`cli` — the stable `python -m automind.cli <command>` entry point (forwards to delivery.cli).
"""

__all__ = ["acquisition", "chat", "cli", "delivery", "observability", "shared"]
