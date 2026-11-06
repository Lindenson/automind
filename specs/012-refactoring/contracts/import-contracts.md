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
| `observability-is-a-leaf` (new) | forbidden | `chat`, `acquisition`, `shared` ↛ `automind.observability` |
| `observability-reads-only` (new) | forbidden | `observability` ↛ `chat.application`, `chat.dialog`, `acquisition.*` except `acquisition.api` |
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

## Not visible to import-linter (checked by scripts/check_structure.py)

- **Raw SQL to another area's tables**: `scripts/table_owners.yaml` maps every table to its area; SQL strings
  (text(), f-strings, `.execute("…")`) are scanned for table names; a hit outside the owner area fails, except
  `observability` reading journals (listed per table).
- **Classes in graph state**: `check_checkpoints.py` (R4) — no `automind.` path in any checkpoint blob.

## Engine budget seam (R12)

```python
# acquisition/api.py
class Budget(Protocol):
    def charge(self, eur: float) -> None: ...      # raises BudgetExhausted
    def exhausted(self) -> bool: ...

async def acquire(req: AcquireRequest, emit: Emit, *, budget: Budget, ports: …) -> AcquireResult: ...
async def car_data(variant_id: int) -> CarData: ...   # read model for the chat (R13)
```
