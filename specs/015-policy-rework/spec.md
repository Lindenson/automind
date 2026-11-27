# Spec 015 — Action policy: one typed input, rules with outcomes, one routes table, a decision record per pass

**Branch**: `015-policy-spec` · **Created**: 2026-11-27 · **Status**: Approved by the owner 2026-11-27 (§H, all proposals: "согласен")

**Input**: the owner's policy spec "Спека: переделка политики действий (policy) — дизайн, надёжность, трассируемость"
(2026-11-26), saved verbatim in `source-spec.md`; checked against the code on 2026-11-27 (§B, `coverage-audit.md` §A).
Related: spec 013 (understanding, `Intent`, policy from the goal — T041), spec 014 (node contracts: `@node`,
`ctx.case()`, sections, checkpoint adapter), spec 012 code-shape contract (`specs/012-refactoring/contracts/code-shape.md`).

**Scope**: only what 013 and 014 do not own. Where they do, this spec names their task and depends on it.

**Goal in one sentence**: the policy is a pure function of one typed situation and one config; every rule says why it
fired or not; one table says where each action leads; every pass leaves a record that explains and replays it.

---

## A. Why

The policy decides what the bot does next, but the decision cannot be explained or replayed after the turn. The
node gathers its facts from six places, fills the gaps with defaults, glues two flags into one, and keeps only the
winning rule's `reason`. Spec 013 T041 will change the rules (policy from the goal); doing that on today's shape
multiplies the problem, so the skeleton and the record come first, behaviour unchanged.

## B. Evidence (verified in code 2026-11-27)

Paths under `backend/src/automind/chat/`. Full verdicts on every claim of the source: `coverage-audit.md` §A.

| # | Fact | Where |
|---|---|---|
| B1 | `policy_node` reads six sources: board (`state.get`), case from the DB, last report fingerprint from the DB, `settings()`, `ports.ref.search`, a function of another node's module | `dialog/nodes/understand.py:99-121`; `dialog/context.py:22-24`; `infrastructure/persistence/repositories.py:143,276`; `dialog/nodes/feasibility.py:30-32` |
| B2 | Up to 9 passes per turn (`MAX_HOPS = 8`, the limit rule fires when `hops >= 8`, `hops` starts at 0) × 2 DB queries per pass = up to 18 queries from the policy | `dialog/policy/contracts.py:17`; `dialog/policy/rules/limits.py:12`; `dialog/state.py:91` |
| B3 | Silent defaults: `request_kind or "compare"`, `get("case_changed", True)`, `get("assessments", {})`; a car without assessment gets `CarState()`, whose `identity_known` defaults to **True**; `Situation` has 9 defaulted fields; `intake_limits or Limits(full_intake=False)`. 8 of the node's 10 `.get` calls default or coerce | `understand.py:104-117`; `policy/contracts.py:31-44`; `domain/decision.py:47`; `policy/rules/intake.py:27` |
| B4 | Glued flag `research_declined or research_done`, read by two rules; `research_declined` has three writers (assess from `case.declined_plan` — survives turns —, `apply_cost`, `apply_intake`) | `understand.py:112`; `policy/rules/research.py:12`, `confirm.py:26`; `application/services/assessment/contracts.py:94`, `assessment/service.py:68`; `dialog/nodes/confirm.py:254,428` |
| B5 | `decide()` takes 14 arguments, builds `Situation`, instantiates `RulesInOrder()` per call; the `Policy` protocol has no user | `policy/chain.py:51-69`; `policy/contracts.py:51-52` |
| B6 | 10 rules + the fallback `answer_or_report` (6 situations, 7 returns) outside the list | `policy/chain.py:27-48`; `policy/rules/answer.py:11-36` |
| B7 | Routes in three places that agree today: `route_policy` dict (KeyError on a new kind), `POLICY_ROUTES`, `ActionKind` (11 kinds, 10 targets) | `understand.py:132-145`; `dialog/graph.py:52-53,97`; `domain/decision.py:13-25` |
| B8 | What follows each target is not "terminal or assess": 5 kinds end the turn in an interrupt (`wait_*`), `select_candidates` re-enters via `identify`, research may pause at `prepare_limit` | `graph.py:56-74,99-106` |
| B9 | Feasibility "pending" hashes `constraint_lines` from the **application** layer, so it cannot move into the domain; thresholds come from `settings()` and are duplicated as `DEFAULT_*`; the cap is read again by two confirmation nodes | `nodes/feasibility.py:23-32`; `application/services/feasibility/feasibility.py:130`; `shared/infrastructure/config/settings.py:31-32`; `policy/contracts.py:18-19`; `confirm.py:223,348` |
| B10 | Readers of the board's `decision`: `confirm.py:37,110,219,348`, `nodes/research.py:35`, `nodes/report.py:51`, `report_writer.py:33`. Readers of `action`: `turn/replies.py:48,71`, `turn/outcome.py:50,71` → `turns.action`, read by `repositories.py:276` (`Turn.action == "REPORT"` for the fingerprint) and `observability/domain/outcome.py:73`. `"CONFIRM_LIMIT"` (not an `ActionKind`) is written by `nodes/research.py:90` | |
| B11 | Rules are already pure (import only `chat.domain`) and in mypy strict scope; no import-linter contract covers `chat.dialog.policy`; Hypothesis is a dev dependency used once | `scripts/check.sh:50,66`; `backend/pyproject.toml:40`; `backend/.importlinter` |
| B12 | 32 unit tests over `decide` (not per branch: no direct test of `report_after_timeout`, rule order, most `intake_card` branches) | `backend/tests/unit/chat/dialog/policy/test_policy.py`, `test_policy_feasibility.py`; `backend/tests/graph/test_robustness.py`, `test_candidates.py` |
| B13 | No OpenTelemetry; metrics are `prometheus_client` with prefix `automind_`; alerts in `deploy/prometheus/automind-rules.yml` | `shared/infrastructure/metrics/prom.py:24` |
| B14 | An unknown exception already fails the turn with "Что-то пошло не так. Попробуйте ещё раз." | `dialog/turn/endings.py:39-61` |
| B15 | `chat.application` may not import `chat.dialog` (import contract), so a port in `application/ports.py` cannot be typed with `dialog/policy` types | `backend/.importlinter:43-60` |

