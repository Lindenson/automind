# Spec 014 — Graph node contracts: typed input and output, one owner per state section

**Branch**: `014-node-contracts` · **Created**: 2026-11-26 · **Status**: Approved by the owner 2026-11-26 (§G)

**Input**: the owner's critique "11. Контракт узлов графа" (2026-11-26), checked against the code on the same day
(§B). Related: spec 013 (understanding, `Intent`, identification subgraph), spec 012 code-shape contract
(`specs/012-refactoring/contracts/code-shape.md`: ports, named steps, states not words, ≤ 200 lines/module).

**Goal in one sentence**: every graph node declares what it reads, what it writes and where it may go next, as types;
every part of the turn state has exactly one writer; a broken contract fails at once with the node and the key named.

---

## A. Why

The turn graph (`chat/dialog/graph.py`, 32 nodes: 17 plain + 5 confirmations × prepare/wait/apply) shares one flat
`TurnState` (`chat/dialog/state.py`, 38 keys, `total=False`). Nothing says which node needs which key or who may
write it. A missing key is a silent `None`; a key two nodes write is a race in meaning; a key forgotten in the reset
leaks into the next turn. Spec 013 adds more state (`intent`, identification trail) — on the current shape that makes
the problem bigger, so the contract comes first or together with it.

## B. Evidence (verified in code 2026-11-26)

| # | Problem | Where |
|---|---|---|
| B1 | Only 4 of 32 nodes have an output type: `ReadState`, `AppliedState` (`application/services/interpretation/contracts.py`), `AssessedState` (`assessment/contracts.py`), `PolicyState` (`nodes/understand.py`), all `TypedDict(total=False)`; 23 node functions return `dict[str, Any]` | `chat/dialog/nodes/*`, `confirmation.py` |
| B2 | No node declares its input: `state.get("…")` anywhere in its body, e.g. `request_kind` read in `report_writer.py:32`, `report_followup.py:54`, `nodes/research.py:143`, `nodes/understand.py:91,106`, `tracing.py:102` | |
| B3 | `TurnState(total=False)`: no key is required; absence is invisible | `state.py:35` |
| B4 | One key, several writers: `request_kind` by `interpret` (`ReadState`) and `apply_delta` (`AppliedState`); `action` is written in 16 places; `reply_text`/`blocks` by every terminal and some confirmations | |
| B5 | A key outside the schema: `provider_down` is put into the final state by `turn/execution.py:114` and read by `turn/outcome.py:69`; `TurnState` has no such key | |
| B6 | Hand-written reset: `PER_TURN_RESET` lacks `interpretation`, so the previous turn's interpretation stays in the state; it also lacks `preset`, `case_version`, `user_text` (set by the runner / `load_case`, but nothing enforces it); it sets `language: "en"` for every turn (spec 013 B4: "переформулируйте" answered in English) | `state.py:73` |
| B7 | Node settings as a bare bool: `("interpret", interpret_node, True)` — `True` means "retry on a provider failure" | `graph.py` `NODES` |
| B8 | The case file is read from the DB in every node: `load_case(c)` 25 times in `chat/dialog`; `save_case` appends `max(version)+1` read at save time, so a write based on a stale read is not detected (only a truly concurrent insert hits the PK) | `context.py:22-31`, `infrastructure/persistence/repositories.py:165` |
| B9 | A retried node has side effects before its model call: `report_node` runs `persist()` (computations) before `write_report` (LLM, `LLM_RETRY`); `answer_node` persists a race before `write_answer` — a retry repeats the writes | `nodes/report.py:27-58` |
| B10 | Routing by flags: `route_after_interpret`, `route_after_apply`, `route_after_apply` (confirmations) read `route`/`done` keys a node set for the router | `graph.py`, `nodes/*` |

Correction to the critique: `done` itself is set in one place only; the "written by almost any node" holds for
`action`, `reply_text`, `blocks`.

## C. Goals

1. **Typed node contract**: each node has a frozen `…In` model (the sections it reads, required unless `Optional`) and
   a frozen `…Out` model (`extra="forbid"`, the sections it writes); the node body sees typed objects only.
