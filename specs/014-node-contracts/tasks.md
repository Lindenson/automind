# Tasks — Spec 014 Graph node contracts

One step = one PR, merged to main; pre-prod redeployed after each; gate: `scripts/check.sh` green, structure ratchet
does not grow, behaviour diff "differs 0" (C3: only the listed reset fixes), `check_checkpoints.py` 0 module paths,
pr-self-check answered. Paths under `backend/src/automind/chat/dialog/` unless stated. "(verify)" = read 2026-11-26.

## C1 — `@node` over the flat keys (PR 1)

- [x] T101 `contract/` package: `Retry` (StrEnum PROVIDER | NONE), `ContractError`, `node(name, reads, writes, retry)`
  decorator (build In from state, call, check writes against owners, dump, trace — replaces `tracing.traced`),
  `owners.py` (key → owner node(s); reducer keys `notices`, `research_results` marked append-only).
- [x] T102 In/Out models for every node in `graph.NODES` and the five confirmations (prepare/wait/apply), over today's
  keys; replaces `ReadState`/`AppliedState`/`AssessedState`/`PolicyState` and the 23 `dict[str, Any]` returns.
  Nodes stay ≤ 40 lines public; In/Out models live beside the node module (≤ 200 lines/module).
- [x] T103 Ad-hoc keys into `TurnState`: `provider_down` (turn/execution.py:114, verify) and any other the decorator
  finds; `request_kind` gets one owner (interpret) — `apply_delta` stops writing it (verify nothing depends on the
  second write; if it does, document the case and keep it as a named field of `applied`).
- [x] T104 `graph.NODES` tuples → `node(...)` metadata (`retry=`); `build_graph` reads it; no bare bool.
- [x] T105 Tests: decorator unit tests (missing required key, foreign write, extra key); owners test (no two writers
  except reducers); shape test (every required input written on every path from START, from the types).
- [x] T106 `python -m automind.chat.dialog.contract` prints node · reads · writes · next; output committed as
  `specs/014-node-contracts/contract.md`; a test fails when it is stale.
- [x] T107 Production mode: violation → log (node, key, kind) + `graph_contract_violation_total`; tests: error
  (`AUTOMIND_CONTRACT_STRICT`, default on in tests).

