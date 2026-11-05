# Contract: Registry port (`automind.acquisition.registry.api`)

The only module of the registry the chat cycle (`application/research.py`) may import (import-linter contract `registry-boundary`).

```python
class PlannedSource(BaseModel):
    domain: str
    market: str            # market whose queries should target it, or "ANY"
    priority: int          # 0 = first; same scale as today's favourite priority
    status: Literal["active", "candidate", "retired"]
    unverified: bool       # candidate → label "unverified source", half weight

class Plan(BaseModel):
    area: str
    sources: list[PlannedSource]   # ordered; candidates limited to cfg.candidate_slots
    skip: set[str]                 # domains not to read for this area (blocked/degraded)

class Attempt(BaseModel):
    domain: str; area: str; market: str
    job_id: str | None; variant_id: str | None; url: str
    outcome: Literal["accepted", "rejected", "robots", "junk", "empty", "error"]
    reason: str | None = None
    values: int = 0
    cost_eur: float = 0.0
    via_learned_query: bool = False   # keeps the spec-007 "no self-reinforcement" rule

class RegistryPort(Protocol):
    async def plan(self, area: str, markets: list[str], make: str | None) -> Plan: ...
    async def record(self, attempts: list[Attempt]) -> None: ...          # never raises into research
    async def signal(self, s: TruthSignalIn) -> None: ...                  # challenge, bad source, replacement
```

Guarantees:
- with `registry.autonomy: false` the plan equals today's behaviour: favourites with their YAML priority, then learned domains by the spec-007 rule; `skip` = deny-list only;
- `plan()` never returns a blocked, classifieds or deny-listed domain;
- `record()` and `signal()` swallow and log their own errors (a job never fails over the registry, as today's `_record_learned`).