Corrections to the source: tests exist (B12); mypy strict on `dialog/policy` is already clean, the `Any`/`cast` are in
the node (`understand.py:6,51,120`); the limit is 9 passes, not 8 (B2); `CarState.gearbox_mixed` is used by a rule
(`policy/rules/intake.py:70`) and must stay in `CarFacts`; the `ROUTES` table of the source matches the code exactly
(`coverage-audit.md` §C).

## C. Goals

1. **Pure decision**: `decide(situation, config) -> Decision`, no I/O, no globals, no clock.
2. **One input**: everything the rules read is in `Situation` or `PolicyConfig`; `situation_from` is the only place
   that turns the board into facts.
3. **No silent defaults**: a missing or inconsistent input is a `PolicyInputError` naming the field (metric first,
   strict after a week at 0 — the 014 G2 pattern).
4. **Honest facts**: `research: ResearchStatus` replaces the three flags; a glue is a named rule branch.
5. **One routes table** `ROUTES: ActionKind → node id` with a `Continuation` per kind; the router and the graph edges
   are built from it.
6. **A record per pass**: `policy_decisions` row (situation without the case + case version, config hash, rules
   version, full trail, decided_by, action, next node); "why" and replay from one command.
7. **Behaviour unchanged** until PL5; PL1 proves it on 10 000 random situations against the old code.

Non-goals: no change of what the policy decides before PL5; the model never chooses the action; target nodes are
not touched except their registration in `ROUTES` (and the cap display reading the same config, T210); the switch to
`Intent` stays 013 T041; `@node`, `ctx.case()`, sections, `Command(goto)` and the checkpoint adapter stay 014's.

Measurable (baselines verified, §B):

| Criterion | Now | Target |
|---|---|---|
| Sources of the decision | 6 (B1) | 2 (`Situation`, `PolicyConfig`) |
| DB queries by the policy per turn | up to 18 (B2) | 0 after the turn's first read |
| Defaulting `.get` when building the input | 8 (B3) | 0 |
| Places that define a route | 3 (B7) | 1 |
| Passes with a full record | 0 % | 100 % |
| Rule branches with a fired and a skipped test | not per branch (B12) | 100 % |
| mypy strict | `dialog/policy` clean (B11) | + `dialog/nodes/policy.py` |

## D. Design

### D1. Contracts and where they live

| Type | Module | Why there |
|---|---|---|
| `CarFacts`, `Situation`, `Stage`, `RuleOutcome`, `Decision`, `PolicyInputError`, `PolicyBug` | `chat/dialog/policy/contracts.py` | rules and decide only |
| `PolicyConfig` (threshold, hard cap, `max_passes`, intake limits; validator cap ≥ threshold), `DecisionRecord` (plain data of one row) | `chat/domain/decision/` (module → package) | `Ports` and the `DecisionLog` port reference them; `chat.application` may not import `chat.dialog` (B15) |
| `ResearchStatus` (PL5) | `chat/domain/decision/` | a state of the case's research, enum (code-shape "states, not words") |

