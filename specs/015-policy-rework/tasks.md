# Tasks — Spec 015 Action policy

One step = one PR, merged to main; pre-prod redeployed after each; gate: `scripts/check.sh` green, structure ratchet
does not grow, behaviour diff "differs 0" (PL5: only the listed outcomes), `check_checkpoints.py` 0 module paths,
pr-self-check answered. Paths under `backend/src/automind/chat/` unless stated. "(verify)" = read 2026-11-27.
Order of merge: PL1 → PL2 → PL3 → PL5 → PL4 (spec §D7).

## PL1 — Skeleton without behaviour change (PR 1, now, beside 013 S2 / 014 C1)

- [x] T201 `dialog/policy/contracts.py`: `Stage` (StrEnum LIMITS | GENERAL | INTAKE | CONFIRM | RESEARCH | ANSWER),
  `CarFacts` (today's `CarState` fields incl. `gearbox_mixed` + `key`), `Situation` (frozen, `extra="forbid"`, today's
  facts without defaults: request, cars, cost, last fingerprint, cost_approved, research_declined, case_changed,
  feasibility_pending, `pass_no`), `RuleOutcome`, `Decision`, `PolicyInputError`, `PolicyBug`.
  `domain/decision.py` → package `domain/decision/`; `PolicyConfig` (threshold, hard cap, `max_passes`, intake
  `Limits`; validator cap ≥ threshold) there. PL1 builds the config in the node from the same sources as today.
- [x] T202 Rules as classes, one module per stage (≤ 200 lines): the 10 rules of `policy/chain.py:27-38` (verify) +
  `AnswerOrReport` last, always firing, 1:1 logic; stable `name`, `stage`, `requirement`; `fire`/`skip`; `Action`
  factories; `RULES: Final` and `decide(s, cfg) -> Decision` in `dialog/policy/decide.py`; `PassLimit` fires at
  `pass_no == max_passes + 1`. Deleted: `chain.py`, `RulesInOrder`, `Policy`, the 14-argument `decide`, `MAX_HOPS`,
  `DEFAULT_*`; callers moved (`nodes/understand.py:105`, `backend/tests/graph/test_robustness.py`,
  `test_candidates.py`, `backend/tests/unit/chat/dialog/policy/*`). `word` lines of `intake_step` removed from
  `scripts/structure_baseline.txt`.
- [x] T203 `dialog/policy/routes.py`: `ROUTES` (ActionKind → `Route(node, Continuation)`; END / SUSPEND / LOOP as
  spec §D4); `graph.py` builds the policy router and path map from it; `route_policy` (`understand.py:132`) and
  `POLICY_ROUTES` (`graph.py:52`) deleted; test: `set(ROUTES) == set(get_args(ActionKind))`, every node exists in the
  built graph; `backend/tests/graph/graph_shape.json` unchanged.
- [x] T204 Tests (`backend/tests/unit/chat/dialog/policy/`): one situation builder; per rule a parametrized table
  (each branch fired with its action, skipped with its reason); order tests; an exception in a rule propagates;
  Hypothesis properties (no `PolicyBug`, trail ends with `decided_by`, limit pass is END); termination simulator
  (LOOP effects applied, SUSPEND/END end the turn, ≤ `max_passes + 1` passes).
- [x] T205 Regression: today's chain frozen as `backend/tests/unit/chat/dialog/policy/legacy_policy.py`; Hypothesis
  compares `Action` minus `reason` on random valid situations — 10 000 in the PR run (paste the result), 500
  derandomized in `check.sh` (spec §H D10).
- [x] T206 import-linter contract `policy-pure` in `backend/.importlinter` (spec §D2 list); `lint-imports` green.

PL1 done (PR `015-pl1-policy-skeleton`). Findings: (1) `Situation` keeps `cost_estimate_eur: float` and the
glued `research_declined` (declined or done) until PL2/PL5 — the Decimal rounding and `ResearchStatus` change
decisions at the edges, so they wait for their steps; the node fills an unassessed car with today's empty `CarState`
(identity known) — PL2's invariant replaces that. (2) `max_passes` comes from a new setting `policy_max_passes = 8`
(the old code constant `MAX_HOPS`), read in the node with the thresholds; PL2 builds `PolicyConfig` once.
(3) `Action` got one factory per kind; `CarFacts.of(key, CarState)`. (4) `word` debt: intake `StepKind` became a
`StrEnum`, `_need` reads a table, the MODEL question compares with `tactic.NOT_FOUND` — structure 1406 → 1401.
(5) Regression: 10 000 random situations, 0 differences (whole `Action` incl. `reason`); the generator mixes raw and
settled cases so every branch of all 11 rules is reached; a mutation at the €0.30 threshold or the feasibility
branch is caught by the 10 000 run and by the rule tables (the derandomized 500 of `check.sh` is a smoke run).
(6) `DecisionState.kind` is typed `ActionKind`; the graph's policy edge is `route_of` over `ROUTES`.

