# Tasks — Spec 014 Graph node contracts

One step = one PR, merged to main; pre-prod redeployed after each; gate: `scripts/check.sh` green, structure ratchet
does not grow, behaviour diff "differs 0" (C3: only the listed reset fixes), `check_checkpoints.py` 0 module paths,
pr-self-check answered. Paths under `backend/src/automind/chat/dialog/` unless stated. "(verify)" = read 2026-11-26.

## C1 — `@node` over the flat keys (PR 1)

- [ ] T101 `contract/` package: `Retry` (StrEnum PROVIDER | NONE), `ContractError`, `node(name, reads, writes, retry)`
  decorator (build In from state, call, check writes against owners, dump, trace — replaces `tracing.traced`),
  `owners.py` (key → owner node(s); reducer keys `notices`, `research_results` marked append-only).
- [ ] T102 In/Out models for every node in `graph.NODES` and the five confirmations (prepare/wait/apply), over today's
  keys; replaces `ReadState`/`AppliedState`/`AssessedState`/`PolicyState` and the 23 `dict[str, Any]` returns.
  Nodes stay ≤ 40 lines public; In/Out models live beside the node module (≤ 200 lines/module).
- [ ] T103 Ad-hoc keys into `TurnState`: `provider_down` (turn/execution.py:114, verify) and any other the decorator
  finds; `request_kind` gets one owner (interpret) — `apply_delta` stops writing it (verify nothing depends on the
  second write; if it does, document the case and keep it as a named field of `applied`).
- [ ] T104 `graph.NODES` tuples → `node(...)` metadata (`retry=`); `build_graph` reads it; no bare bool.
- [ ] T105 Tests: decorator unit tests (missing required key, foreign write, extra key); owners test (no two writers
  except reducers); shape test (every required input written on every path from START, from the types).
- [ ] T106 `python -m automind.chat.dialog.contract` prints node · reads · writes · next; output committed as
  `specs/014-node-contracts/contract.md`; a test fails when it is stale.
- [ ] T107 Production mode: violation → log (node, key, kind) + `graph_contract_violation_total`; tests: error
  (`AUTOMIND_CONTRACT_STRICT`, default on in tests).

## C2 — Case file once per turn (PR 2)

- [ ] T110 `TurnContext.case()` (lazy, cached per ainvoke) and `TurnContext.save_case(case, changes, publish=)`;
  25 `load_case(c)` call sites (verify) moved; `context.load_case/save_case` removed.
- [ ] T111 `CaseRepo.save_version(chat_id, data, changed_by, change_log, expected: int)`; mismatch →
  `VersionConflict` (named in the port docstring), distinct from store-unavailable; integration test with a stale
  read.
- [ ] T112 Retry purity: `report_node`/`answer_node` persist after the model call (or split the persist into a
  non-retried node); test fake fails on a store write before the first LLM call of a `Retry.PROVIDER` node.
- [ ] T113 Owner's decision G3: on `VersionConflict` the node runs once more from a fresh read (cache dropped); a
  second conflict fails the turn with a notice; test for both.

## C3 — Sections and automatic reset (PR 3, with spec 013 S4)

- [ ] T120 `TurnState` sections (`chat`, `input`, `understanding`, `applied`, `assessment`, `decision`, `confirm`,
  `research`, `research_results`, `notices`, `reply`) as Pydantic models with a lifetime mark; owners registry by
  section.
- [ ] T121 `begin_turn` (the `load_case` node id kept as alias) clears every `turn` section; `PER_TURN_RESET` deleted;
  `language` lives in `chat` (no "en" reset).
- [ ] T122 Checkpoint adapter: flat keys of an old blob → sections (pure function, tests on blobs exported by
  `scripts/check_checkpoints.py`); a waiting old-shape turn resumes on the new code (test + pre-prod proof).
- [ ] T123 Behaviour diff: list every changed outcome (expected: the interpretation leak, the language reset) in the
  PR.

## C4 — Nodes choose their next step (PR 4, with spec 013 S5)

- [ ] T130 `Out.next()` → `Command(goto)` for interpret/understand, apply_changes, confirmations' apply,
  select_candidates; `route`/`done` keys and their router functions deleted; policy stays a conditional edge.
- [ ] T131 `tests/graph/graph_shape.json` unchanged in nodes; edges updated only where a router became a `goto`
  (listed); `check_checkpoints.py` green.
- [ ] T132 Switch production to strict (owner's decision G2) once the violation metric was 0 for the agreed period.

## After C4

Update `docs/next-session.md`; the contract table in `contract.md` is the documentation of the graph.