All frozen, `extra="forbid"`, no field default that can hide an error. `CarFacts` = today's `CarState` + `key`,
**keeping `gearbox_mixed`**. `cost_estimate_eur: Decimal` (`ge=0`), converted at `situation_from` (round half-up to
the cent; assess stays float). `pass_no` starts at 1; `PassLimit` fires at `pass_no == max_passes + 1` (today's
semantics, B2), and `pass_no > max_passes + 1` is a `PolicyBug`.

### D2. Rules and decide

As the source §5: `Rule` protocol (`name: ClassVar[str]` stable, `stage: ClassVar[Stage]`, `requirement:
ClassVar[str | None]`, `check(s, cfg) -> RuleOutcome`), helpers `fire`/`skip`, `Action` factories
(`Action.research(cars)`, `Action.confirm_cost(cars, over_cap=)`, …). `RULES: Final[tuple[Rule, ...]]` grouped by
stage, the 10 rules ported 1:1 and `AnswerOrReport` last and always firing; `decide` returns at the first fired rule
with the trail up to it; falling off the end raises `PolicyBug` (a test proves unreachable). An exception inside a
rule is never caught. One module per stage (≤ 200 lines); `chain.py`, `RulesInOrder`, `Policy`, the 14-argument
`decide`, `MAX_HOPS`, `DEFAULT_*` are deleted. The `word` debt of `intake_step` (`scripts/structure_baseline.txt:1371-1372`)
is cleared in the port. `AnswerOrReport` keeps its six situations until 013 T041 (§H D3).

An import-linter contract `policy-pure`: `automind.chat.dialog.policy` may not import `chat.dialog.nodes`,
`chat.dialog.graph`, `chat.application`, `chat.infrastructure`, `shared.infrastructure` (settings), `langgraph`,
`sqlalchemy`.

### D3. Node and `situation_from`

`dialog/nodes/policy.py` (out of `understand.py`), ≤ 30 lines: build `Situation` with `situation_from(inp, case=,
last_fingerprint=)`, `decide(situation, ctx.ports.policy)`, write the record (D5), return the decision. Its `In`/`Out`
come from 014's `@node` (T101/T102, flat keys at C1; sections at C3). The case comes from `ctx.case()` (014 T110);
the last report fingerprint from `ctx.last_report_fingerprint()`, cached per `ainvoke` the same way (until 014 C3
moves it into the `chat` section). `feasibility_pending` becomes a fact computed by assess (the application owns
`constraint_lines`, B9) and written into the assessment; `needs_ack`/`pending` move from `nodes/feasibility.py` into
the feasibility service. Assess also writes `assessed_version` (the case version it assessed) for invariant D6.

`PolicyConfig` is built once in the composition root (`delivery`) from settings and `search.yaml intake`; invalid →
the service does not start; reached as `Ports.policy`. The cap shown by `confirm.py:223,348` reads the same object.

### D4. Routes

`dialog/policy/routes.py`: `ROUTES: Final[Mapping[ActionKind, Route]]`, `Route(node: NodeId, continuation:
Continuation)`, `Continuation = END | SUSPEND | LOOP` (B8: END for general/ask/answer/report/rescore; SUSPEND for the
four `CONFIRM_*`/`FEASIBILITY` kinds; LOOP for `RESEARCH`, `SELECT_CANDIDATES`). The graph keeps a conditional edge
from `policy` (014 D4, approved) whose router and path map are built from `ROUTES`; `route_policy` and
`POLICY_ROUTES` are deleted; `tests/graph/graph_shape.json` does not change. Test: `set(ROUTES) ==
set(get_args(ActionKind))` and every node exists in the built graph.

### D5. Decision record

One row per pass in `policy_decisions` through the port `DecisionLog` (`chat/application/ports.py`, raises
`StoreUnavailable` only) and its repository in `chat/infrastructure/`; table owner `chat`
(`scripts/table_owners.yaml`); Alembic migration. Key `(turn_id, pass_no)`, upsert (a retried node writes no
duplicate). Columns: `chat_id`, `turn_id`, `pass_no`, `situation` (dump without the case) + `case_version`,
`config_hash` (configs by hash in `policy_configs`), `rules_version` (hash of names and order of `RULES` + package
version), `trail` `[{rule, fired, why}]`, `decided_by`, `action`, `next_node`. A write failure: log at ERROR with
chat/turn ids and `automind_policy_record_errors_total`; the turn goes on.

