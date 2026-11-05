# Contract: Acquisition interface (`automind.acquisition.api`)

The only engine module the chat (`automind.application`, `automind.orchestration`, `automind.domain`) may import
(import-linter contract `chat-uses-acquire-only`, FR-005, FR-006). Everything else under `automind.acquisition` is
internal. Live calls run in the caller's process within the caller's deadline and budget (research R5).

```python
from datetime import datetime
from enum import StrEnum
from typing import Awaitable, Callable, Literal
from pydantic import BaseModel

Emit = Callable[[str, str], Awaitable[None]]        # (stage, text) — progress for the chat; unchanged from today


class Need(StrEnum):
    CACHED = "cached"          # read the engine's stored data only; never search or fetch
    STANDARD = "standard"      # cache-first; research what is missing or stale (today's round 0)
    FOLLOW_UP = "follow_up"    # a gap round (today's round > 0)
    FRESH = "fresh"            # "find it": past the search cache, wider queries (today's fresh)
    ESCALATE = "escalate"      # the registry's other markets too (today's escalate)
    REFRESH = "refresh"        # prefetch: like STANDARD, background budget, no emit


class AcquireRequest(BaseModel):
    job_id: str                     # research_jobs.id (chat) or acq_tasks.id (prefetch)
    variant_id: str
    kinds: list[str]                # areas: specs, engineering, price, maintenance, ... (one per call today)
    need: Need = Need.STANDARD
    round: int = 0
    deadline: datetime | None = None    # the job timeout; the engine stops starting new pages after it
    car_year: int | None = None


class SourceRef(BaseModel):
    domain: str
    url: str
    quote: str                      # verbatim excerpt (I)
    source_type: str
    unverified: bool = False        # candidate source: "unverified source", half weight (US7)
    producer: Literal["reader", "extractor", "dataset", "user"]
    producer_version: str | None    # km77@v1 / extract_specs@v3
    model: str | None


class AcquiredValue(BaseModel):
    attribute: str
    value: float | str | None
    unit: str | None
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    provenance: str                 # IV classes
    sources: list[SourceRef]


class Tried(BaseModel):
    domain: str
    outcome: Literal["accepted", "rejected", "robots", "junk", "empty", "error", "not_reached"]
    reason: str | None = None


class KindResult(BaseModel):          # == today's JobResult, plus what was tried
    kind: str
    ok: bool = True
    docs: int = 0
    accepted: int = 0
    rejected: int = 0
    minimum_met: bool = False
    error: str | None = None
    hits: list[dict] = []             # unchanged shape (area_hits)
    tried: list[Tried] = []           # for "no data — tried: …" (FR-022)
    stage_versions: dict[str, str] = {}


class AcquireResult(BaseModel):
    job_id: str
    variant_id: str
    round: int
    kinds: list[KindResult]
    values: list[AcquiredValue] = []  # filled when the caller asks for them (read path); research uses spec_values


async def acquire(req: AcquireRequest, emit: Emit, *, ports: "AcqPorts | None" = None) -> AcquireResult: ...
#   raises BudgetExceeded (unchanged) — the caller pauses and asks the user; any other error → KindResult(ok=False)

# Read model (moved from application/research.py, same semantics)
async def missing_critical(variant_id: str, powertrain: str | None = None) -> list[str]: ...
async def last_done(variant_ids: list[str]) -> dict[str, dict]: ...
async def ev_counts(variant_ids: list[str]) -> dict: ...
async def powertrains(variant_ids: list[str]) -> dict[str, str | None]: ...
async def registry_done(variant_ids: list[str]) -> dict[str, dict]: ...
async def unmet_areas(variant_ids: list[str]) -> dict[str, set[str]]: ...
async def gearbox_families_mixed(variant_id: str) -> bool: ...          # accepted_gearboxes + mixed_families

# Challenge path (application/challenge.py, repair.py)
async def recheck_value(variant_id: str, attribute: str, *, claim_ids: list[str]) -> "RecheckResult": ...
async def reselect(variant_id: str) -> None: ...

# Identity helpers (strangler S8: lineup.py, versions.py, resolve.py stop searching/fetching themselves)
async def lineup(make: str) -> "Lineup | None": ...
async def versions(make: str, model: str, generation: str | None) -> "VersionsOut | None": ...
async def generation_hints(query: str) -> list["WebHint"]: ...
```

## Guarantees

- `acquire()` never raises except `BudgetExceeded`; one failing kind never fails the others (FR-023 of spec 002).
- With `registry.autonomy: false` and no accepted agent change, results equal today's `research.run_job` for the same
  inputs (golden dialogues g1–g12 unchanged after each strangler step, FR-007).
- Every value written records producer, producer version, model and snapshot (FR-002).
- `Need.CACHED` performs no search, fetch or model call.
- The read-model functions perform no network or model call.
- The chat never receives raw page text; `quote` is the stored excerpt only.

## Ports

`acquisition/ports.py: AcqPorts` (search, page store, readers, llm, registry, metrics, ref, market_facts, budget) is
built by `acquisition/infrastructure/wiring.py: live_acq_ports()` and cached per process; tests pass fakes. After
strangler step S8 the chat's `application/ports.py: Ports` no longer has `search`, `pages` or `readers`; it has
`acquisition: AcquisitionPort` (a Protocol mirroring the functions above) so graph tests can fake the engine.
