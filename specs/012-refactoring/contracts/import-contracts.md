# Contract: import boundaries (backend/.importlinter, target)

Existing 10 contracts are rewritten to the new paths in the move step (same meaning, never weaker), then the
following set is reached step by step. "→" = may import.

## Areas

| Contract | Type | Rule |
|---|---|---|
| `shared-is-kernel` | forbidden | `automind.shared` ↛ `chat`, `acquisition`, `delivery` |
| `chat-uses-acquire-only` (kept, retargeted) | forbidden | `automind.chat` ↛ `automind.acquisition.*` except `automind.acquisition.api` |
| `engine-knows-no-chat` (new) | forbidden | `automind.acquisition` ↛ `automind.chat` (fixes `pipeline/relevance.py` → application/usage) |
| `delivery-is-outermost` (new) | forbidden | nothing imports `automind.delivery` |
| `web-uses-facades` (kept, retargeted) | forbidden | `delivery.web` ↛ engine internals (only `acquisition.api`, `acquisition.admin`, `acquisition.registry.api`) |

## Layers inside `chat` (type `layers`, top may import bottom)

```
chat.application.usecases
chat.dialog
chat.application.services
chat.application.ports
chat.domain
```
`chat.infrastructure` implements `chat.application.ports`; only `delivery.web.app` (composition root) wires it.
No `ignore_imports` (today: 12 legacy lines for compose, resolve, repair, challenge, backfill, lineup).

## Purity (type `forbidden`)

- `chat.domain`, `acquisition.domain`, `acquisition.*.domain`, `shared.vehicle`, `shared.evidence`,
  `shared.research_order` ↛ langgraph, langchain*, fastapi, sqlalchemy, httpx, mcp, any `*.infrastructure`,
  `*.application`, `*.dialog`.
- `chat.dialog` ↛ sqlalchemy, fastapi, `chat.infrastructure` (nodes reach data only through services/ports).
- `chat.application` ↛ langgraph, fastapi, sqlalchemy, `chat.infrastructure`, `chat.dialog`.
- `acquisition.parsing.readers` pure core (kept from spec 011 "pure cores").

## Package APIs

`independence`/`forbidden` contracts between sibling engine packages are kept from spec 011; cross-package access
inside an area goes through the target package's `__init__` exports (checked by `scripts/check_structure.py`
rule "no import of a private module `_x` or of a non-exported name across packages").