C1 done (PR `014-c1-node-contracts`). Findings: (1) T103 — the second write of `request_kind` is the one that
counts: apply_delta settles the request in code (`choose_for_me` from the words, `compare` while an intake step is
pending, the cars safety net), and policy, assess, after_research, the report and the turn record read the settled
one. Nobody reads `request_kind` between interpret and apply_delta, and interpret's own request is inside its
`interpretation`; so the one owner is **apply_delta** (it also writes it on its ask-back branch, where it equals the
interpretation's), interpret no longer writes it — final values identical on every path. (2) Ad-hoc key:
`provider_down` (turn/execution.py, read by turn/outcome.py) is now a `TurnState` key owned by the runner; the
decorator found no other. (3) `case_version` is also written by load_case (not a reset key). (4) 15 keys keep several
writers until a named step (owners.py `until`, pinned by a test): action, blocks, reply_text (C3 reply); confirm_payload,
resume (C3 confirm); jobs, round, limit_hit (C3 research); not_understood, user_text (C3); case_version (C2); done,
route (C4); cost_approved, research_declined (015 PL5). (5) What remains of `state.get` in `chat/dialog/nodes`: only
the 10 router functions (`route_*`, `fan_out`, `route_policy`), deleted at C4 (T130).

## C2 — Case file once per turn (PR 2)

- [x] T110 `TurnContext.case()` (lazy, cached per ainvoke) and `TurnContext.save_case(case, changes, publish=)`;
  25 `load_case(c)` call sites (verify) moved; `context.load_case/save_case` removed. `save_case` updates the cache;
  spec 015 T211 adds `last_report_fingerprint()` cached the same way.
- [x] T111 `CaseRepo.save_version(chat_id, data, changed_by, change_log, expected: int)`; mismatch →
  `VersionConflict` (named in the port docstring), distinct from store-unavailable; integration test with a stale
  read.
- [x] T112 Retry purity: `report_node`/`answer_node` persist after the model call (or split the persist into a
  non-retried node); test fake fails on a store write before the first LLM call of a `Retry.PROVIDER` node.
- [x] T113 Owner's decision G3: on `VersionConflict` the node runs once more from a fresh read (cache dropped); a
  second conflict fails the turn with a notice; test for both.

C2 done (PR `014-c2-case-once`). Findings: (1) T110 — 25 `load_case` and 26 `save_case` call sites moved to
`c.case()` / `c.case_version()` / `c.save_case()`; the free functions are gone from `context.py`. The cache is
`turn/cached.py` `Cached[T]` (loaded on first `get`, a lock so parallel research jobs share one read, `put` after
the owner's write, `forget`), held by `TurnContext`, which is built per `ainvoke` (a resume or restart reads afresh);
T211's `last_report_fingerprint()` is one more `Cached` field. `case()` returns a new `CaseFile` on every call
(validated from the cached JSON), so a node's unsaved changes never reach the next node — as with a read. After a
save the cache holds the JSON in the store's key order (`jsonb`: by length, then bytes): a cached case iterates its
dicts exactly like the read it replaces (behaviour diff 0). (2) `case_version` (owners `until` C2): nodes no longer
write it; its one writer is `load_case` (the version the turn starts from); the turn row's `case_version_after` comes
from the context — now also right where the last save was by a node that never wrote the key (feasibility, prepare_*,
apply_cost/intake), and set for early endings (was None). (3) T111 — `expected` is keyword-only; the repo compares the
latest version with it and inserts `expected + 1` in one transaction; a concurrent insert of that version (PK) is a
`VersionConflict` too, never `StoreUnavailable`. (4) T112 — report/answer call the model first, then write: intake
events (`DeferredIntake`: the report service's `ENERGY_REPORT` went to the DB before the reporter), computations,
the case. Status events still precede the model (the client's progress stream, not a store). interpret and general
wrote nothing before the model already. Graph test: a guard over the stores' write methods fails a `Retry.PROVIDER`
node writing before its first model call (fails on the old order). (5) T113 — in `@node` (`contract/node.py` `_run`):
`save_case` drops the cache on `VersionConflict`, the body runs once more; a second conflict propagates, the turn is
FAILED and its `error` event says the case was changed elsewhere (`turn/endings.user_error_text`; not an `Ending`,
which would answer as DONE). What the first run did before its save (status events, an intake event, a model call)
happens once more — rare: within a run only a concurrent writer outside the turn lock can move the case.

## C3 — Sections and automatic reset (PR 3, with spec 013 S4)

- [ ] T120 `TurnState` sections (`chat`, `input`, `understanding`, `applied`, `assessment`, `decision`, `confirm`,
  `research`, `research_results`, `notices`, `reply`) as Pydantic models with a lifetime mark; owners registry by
  section. `decision` = spec 015 `DecisionHistory` (T230), no `hops`; `reply.action` is the only `action`.
  Nested values typed and validated: no `SkipValidation` left in the node contracts (89 on 2026-11-27; review of
  2026-11-27: the contract checks presence, not content).
- [ ] T121 `begin_turn` (the `load_case` node id kept as alias) clears every `turn` section; `PER_TURN_RESET` deleted;
  `language` lives in `chat` (no "en" reset).
- [ ] T122 Checkpoint adapter: flat keys of an old blob → sections (pure function, tests on blobs exported by
  `scripts/check_checkpoints.py`); a waiting old-shape turn resumes on the new code (test + pre-prod proof). Also maps
  `decision`, `hops`, `action`, `cost_approved`, `research_declined`, `research_done` (spec 015 T231).
- [ ] T123 Behaviour diff: list every changed outcome (expected: the interpretation leak, the language reset) in the
  PR.

## C4 — Nodes choose their next step (PR 4, with spec 013 S5)

- [ ] T130 `Out.next()` → `Command(goto)` for interpret/understand, apply_changes, confirmations' apply,
  select_candidates; `route`/`done` keys and their router functions deleted; policy stays a conditional edge whose
  path map and router come from spec 015 `ROUTES` (T203); `POLICY_ROUTES` deleted.
- [ ] T131 `tests/graph/graph_shape.json` unchanged in nodes; edges updated only where a router became a `goto`
  (listed); `check_checkpoints.py` green.
- [ ] T132 Switch production to strict (owner's decision G2) once the violation metric was 0 for the agreed period.

## After C4

Update `docs/next-session.md`; the contract table in `contract.md` is the documentation of the graph.