Log line `policy.decided` (chat_id, turn_id, pass_no, decided_by, action.kind, next_node). Prometheus:
`automind_policy_decisions_total{rule,action}`, `automind_policy_passes_per_turn` (histogram),
`automind_policy_pass_limit_total`, `automind_policy_input_errors_total{field}`; alert on pass-limit growth in
`deploy/prometheus/automind-rules.yml`. No OpenTelemetry (B13, §H D1).

CLI `python -m automind.delivery.cli.policy why <turn_id> [--replay]` and `export <turn_id>` (YAML fixture, user words
in evidence and the region masked). The renderer is a function that 013 T035 `turn show` reuses (§G). The CLI lives
in `delivery/cli` like the others (the policy package may not reach the DB, D2).

### D6. Reliability

Invariants (each a `PolicyInputError` naming the field; production: log + `automind_policy_input_errors_total{field}`,
strict by config after a week at 0; tests: strict): facts for exactly the case's cars; `assessed_version ==
case.version`; cost ≥ 0 (type); `pass_no ≤ max_passes + 1` (`PolicyBug`). A strict error fails the turn through the
existing ending (B14) — no new ending type. No retries (`Retry.NONE`, 014 T104).

### D7. Placement against 013 and 014

| Step | Content | When | Depends on |
|---|---|---|---|
| PL1 | Skeleton: contracts, `Rule`/`RuleOutcome`/`Decision`, rules 1:1, `AnswerOrReport` last, `ROUTES` + `Continuation`, `policy-pure` contract, table/order/property tests, 10 000-case regression vs the old code | now, beside 013 S2 / 014 C1 | — |
| PL2 | One input: `PolicyConfig` at the composition root, `situation_from`, fingerprint cache, feasibility fact from assess, invariants (metric), node to `nodes/policy.py` | after 014 C2 | 014 T110 (`ctx.case()`), T101–T102 (`@node`) |
| PL3 | Record: `policy_decisions`, `DecisionLog`, log, metrics, alert, `why`/`export`/`--replay` | before 013 S3 | PL2; owner's yes for the table (§H D2) |
| PL5 | Honest facts: `ResearchStatus`, first behaviour change, golden situations updated | after 013 S3, before 013 S4 (§H D5) | PL3 (the record shows the change) |
| PL4 | Decision history on the board: `decision` = passes of the turn, no `hops`, no `action` from the policy; adapter for old blobs | with 014 C3 (= 013 S4) | 014 T120–T122 |
| — | Policy reads `Intent` | 013 T041 (S4), rewritten on `Rule`/`Situation` (§G) | PL1–PL3, PL5 |

PL4 is numbered as in the source (step 4) but merges after PL5, because its state change is born with 014's
sections in one checkpoint migration. The source's `ROUTES` part of step 4 moves to PL1 (no state change, §H D7).

## E. Testing and acceptance

- Unit (no DB, no LangGraph, no model): one situation builder (`situation().with_car(...).research(...).build()`);
  a table per rule: every branch fired with its action and skipped with its reason; order tests (two rules apply →
  the earlier wins); `situation_from` per invariant; `research_status` per precedence row (PL5).
- Properties (Hypothesis, random valid situations): `decide` never raises `PolicyBug`; the trail is non-empty and
  ends with `decided_by`; at `pass_no == max_passes + 1` the action's continuation is END.
- Termination simulator: LOOP actions apply their effect (research → DONE + fresh data; candidates → cars named);
  SUSPEND and END end the turn; every random start ends within `max_passes + 1` passes, and within 4 for the
  catalogue of start situations (target, not config, §H D6).
- Regression: the old chain is frozen as a test snapshot; both decide 10 000 random situations in the PL1 PR run
  (whole `Action` minus `reason` equal); `check.sh` runs a derandomized subset (§H D10); the snapshot is removed at PL5.
- Record: round-trip `decide → record → read → decide` gives the same action; repeat of a pass writes no duplicate;
  write failure path.
- Graph: routes completeness; `graph_shape.json` unchanged; golden dialogues and graph tests unchanged after PL1–PL4;
  behaviour diff "differs 0" for PL1–PL4; PL5 lists each changed outcome.

Acceptance:
- [ ] `decide(situation, config)` is the only entry; `chain.py`, `RulesInOrder`, `Policy`, `MAX_HOPS`, `DEFAULT_*`
      gone; `lint-imports` has `policy-pure`.
- [ ] Every rule branch has a fired and a skipped test; 10 000-case regression differs 0 (PL1).
- [ ] Policy DB reads per turn after the first: 0 (test counting port calls); 0 `settings()`/`ref.search` in the
      policy path.
- [ ] `ROUTES` is the only route definition; completeness test green.
- [ ] Every pass on pre-prod leaves a `policy_decisions` row; `why <turn_id>` and `--replay` work on a live turn.
- [ ] `PolicyInputError` metric at 0 for a week before strict.
- [ ] PL5 behaviour diff listed and approved by the owner.

## F. Steps (one PR each)

| # | Step | When |
|---|---|---|
| PL1 | Skeleton + routes + tests + regression | now, beside 013 S2 / 014 C1 |
| PL2 | One input and config | after 014 C2 |
| PL3 | Decision record and "why" | before 013 S3 |
| PL5 | `ResearchStatus` (first behaviour change) | after 013 S3, before 013 S4 |
| PL4 | Decision history on the board | with 014 C3 / 013 S4 |

## G. Approved constraints kept (conflicts resolved by them)

1. 013 order S0 → S7 and G6 (first goal only at S4): untouched; 015 adds no goal logic. The switch to `Intent` stays
   013 T041; proposal: rewrite T041 to sit on `Rule`/`Situation`/`Decision` (`coverage-audit.md` §E4).
2. 014 G1 order (C1–C2 now, C3 with 013 S4, C4 with 013 S5): PL2 waits for C2; PL4 rides C3; nothing rides C4.
3. 014 D4 "policy stays a conditional edge": kept; the source's `PolicyOut.next()` → `goto` is not used, the edge is
   built from `ROUTES`.
4. 014 G2 (log + metric, strict after a week at 0): reused for the policy invariants.
5. Import contracts (`application-ports`): `PolicyConfig` and `DecisionRecord` in `chat/domain/decision/`, not in
   `dialog/policy` as the source writes; the CLI in `delivery/cli`, not `dialog.policy.__main__`.
6. One owner of the policy trace: `policy_decisions` (this spec), if the owner agrees (§H D9); edits to 013/014 are
   listed in `coverage-audit.md` §E.

## H. Owner's decisions (2026-11-27 — every proposal approved as written)

| # | Question | Proposal |
|---|---|---|
| D1 | (source §11 Q1) OpenTelemetry span? | None exists (B13): log line + `policy_decisions` + Prometheus; no span. |
| D2 | (§11 Q2) Retention of `policy_decisions`; owner's yes for two new tables (`policy_decisions`, `policy_configs`) | 90 days, deleted daily by a chat retention step; no partitions (≤ 9 rows per turn); additive migration. |
| D3 | (§11 Q3) Split `AnswerOrReport` at PL1 or later? | Later, in 013 T041: its branches are request labels that become goal rules; PL1 stays 1:1 for the regression. |
| D4 | (§11 Q4) Admin page "why" or CLI? | CLI now (`delivery/cli/policy.py`); the read side of `DecisionLog` allows an endpoint later. |
| D5 | Where `ResearchStatus` (source step 5) goes against 013 | After 013 S3, before S4: a separate PR keeps S4's behaviour diff clean. Expected diff is small (today DONE and DECLINED both skip research); the gain is the trace. |
| D6 | (§11 Q5) `max_passes` | Keep today's semantics (8 + the limit pass = 9). Decide a lower value from `automind_policy_passes_per_turn` two weeks after PL3; the "≤ 4" stays a simulator target. |
| D7 | `ROUTES` in PL1 instead of the source's step 4 | Yes: no state change, graph shape identical, and the completeness test is in place before 013 T041 adds `ANSWER_AND_REASK`. |
| D8 | Source `PolicyOut.next()` → `goto` vs 014 D4 (approved: policy stays an edge) | Keep 014: conditional edge built from `ROUTES`. |
| D9 | Owner of the policy trace: 013 `turn_understanding.policy_trail` (T033/T041/T035) vs `policy_decisions` | `policy_decisions` (per pass, replayable); `turn_understanding` drops `policy_trail`; `turn show` reuses the `why` renderer (edits E1–E4). |
| D10 | Size of the Hypothesis regression in `check.sh` | 10 000 once in the PL1 PR (result pasted); `check.sh` runs 500, derandomized, until PL5. |
| D11 | Three-valued `Continuation` instead of the source's "terminal / back to assess" | Yes (B8): END / SUSPEND / LOOP; the termination test counts SUSPEND as an end of the turn. |