## PL2 — One input and config (PR 2, after 014 C2)

- [x] T210 `PolicyConfig` built once in the composition root (`delivery`, where `Ports` is wired — verify) from
  settings + `search.yaml intake`; invalid → startup fails (test); `Ports.policy: PolicyConfig`; the cap text in
  `dialog/nodes/confirm.py:223,348` (verify) reads it; no `settings()`/`ref.search` left in the policy path.
- [x] T211 `dialog/policy/situation.py` `situation_from(inp, *, case, last_fingerprint) -> Situation` (pure; `Decimal`
  cost rounded half-up to the cent); `TurnContext.last_report_fingerprint()` cached per `ainvoke` with 014 T110's
  mechanism; the case from `ctx.case()` (014 T110).
- [x] T212 Feasibility fact from assess: `needs_ack`/`pending` (`dialog/nodes/feasibility.py:23-32`, verify) move into
  the feasibility service; assess writes `feasibility_pending: bool` and `assessed_version` into its output;
  `prepare_feasibility`/`apply_feasibility` use the moved functions.
- [x] T213 Invariants in `situation_from` (spec §D6): facts for exactly the case's cars, `assessed_version ==
  case.version`, `pass_no ≤ max_passes + 1`; production: log (field, turn_id) +
  `automind_policy_input_errors_total{field}`, strict by `AUTOMIND_POLICY_STRICT` (on in tests); one test per
  invariant; a strict error fails the turn via `turn/endings.py` (no new ending).
- [x] T214 `policy_node` → `dialog/nodes/policy.py` (≤ 30 lines; `@node("policy", retry=Retry.NONE)` from 014
  T101/T104); module added to the mypy strict list (`scripts/check.sh:50`, `backend/pyproject.toml`); test: policy
  store reads per turn after the first = 0.

PL2 done (PR `015-pl2-one-input`). Findings: (1) the composition root is `chat/infrastructure/adapters.live_ports`
(called from `delivery/web/app.py` at startup), so `policy_config(settings, search)` lives beside it; an invalid
config raises there and the app does not start. The golden runner builds it after a dialogue's settings overrides
(g7). (2) Money is `Decimal` in `PolicyConfig` and `Situation`; the estimate is rounded half-up to the cent in
`situation_from` (assess stays float). The regression strategy draws costs to the cent, so the old float chain and
the new Decimal policy still agree: 10 000 situations, 0 differences. (3) `situation_from` stays pure: it returns
`SituationRead(situation, errors)`; the node raises the first error when `PolicyConfig.strict_inputs`
(`AUTOMIND_POLICY_STRICT`, on in tests) or logs `policy.input_error` and counts
`automind_policy_input_errors_total{field}`. Invariant `cars` covers both a case car without an assessment (the
production fallback stays the empty `CarState`) and an assessment of a car the case does not have. (4) New state
keys `feasibility_pending`, `assessed_version` (owner `assess`, reset per turn); `PlanRequest.checked` carries the
turn's earlier checks, so `Planned.feasibility_pending` is computed in the service. (5) `feasibility.py` order/doc
debt cleared on the way: structure 1390 → 1381. Behaviour diff vs main: differs 0; checkpoints: 19 threads load.

## PL3 — Decision record and "why" (PR 3, before 013 S3; spec §H D2 decided first)

- [x] T220 `DecisionRecord` (`domain/decision/`), port `DecisionLog` (`application/ports.py`: `record`, `for_turn`;
  raises `StoreUnavailable`), repository in `infrastructure/`; Alembic migration `policy_decisions` (key
  `(turn_id, pass_no)`, upsert) + `policy_configs` (by hash); both under `chat` in `scripts/table_owners.yaml`; the
  policy node writes one row per pass; a write error → ERROR log + `automind_policy_record_errors_total`, turn goes on
  (test drives it).
- [x] T221 `config_hash` (sha256 of the canonical JSON) and `rules_version` (hash of `RULES` names in order + package
  version), unit-tested for stability.
- [x] T222 Log line `policy.decided`; Prometheus `automind_policy_decisions_total{rule,action}`,
  `automind_policy_passes_per_turn`, `automind_policy_pass_limit_total` (in `shared/infrastructure/metrics/prom.py`);
  alert on pass-limit growth in `deploy/prometheus/automind-rules.yml`.
- [x] T223 CLI `python -m automind.delivery.cli.policy why <turn_id> [--replay]` and `export <turn_id>` (YAML fixture;
  user words in evidence and region masked); the renderer is a function `turn show` (013 T035) calls.
- [x] T224 Tests: round-trip `decide → record → read → decide` same action; repeated pass writes no duplicate;
  masking; exported fixtures load as golden situations (`backend/tests/unit/chat/dialog/policy/golden/`).
- [x] T225 Retention per spec §H D2 (daily delete of rows older than the agreed days).

PL3 done (PR `015-pl3-decision-record`). Findings: (1) constitution XIII allows the API one background task, so the
90-day delete is a step of the engine's `retention_loop(prune_decisions)` (chat code, chat table), not a second
loop. (2) `prom.py` would pass 200 lines: the policy's metrics live in `shared/infrastructure/metrics/policy.py`
(`decided`, `passes`, `input_error`, `record_error`, `metric_names`); `automind_policy_passes_per_turn` is observed
by the turn outcome (final `hops`), not by the node. (3) `rules_version()` is a cached function (sha256 of the rule
names in order + the package version), `config_hash` the sha256 of the canonical config JSON. (4) `export` masks
every string under `request_text`, `evidence`, `region`, `region_code`; the masked situation decides the same
(test). Golden: `golden/synthetic.yaml` (6 passes: report, confirm cost, research, over cap, unknown car, pass
limit). (5) Chat deletion removes the chat's passes (`CHAT_SCOPED`); `policy_configs` stay (no user data). (6) The
behaviour diff cannot run main on a test DB at 0026: compared against main + the migration and models only —
differs 0.

## PL5 — Honest facts (PR 4, after 013 S3, before 013 S4)

- [ ] T240 `ResearchStatus` (`domain/decision/`: NOT_NEEDED, PENDING, APPROVED, DECLINED, DONE) and
  `research_status(...)` (pure; precedence DONE > DECLINED > APPROVED > PENDING > NOT_NEEDED over `research_done`,
  `research_declined` from assess / `apply_cost` / `apply_intake`, `cost_approved`; one test per row);
  `Situation.research` replaces `cost_approved` + `research_declined`; the glue at `nodes/understand.py:112` (verify)
  removed.
- [ ] T241 `StaleData` and `IntakeCard` decide with `match s.research` + `assert_never`; reasons name DONE vs DECLINED.
- [ ] T242 Behaviour diff: every changed outcome listed in the PR; golden situations updated explicitly;
  `legacy_policy.py` and its regression removed.

## PL4 — Decision history on the board (PR 5, with 014 C3 / 013 S4)

- [ ] T230 The `decision` section (014 T120) = `DecisionHistory` (passes of the turn: action, decided_by, pass_no);
  `pass_no = len(passes) + 1`; `hops` deleted; the policy no longer writes `action` (014 `reply.action` is the turn's
  outcome). Readers moved to `decision.last` (spec §B10: `confirm.py`, `nodes/research.py`, `nodes/report.py`,
  `report_writer.py` — verify); `turns.action` keeps its values (fingerprint query `repositories.py:276`,
  `observability/domain/outcome.py:73`).
- [ ] T231 Checkpoint adapter (inside 014 T122): `decision`, `hops`, `action`, `cost_approved`, `research_declined`,
  `research_done` of an old blob → sections; tests on blobs from `scripts/check_checkpoints.py`.
- [ ] T232 Behaviour diff: nothing beyond 014 C3's list.

## After PL4

013 T041 (policy reads `Intent`) is written on `Rule`/`Situation`/`Decision` (edit E4 in `coverage-audit.md`).
Update `docs/next-session.md`; `why <turn_id>` is the documented way to answer "why did the bot do X".