2. **One owner per state section**; reducer sections (`notices`, `research_results`) are append-only for everyone.
3. **Automatic per-turn reset**: sections are marked `chat` or `turn` lifetime; `begin_turn` clears every `turn`
   section; no hand-written list.
4. **Named node settings**: `retry=Retry.PROVIDER | Retry.NONE`; a retried node has no side effect before its model
   call (checked by a test fake that fails on a store write before the first LLM call of a retried node).
5. **The case file once per turn**: `ctx.case()` reads it on first use and caches it for the `ainvoke`;
   `ctx.save_case(case, changes)` saves with the expected version; a stale write raises `VersionConflict`.
6. **Contract checked and documented from the types**: graph-shape test (every required input section has a writer on
   every path from START), owners test, and `python -m automind.chat.dialog.contract` printing
   "node · reads · writes · next".
7. **Behaviour unchanged** until step 3; checkpoints of waiting turns keep resuming (node ids never change).

Non-goals: no change of what the policy decides; no new node; the policy stays a router visible in `graph.py`.

## D. Design

### D1. State sections and owners

| Section | Contents | Owner (writer) | Lifetime |
|---|---|---|---|
| `chat` | chat language, fingerprint of the last report | terminal nodes, through `reply` | chat |
| `input` | chat_id, turn_id, user_text, ui_action / preset, resume answer | the runner (before the graph) | turn |
| `understanding` | `Intent` or `AskBack` (spec 013); before 013 S4: today's `interpretation` + `request_kind` | `understand` (`interpret` alias) | turn |
| `applied` | new case version, change log, not understood car keys, picked | `apply_changes` (`apply_delta` alias) | turn |
| `assessment` | car states, research plan, cost estimate, feasibility | `assess` | turn |
| `decision` | `DecisionHistory` (spec 015 T230): this turn's passes; pass number = length; no `hops` | `policy` | turn |
| `confirm` | payload of the question, the answer, approved / declined flags | `prepare_*` / `apply_*` of that confirmation | turn |
| `research` | jobs, round, limits, limit extensions, research done | research nodes | turn |
| `research_results` | results of the parallel jobs (reducer: append) | `research_job` | turn |
| `notices` | notices (reducer: append) | any node, append only | turn |
| `reply` | text, blocks, action (the turn's outcome kind — the only `action`), fingerprint, outcome (incl. `provider_down`) | terminal nodes | turn |

`provider_down` and every other key now outside `TurnState` become fields of a section. The registry of owners is
data (`chat/dialog/contract/owners.py`), read by the decorator and the tests.

### D2. The node decorator

```python
class UnderstandIn(BaseModel):
    model_config = ConfigDict(frozen=True)
    input: TurnInput
    chat: ChatMemory

class UnderstandOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    understanding: Understood | AskBack

    def next(self) -> Literal["apply_changes", "reply"]:
        return "reply" if isinstance(self.understanding, AskBack) else "apply_changes"

@node("understand", reads=UnderstandIn, writes=UnderstandOut, retry=Retry.PROVIDER)
async def understand(inp: UnderstandIn, ctx: TurnContext) -> UnderstandOut: ...
```

`@node` does, once for all nodes:
1. builds `…In` from the state; a missing required section → `ContractError("understand: no input")`;
2. calls the function with typed objects (no `state.get`, no `model_validate` in a node);
3. checks the output writes only the node's own sections (owners registry);
4. dumps the output to JSON for the checkpoint and returns `Command(update=…, goto=out.next())` when the output
   defines `next()` (step 4); otherwise a plain update;
5. records the node in the trace (replaces `traced`).

A violation is an error in tests; in production during the transition a log line with node + key and the metric
`graph_contract_violation_total{node,key,kind}`, then an error (owner's switch in config after a week at 0).

### D3. Case file once per turn

`TurnContext.case()` (lazy, cached per `ainvoke`), `TurnContext.save_case(case, changes, publish=…)` with the expected
version (store: `save_version(chat_id, data, expected=version)`; a mismatch → `VersionConflict`, distinct from
`CaseStoreUnavailable`). After a resume (`Command(resume)`) or a restart the cache is empty: `TurnContext` is created per
`ainvoke`. `load_case`/`save_case` free functions are removed when no node uses them.

### D4. Routing

Nodes whose next step is their own decision return it (`Out.next()` → `Command(goto)`): interpret/understand,
apply_changes, the confirmations' apply, select_candidates. The `route`/`done` router keys disappear. The policy stays
a conditional edge: its path map and router are built from `ROUTES` (spec 015 T203); `POLICY_ROUTES` is deleted. Its
choice is the centre of the graph.

### D5. Checkpoints

Node ids never change (`tests/graph/graph_shape.json`). Step 3 changes the state shape: a transition adapter reads
the flat keys of an old checkpoint into sections (one pure function, unit-tested on real blobs from
`scripts/check_checkpoints.py`); new keys only add. A waiting turn on the old shape resumes on the new code
(proved on pre-prod blobs before the deploy).

### D6. Relation to spec 013

- Steps 1–2 (decorator over the flat keys, `ctx.case()`) are independent of 013 and can go before 013 S3.
- Step 3 (sections + automatic reset) goes with 013 S4 (switch to `Intent`): the `understanding` section is born typed,
  `request_kind`/`interpretation` disappear there instead of being migrated twice; `language` moves to `chat`
  (fixes the "en" reset of B6 together with 013's language hysteresis).
- Step 4 (`Command(goto)`) goes with 013 S5 (identification subgraph), whose nodes are written in the new shape.

## E. Testing and acceptance

- Unit: `@node` (missing section, foreign section write, extra key, retry flag), owners registry, transition adapter,
  `ctx.case()` caching and `VersionConflict`.
- Graph: shape test from the types (every required input has a writer on every path from START); owners test (no
  two writers except reducer sections); retry-purity test (a retried node writes nothing before its first model call).
- All golden dialogues and graph tests unchanged after each step; behaviour diff "differs 0" for steps 1, 2, 4;
  step 3 differs only where the reset leak is fixed (listed in the PR).

Acceptance:
- [ ] Every node (32) has `…In`/`…Out`; 0 `dict[str, Any]` node returns; 0 `state.get` in `chat/dialog/nodes`.
- [ ] Owners test green; `provider_down` and every other ad-hoc key is in a section.
- [ ] `PER_TURN_RESET` gone; a test proves every `turn` section is empty at the start of a turn.
- [ ] `load_case` calls in nodes: 0; a stale save raises `VersionConflict` (test).
- [ ] `report`/`answer` persist after the model call (or are not retried); retry-purity test green.
- [ ] `python -m automind.chat.dialog.contract` output committed in `specs/014-node-contracts/contract.md`; a test
      fails when it differs from the code.
- [ ] `check_checkpoints.py` on prod blobs: old waiting turns resume after step 3.

## F. Steps (one PR each)

| # | Step | When |
|---|---|---|
| C1 | `@node` + `Retry` over today's flat keys: In/Out for all 32 nodes, owners registry, contract CLI, shape/owners tests; finds ad-hoc keys (`provider_down`) and adds them to the state | now, beside 013 S1–S2 |
| C2 | `ctx.case()` / `ctx.save_case` with the expected version, `VersionConflict`; retry purity of report/answer | after C1 |
| C3 | Sections + `begin_turn` automatic reset + checkpoint adapter | with 013 S4 |
| C4 | `Command(goto)` from `Out.next()` instead of `route`/`done` routers; policy stays a router | with 013 S5 |

## G. Owner's decisions (2026-11-26)

1. Order: C1–C2 now, beside spec 013 S1–S2; C3 with 013 S4; C4 with 013 S5 — "да, порядок ок".
2. A violation in production during the transition: log + metric, strict after a week at 0 (the proposal; owner's "да").
3. `VersionConflict` in a turn: the node is retried once from a fresh read of the case; a second conflict fails the
   turn with a notice — "при конфликте повторять один раз".
