# Contract: shape of code (checked by scripts/check_structure.py and review)

## Module layout (FR-012)

```python
"""What this module is, in one or two sentences (what concept it owns)."""
from __future__ import annotations
# imports

# 1. contracts: DTOs, Protocols, type aliases, enums, contract constants
# 2. public functions / classes (the API of the module), most important first
# 3. private helpers (_name), in the order they are used
```
Limits: module ≤ 400 lines (allow-list for data modules), function ≤ 50 lines (target; > 80 fails).

## Use case (chat/application/usecases/<action>.py)

```python
class FindMore:
    """The person pressed "find it": research more for the chosen cars and areas, then answer."""

    def __init__(self, runner: TurnRunner, chats: ChatRepository) -> None: ...

    async def run(self, cmd: FindMoreCommand) -> TurnStarted:      # ≤ 30 lines
        chat = await self.chats.get(cmd.chat_id)
        preset = ResearchPreset.from_command(cmd)                    # mapper lives with the DTO
        return await self.runner.start(chat, preset)
```

## Service (*/application/services/<name>/)

```
identification/
  __init__.py        docs + __all__
  contracts.py       IdentifyRequest, Identified, Fallback(Protocol)
  service.py         class IdentificationService: __init__(ports) ; run() lists stages   (≤ 60 lines)
  stages/            normalise_name.py, catalogue_lookup.py, run_fallbacks.py, narrow_ladder.py, settle.py
  strategies/        catalogue.py, registered.py, open_world.py   (each implements Fallback)
```

```python
async def run(self, req: IdentifyRequest) -> Identified:
    name = normalise_name(req.car, self.vocabulary)
    hit = await catalogue_lookup(name, self.variants)
    if hit.settled:
        return settle(hit)
    found = await run_fallbacks(name, self.fallbacks)      # ordered strategies, first that answers wins
    return settle(narrow_ladder(found, req.case))
```

## Dialog state (review B3)

Graph state holds plain data only: nested values are `TypedDict`s; a DTO crosses the node boundary with
`Decision.from_state(state["decision"])` / `decision.to_state()`. Never put a class instance into the state.

## Dialog node (chat/dialog/nodes/*.py) — ≤ 30 lines, no business logic

```python
async def identify_node(state: TurnState, runtime: Runtime[TurnContext]) -> StateUpdate:
    case = await runtime.context.cases.load(state["chat_id"])
    result = await runtime.context.services.identification.run(IdentifyRequest.for_turn(case, state))
    return {"assessments": result.assessments_for_state()}
```

## Patterns and vocabulary (FR-016, revised after review I2)

```python
# chat/domain/vocabulary/distance.py — shared language patterns and word tables, by concept
PER_MONTH = re.compile(r"...")   # "1–2 тыс км в месяц", "1500 km/mes"

# a technical regex used once stays in its module, contracts section, named, with an example
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")   # "2026-11-06"
```
Forbidden: `re.compile` or a regex literal inside a function; word/phrase tables inside logic modules.
Justified size/limit exceptions: `scripts/structure_exceptions.txt` (path, limit, reason).

## Naming

Modules and packages are nouns of the concept (`case/`, `ladder/`, `confirmation.py`); use cases are verbs
(`find_more.py` / `FindMore`); stages are verb phrases (`catalogue_lookup`); no `utils.py`, `helpers.py`, `common.py`
(today's `nodes/common.py` becomes `dialog/context.py`).
