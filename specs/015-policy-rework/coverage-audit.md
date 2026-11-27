# Coverage audit: owner's policy spec → specs 013 + 014 (+ draft 015)

Date: 2026-11-27. Read-only on code; every code claim below was checked on branch `015-policy-spec` (= main
`eb086b7` for code). Paths are under `backend/src/automind/chat/` unless they start with `backend/`, `scripts/` or
`deploy/`.

Source: `specs/015-policy-rework/source-spec.md` (§1–§11). Our documents: `013/spec.md` (**13s**), `013/tasks.md`
(**13t**), `014/spec.md` (**14s**), `014/tasks.md` (**14t**), `015/spec.md` + `015/tasks.md` (**15**, draft).

Statuses (of 013/014, before 015): **Covered** — in a spec and a task; **Partial** — part of it, or the mechanism
without the policy-specific content; **Missing** — neither 013 nor 014 has it (015 now owns it); **Differs** — 013/014
or the code says something else (both sides quoted; resolution in 15 §G or "Decisions pending").

## 0. General remarks

| # | Remark | Consequence |
|---|---|---|
| G1 | The source was written against an archive "without tests and code outside" (§2 table, §11 Q1). Several of its "now" values are wrong for the repo: tests exist, mypy strict already covers `dialog/policy`, import-linter runs in CI, Hypothesis is a dev dependency (§A below). | Its measurable criteria are restated in 15 §C against verified baselines. |
| G2 | The source's `ROUTES` table equals today's `route_policy` mapping exactly (§C below): the names `plan_research`, `prepare_feasibility`, `RESCORE` all exist. The mismatch is elsewhere: "terminal or back to assess" is not a binary in the graph. | 15 uses a three-valued `Continuation`. |
| G3 | Two owners threatened: `policy_trail` (13t T033/T035/T041) vs `policy_decisions` (source §7); `hops` in the `decision` section (14s D1) vs "hops disappears" (source §6.1); `POLICY_ROUTES` kept (14s D4) vs deleted (source §6.2). | Edits proposed in §E; owner picks in 15 §H. |
| G4 | Source module paths for contracts/config collide with the import contract `application-ports` (`backend/.importlinter:43-60`: `chat.application` may not import `chat.dialog`): `PolicyConfig` "in Ports" and a `DecisionLog` port typed with `dialog.policy` contracts cannot both hold. | 15 puts `PolicyConfig` and `DecisionRecord` in `chat/domain/decision/`. |

## A. Verification of the source's claims (P1–P9 and numbers)

Like 14s §B: **true** / **partly** / **wrong**, with file:line.

| Claim | Verdict | Evidence |
|---|---|---|
| P1 facts from six sources | **true** | `dialog/nodes/understand.py:99-121` `policy_node`: board (`state.get`), DB case (`load_case`, l.102 → `context.py:22-24` → `CaseRepo.latest` `infrastructure/persistence/repositories.py:143`), DB fingerprint (`c.ports.turns.last_report_fingerprint`, l.110 → `repositories.py:276`), `settings()` (l.103, 115-116), `c.ports.ref.search` (l.117), another node's module `fz_nodes.pending` (l.114, `dialog/nodes/feasibility.py:30-32`). Six counting the two DB reads apart. |
| "up to 16 DB queries per turn" | **partly** | 2 queries per pass (`latest` + `last_report_fingerprint`), but up to **9** passes (see "max 8 hops") → up to **18** from the policy alone; the graph's `recursion_limit=60` (`dialog/runner.py:48`) may stop a turn earlier. Other nodes add their own `load_case` reads (14s B8). |
| P2 silent defaults | **true** | `understand.py:107` `request_kind or "compare"`; l.113 `get("case_changed", True)`; l.108 `get("assessments", {})`; `policy/contracts.py:44` `self.cars.get(c.key, CarState())` — and `CarState()` means *identified* (`domain/decision.py:47` `identity_known: bool = True`), so a car without assessment is treated as "known, no data". Also `Situation` field defaults `policy/contracts.py:31-39` and `policy/rules/intake.py:27` `s.intake_limits or intake.Limits(full_intake=False)`; `domain/intake/steps.py:33-39` `Limits.from_config` defaults each key. |
| "8 `.get` defaults when building the input" | **true (8 of 10)** | `policy_node` has 10 `.get` calls (l.104, 107, 108, 109, 111, 112 ×2, 113, 114, 117); 8 of them default or coerce: `or 0` (104), `or "compare"` (107), `{}` (108), `bool()` (111, 112 ×2), `True` (113), `or {}` (117). |
| P3 glued flag `research_declined or research_done` | **true** | `understand.py:112`. The glued flag feeds two rules: `policy/rules/research.py:12` and `policy/rules/confirm.py:26`. `research_declined` itself has three writers: assess (`application/services/assessment/contracts.py:94`, from `case.declined_plan`, `assessment/service.py:68` — survives turns), `apply_cost` (`dialog/nodes/confirm.py:254`), `apply_intake` (`confirm.py:428`); `research_done` from `nodes/research.py:142`. |
| P4 `feasibility.pending` in a node module; thresholds from `settings()` bypassing Ports | **true** | `nodes/feasibility.py:23-32` (`needs_ack` hashes `fz_app.constraint_lines` — an **application** function, `application/services/feasibility/feasibility.py:130`, so it cannot move into the domain as the source's `pending_for(case)` proposes); `understand.py:103,115-116`; settings defaults `shared/infrastructure/config/settings.py:31-32` duplicated as `DEFAULT_*` in `policy/contracts.py:18-19`; the cap is read a third time by `confirm.py:223,348`. |
| P5 one decision in three forms; `action` written by other nodes; "ASK = model did not understand" | **true** | `Action` → `model_dump` (`understand.py:120`) → `action` string (l.121). `action` written also by `understand.py:66` and `application/services/interpretation/contracts.py:127` (`"ASK"` when the reading asks back), `nodes/report.py:41,61,74`, `confirm.py:77,157,186,227,352`, `nodes/feasibility.py:55,99`; `nodes/research.py:90` writes `"CONFIRM_LIMIT"` into the confirm payload, a value **not** in `ActionKind` (`domain/decision.py:13-25`), which reaches `turns.action` via `dialog/turn/replies.py:71`. |
| P6 routes in three places; new action → `KeyError` mid-turn | **true** | `understand.py:132-145` (dict `[...]`, KeyError on a missing kind), `dialog/graph.py:52-53` `POLICY_ROUTES`, `domain/decision.py:13-25` `ActionKind`. Today all three agree (11 kinds, 10 targets). |
| P7 `decide()` with 14 arguments | **true** | `policy/chain.py:51-67`: case, request, cars, cost_estimate_eur, last_fingerprint, cost_approved, research_declined, case_changed, feasibility_pending, confirm_threshold_eur, hard_cap_eur, intake_limits, hops, max_hops. |
| `RulesInOrder()` per call | **true** | `policy/chain.py:69`. |
| unused `Policy` protocol | **true** | `policy/contracts.py:51-52`; only exported (`policy/__init__.py:12,15`) and named in docstrings (`dialog/__init__.py:7`); no annotation uses it. |
| "10 rules" + fallback `answer_or_report` | **true** | `policy/chain.py:27-38` (10), fallback l.48 → `policy/rules/answer.py:11-36` (6 outcomes: l.16, 20, 23, 28, 30, 33, 36 — seven returns, six distinct situations). |
| "repeats up to 8 times per turn" / `MAX_HOPS` 8 | **partly** | `policy/contracts.py:17` `MAX_HOPS = 8`, but `limits.hop_limit` returns None while `hops < max_hops` (`policy/rules/limits.py:12`) and `hops` starts at 0 (`dialog/state.py:91`), so passes 1–8 decide normally and the **9th** pass is the limit pass. |
| P8 only `Action.reason` survives | **true** | `DecisionState.reason` (`dialog/state.py:32`); nothing records skipped rules; `turns` stores only the action kind. |
| P9 rules see one `request` label | **true** | `policy/contracts.py:24-25` `request: RequestKind`; 14 values `domain/decision.py:26-41`. |
| §2 "rule test coverage unknown (no tests in the archive)" | **wrong** | `backend/tests/unit/chat/dialog/policy/test_policy.py` (23 tests) and `test_policy_feasibility.py` (9, half of them assessment-plan tests); graph tests call `decide` (`backend/tests/graph/test_robustness.py:3,20,23`, `test_candidates.py:9`). Not per-branch: no direct test of `report_after_timeout`, `candidates` vs `general_answer` order, `intake_card` branches. |
| §2 "mypy --strict on dialog/policy: no (Any, cast)" | **wrong** | `scripts/check.sh:50` runs mypy on `src/automind/chat/dialog/policy`; `backend/pyproject.toml` overrides list `automind.chat.dialog.policy.*` with `strict = true`; `grep Any\|cast` in `dialog/policy/` → nothing. The `Any`/`cast` are in the node: `understand.py:6,51,120`. |
| §5.3 / §9 "import-linter in CI" | **partly** | Configured (`backend/.importlinter`) and run (`scripts/check.sh:66` `lint-imports`), but **no contract covers `chat.dialog.policy`** (its own docstring forbids application/infrastructure, `policy/__init__.py:7`; today it imports only `chat.domain`, verified). |
| §9 Hypothesis | **true (available)** | `backend/pyproject.toml:40` dev dependency; used once (`backend/tests/unit/acquisition/domain/test_relevance.py:3`). |
| §7.2 / §11 Q1 OpenTelemetry | **no tracing** | No `opentelemetry` anywhere in `backend/src` or `pyproject.toml`; the turn path is a context-var record (`dialog/tracing.py`); metrics are `prometheus_client` (`shared/infrastructure/metrics/prom.py`, prefix `automind_`); alerts in `deploy/prometheus/automind-rules.yml`. |
| §8.2 "new soft ending `run_internal_error`" | **partly** | `dialog/turn/endings.py:39-50`: any exception not in the table already FAILS the turn and the user gets `_FAILED_TEXT` "Что-то пошло не так. Попробуйте ещё раз." (l.56, 59-61). A new `Ending` is not needed; only the metric/log naming the field is. |
| §8.1 "assessment.case_version == case.version" | **not expressible today** | The assessment does not carry the version it was computed on: `AssessedState.case_version` is set only when assess saved (`assessment/contracts.py:65`, `understand.py:84-85`). Structurally the only edge into `policy` is from `assess` (`graph.py:96-97`), so the invariant holds by graph today. |
| §4 `CarFacts` "former CarState" | **partly** | `CarState` has `gearbox_mixed` (`domain/decision.py:52`) used by `policy/rules/intake.py:70` (GEARBOX question); the source's `CarFacts` drops it — a 1:1 port would lose a question. |

## B. Requirement coverage

### §1 Problems (fix coverage)

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 1.P1 | Policy facts from one place | Partial | 14t T110 (`ctx.case()`) removes the per-pass case read only; fingerprint, `settings()`, `ref.search`, feasibility module untouched → 15 T211–T214 |
| 1.P2 | No silent defaults | Partial | 14t T101/T107 (`ContractError` on a missing required board key) — not `CarState()`, `Limits` defaults, `Situation` defaults → 15 T201, T213 |
| 1.P3 | Separate declined / done | Missing | → 15 T240–T241 |
| 1.P4 | Decision logic out of node module; config not from `settings()` | Missing | → 15 T210, T212 |
| 1.P5 | One form of the decision; `action` one owner | Partial | 14s D1 `reply.action`, 14t T103/T120 (one owner); the `decision` dict vs `action` string split stays → 15 T230 |
| 1.P6 | Routes in one place | Missing | 14s D4 keeps `POLICY_ROUTES` → 15 T203 |
| 1.P7 | No redundant layers | Missing | → 15 T201–T202 |
| 1.P8 | Decision trace | Partial | 13t T041/T033 `policy_trail` (fired rule + reason per turn), no skipped rules, no replay → 15 T220–T224 |
| 1.P9 | Rules see the intent | Covered | 13t T041, T043 (S4); 15 asks T041 to sit on the new `Situation` (§E) |

### §2 Goals, non-goals, measurable criteria

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 2.G1 | `decide(situation, config) -> Decision` pure | Missing | Rules already pure (imports: `chat.domain` only); the node is not → 15 T202 |
| 2.G2 | One input (`Situation`, `PolicyConfig`) | Partial | 14t T110 for the case → 15 T210–T211 |
| 2.G3 | Missing input = contract error with field name | Partial | 14t T101 (board keys) → 15 T213 (policy inputs) |
| 2.G4 | Honest facts; glue explicit in a named rule | Missing | → 15 T240 |
| 2.G5 | One routes table, router + edges from it | Missing | → 15 T203 |
| 2.G6 | `DecisionTrace` every pass | Partial | 13 `policy_trail` per turn → 15 T220 |
| 2.G7 | Rule readable alone; no spec refs in text | Partial | 012 code-shape rule 5 allows spec ids "as a reference, never replace the meaning"; source wants a `requirement` ClassVar (stricter, compatible) → 15 T202 |
| 2.NG1 | Same behaviour first, then goal policy | Partial | Goal policy = 13t T041 (S4); "same first" → 15 PL1–PL4 gates |
| 2.NG2 | Model never chooses the action | Covered | 13s non-goals; 14s non-goals |
| 2.NG3 | Target nodes untouched except routing | Covered | 14s non-goals ("no new node"); 15 non-goals |
| 2.M1 | Data sources 6 → 2 | Missing | → 15 acceptance |
| 2.M2 | DB queries from policy per turn → 0 | Partial | 14t T110 (case); fingerprint → 15 T211; real baseline 18 (§A) |
| 2.M3 | `.get` with default when building input → 0 | Partial | 14s §E "0 `state.get` in `chat/dialog/nodes`" covers the board; `ref.search.get` and `Limits.from_config` defaults not → 15 T210 |
| 2.M4 | Places defining a route 3 → 1 | Missing | → 15 T203 |
| 2.M5 | Turns with full trace 100 % | Partial | 13s §E "every turn leaves `turn_understanding`" (no skipped rules) → 15 T220 |
| 2.M6 | Table tests: every branch fired + skipped | Missing | Baseline wrong in source (§A) → 15 T204 |
| 2.M7 | mypy --strict on `dialog/policy` clean | Differs | Already true (§A); 15 only adds the new node module to the strict scope (T214) |

### §3 Layers

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 3.1 | `dialog/policy/contracts.py` (depends on domain only) | Missing | Exists with today's types; 15 T201 (+ `PolicyConfig`/`DecisionRecord` in `chat/domain/decision/`, G4) |
| 3.2 | `dialog/policy/rules/*.py` per stage, no nodes/infra/settings/LangGraph | Missing | Files exist by phase (`policy/rules/`); contract missing → 15 T202, T206 |
| 3.3 | `dialog/policy/decide.py` (RULES, decide) | Missing | Today `policy/chain.py` → 15 T202 |
| 3.4 | `dialog/policy/situation.py` `situation_from` | Missing | → 15 T211 |
| 3.5 | `dialog/policy/routes.py` `ROUTES` | Missing | → 15 T203 |
| 3.6 | `dialog/nodes/policy.py` (out of `understand.py`) | Missing | 14t T102 wraps the node in place → 15 T214 |
| 3.7 | `DecisionLog` port + repo in infrastructure | Missing | 13t T033 has a port for `turn_understanding` only → 15 T220 |
| 3.8 | Rules/decide testable without DB, LangGraph, model | Partial | True today for rules (`policy/__init__.py:7`, verified imports); not enforced → 15 T206 |

### §4 Data model

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 4.1 | `CarFacts` frozen, `extra=forbid`, with `key` | Differs | Source drops `gearbox_mixed` (§A); 15 T201 keeps it |
| 4.2 | `ResearchStatus` enum (5 values) | Missing | → 15 T240 |
| 4.3 | `Situation` frozen; cars match case (validator) | Missing | → 15 T201 (type), T213 (validator, metric first) |
| 4.4 | `PolicyConfig` (threshold, cap, max_passes 2..20, intake; cap ≥ threshold) | Differs | "In Ports" impossible from `dialog/policy` (G4) → 15 T210 puts it in `chat/domain/decision/` |
| 4.5 | `RuleOutcome(rule, action or None, why)` | Missing | → 15 T201 |
| 4.6 | `Decision(action, decided_by, trail, pass_no)` | Missing | → 15 T201 |
| 4.7 | Three flags → `ResearchStatus` | Missing | → 15 T240 |
| 4.8 | `cars.get(key, CarState())` → validator | Missing | → 15 T213 |
| 4.9 | `cost_estimate_eur` float → `Decimal`, required | Missing | → 15 T211 (boundary conversion) |
| 4.10 | `hops`/`max_hops` → `pass_no` / `max_passes` | Differs | 14s D1 `decision` = "Action, hops" → 15 T230 + edit E7 |
| 4.11 | `settings()`/`ref.search` → `PolicyConfig` | Missing | → 15 T210 |
| 4.12 | `Action.reason` → trail + decided_by + why | Partial | 13t T041 reason names goal and rule → 15 T202 |
| 4.13 | `decide()` 14 args → `decide(situation, config)` | Missing | → 15 T202 |

### §5 Rules

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 5.1 | `Rule` protocol: `name`, `stage`, `check` → always a `RuleOutcome` | Missing | → 15 T202 |
| 5.2 | `fire` / `skip` helpers | Missing | → 15 T202 |
| 5.3 | `RULES` one tuple grouped by stage | Missing | Today a tuple with phase comments (`policy/chain.py:27-38`) → 15 T202 |
| 5.4 | `AnswerOrReport` an always-firing rule; `PolicyBug` unreachable (tested) | Missing | → 15 T202, T204 |
| 5.5 | StaleData `match` over the enum, `assert_never` | Missing | → 15 T241 |
| 5.6 | `Action` factories (`Action.research(...)`) | Missing | → 15 T202 |
| 5.7 | Rule reads only `Situation`+config; import-linter | Missing | → 15 T206 |
| 5.8 | > 3 branches → split (AnswerOrReport) | Missing | Timing pending (15 §H D3); 13t T041 rewrites these branches anyway |
| 5.9 | `why` written for a complaint reviewer (keys, sums, fields) | Partial | 13t T041 "reason names the goal and the rule" → 15 T202 |
| 5.10 | Stable rule names (metrics, records) | Missing | → 15 T202, T222 |
| 5.11 | Spec refs only in `requirement: ClassVar` | Partial | code-shape rule 5 (`doc`) → 15 T202 |

### §6 Node and routes

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 6.1 | `PolicyIn` from sections; missing section → `ContractError` | Partial | 14t T102 (C1 flat keys), T120 (C3 sections); content (`DecisionHistory`, `ResearchState`) → 15 T230 |
| 6.2 | `PolicyOut.next()` → `ROUTES[...]` as `goto` | Differs | 14s D4 / 14t T130 "policy stays a conditional edge" (approved) → 15 keeps the edge, built from `ROUTES` (§H D8) |
| 6.3 | `@node("policy", retry=Retry.NONE)` | Covered | 14t T101, T104 |
| 6.4 | `situation_from` the only board→facts place, pure | Missing | → 15 T211 |
| 6.5 | `ctx.case()` once per turn; a save refreshes the cache | Covered | 14t T110 (lazy cache), T113 (drop on conflict); "save updates the cache" implicit — edit E5 |
| 6.6 | `ctx.last_report_fingerprint()` once per turn | Partial | 14s D1 puts the fingerprint in the `chat` section (C3); before C3 → 15 T211 |
| 6.7 | `hops` gone; pass number = history length | Differs | 14s D1 keeps hops → 15 T230 + edit E7 |
| 6.8 | `action` key gone; outcome from `decision.last` or `reply.outcome`, never from understanding | Partial | 14s D1 (`reply` owns action/outcome), 14t T103; readers listed in 15 §B → T230 |
| 6.9 | One `ROUTES` table; `POLICY_ROUTES` and `route_policy` deleted | Missing | → 15 T203 (edit E6 to 14s D4) |
| 6.10 | Completeness test `set(ROUTES) == set(get_args(ActionKind))` + nodes exist | Missing | `backend/tests/graph/test_graph_shape.py` pins edges, not completeness → 15 T203 |
| 6.11 | Each action marked terminal / back to assess | Differs | Not a binary in the graph (§C) → 15 T203 `Continuation` END / SUSPEND / LOOP |

### §7 Traceability

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 7.1 | One `policy_decisions` row per pass via `DecisionLog` | Partial | 13t T033 `policy_trail` field per turn → owner choice (§H D9); 15 T220 |
| 7.2 | Row fields: address, situation w/o card + case_version, config_hash (+config table), rules_version, trail, decided_by, action, next_node | Missing | → 15 T220–T221 |
| 7.3 | Replay property from the row | Missing | → 15 T224 |
| 7.4 | Structured log `policy.decided` | Missing | stdlib logging (`dialog/report_writer.py:21`) → 15 T222 |
| 7.5 | OpenTelemetry span `policy.decide` | Missing | No OTel in code (§A); proposal: drop (§H D1) |
| 7.6 | Prometheus: decisions{rule,action}, passes histogram, pass-limit, input errors{field} | Missing | 13t T036 has understanding metrics only → 15 T213, T222 |
| 7.7 | Alert on pass-limit growth | Missing | `deploy/prometheus/automind-rules.yml` exists → 15 T222 |
| 7.8 | CLI "why" | Partial | 13t T035 `turn show` prints `policy_trail` → 15 T223 (renderer reused by T035, edit E3) |
| 7.9 | Admin endpoint with the same data | Missing | §H D4 |
| 7.10 | `--replay` on current code | Missing | → 15 T223 |
| 7.11 | `export <turn_id>` → YAML fixture | Missing | → 15 T223 |
| 7.12 | PII masking on export (evidence words, region) | Missing | → 15 T223 |

### §8 Reliability

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 8.1 | Invariant: CarFacts per case car, none extra | Missing | → 15 T213 |
| 8.2 | Invariant: assessment version == case version | Missing | Needs a new `assessed_version` field (§A) → 15 T213 |
| 8.3 | Invariant: cost ≥ 0 | Missing | → 15 T211 |
| 8.4 | Invariant: `pass_no ≤ max_passes + 1` else `PolicyBug` | Missing | → 15 T202, T213 |
| 8.5 | Invariant: no case but car assessments | Missing | Subsumed by 8.1 (empty case = `CaseFile()`, `context.py:24`) → 15 T213 |
| 8.6 | Input errors end the turn FAILED with a plain message | Partial | Exists: `turn/endings.py:39-50,56` (any unknown exception) → 15 T213 (no new ending) |
| 8.7 | Log + `policy_input_errors_total{field}`; no retries | Missing | → 15 T213 (`Retry.NONE` from 14t T104) |
| 8.8 | An exception inside a rule is never swallowed | Partial | True today (`policy/chain.py:44-48` no try); untested → 15 T204 |
| 8.9 | `PolicyConfig` built once at composition root; invalid → no start | Missing | → 15 T210 |
| 8.10 | No `settings()`, `ref.search`, `DEFAULT_*` in policy code | Missing | → 15 T210 |
| 8.11 | Config hash in every decision | Missing | → 15 T221 |
| 8.12 | Case + fingerprint from the turn cache | Partial | 14t T110 (case) → 15 T211 |
| 8.13 | Policy writes only the decision record, idempotent on (turn_id, pass_no) | Missing | → 15 T220 |
| 8.14 | Record write error: ERROR log + metric, turn goes on; no `except Exception: return` | Partial | 13t T033 has the same rule for `turn_understanding` → 15 T220 |

### §9 Testing

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 9.1 | Table tests per rule branch (fired / skipped with reason) | Missing | 32 existing tests, not per branch (§A) → 15 T204 |
| 9.2 | Order tests (two rules apply → earlier wins) | Missing | → 15 T204 |
| 9.3 | Hypothesis properties: no `PolicyBug`; trail ends with the decider; at the limit the decision is terminal | Differs | Source: terminal "at `pass_no = max_passes`"; today the limit fires at pass `max_passes + 1` (§A) → 15 T204 |
| 9.4 | Termination simulator (≤ 4 passes) | Differs | Needs the three-valued continuation (§C); SUSPEND ends the turn → 15 T204 |
| 9.5 | Golden situations from `export` | Missing | 13t T004 is message → Intent/Action.kind with a real model, not policy fixtures → 15 T223–T224 |
| 9.6 | Record round-trip | Missing | → 15 T224 |
| 9.7 | Routes contract test | Missing | → 15 T203 |
| 9.8 | Module boundaries via import-linter | Missing | No policy contract (§A) → 15 T206 |
| 9.9 | `situation_from` fails on each invariant | Missing | → 15 T213 |
| 9.10 | One situation builder | Missing | → 15 T204 |
| 9.11 | Regression vs old code, Hypothesis 10 000, `action.kind` equal except documented | Missing | → 15 T205 (10 000 in the PR run, smaller derandomized run in `check.sh`, §H D10) |

### §10 Migration steps and risks

| # | Requirement | Status | Where / note |
|---|---|---|---|
| 10.1 | Step 1: skeleton, rules 1:1, 10k regression | Missing | → 15 PL1 (now, beside 13 S2 / 14 C1) |
| 10.2 | Step 2: `situation_from`, config, case/fingerprint cache, feasibility out of node; invariants metric first | Partial | 14t T110 (cache) → 15 PL2 (after 14 C2) |
| 10.3 | Step 3: `policy_decisions` (Alembic), `DecisionLog`, logs, metrics, why/export | Partial | 13t T033/T035 (per-turn trail, `turn show`) → 15 PL3 (before 13 S3) |
| 10.4 | Step 4: ROUTES; decision history; adapter while WAITING turns exist | Partial | 14t T122 (adapter mechanism); ROUTES → 15 PL1 (§H D7); history → 15 PL4 with 14 C3 |
| 10.5 | Step 5: `ResearchStatus`, first behaviour change, then Intent | Partial | Intent = 13t T041 (S4) → 15 PL5 (before 13 S4, §H D5) |
| 10.R1 | Invariants: metric first, fix upstream | Partial | Same pattern as 14s G2 (node contracts) → 15 T213 |
| 10.R2 | Table growth: no card in the row; monthly partitions, 90 days | Missing | Retention loop exists only for acquisition (`acquisition/infrastructure/retention.py`, started `delivery/web/app.py:90`) → §H D2 |
| 10.R3 | WAITING turns with old keys: adapter reads `hops`, `cost_approved`, `research_*` | Partial | 14t T122 → edit E8 (+ these keys) |
| 10.R4 | Decimal at the `situation_from` boundary (cents) | Missing | → 15 T211 |
| 10.R5 | Grep readers of `action`/`decision` before step 4 | Partial | 14t T103 ("verify nothing depends"); readers verified in 15 §B10 |

### §11 Open questions → 15 §H

| # | Question | Proposal (15 §H) |
|---|---|---|
| 11.1 | OpenTelemetry or log + table only? | No OTel in code: log + `policy_decisions` + Prometheus; no span (D1) |
| 11.2 | Keep `policy_decisions` 90 days? | 90 days, deleted daily by a chat retention step; no partitions at ≤ 9 rows/turn (D2) |
| 11.3 | Split `AnswerOrReport` at step 1 or after Intent? | After: in 13t T041, where its request-label branches become goal rules (D3) |
| 11.4 | Admin page or CLI? | CLI now; the read port allows an endpoint later (D4) |
| 11.5 | Real `max_passes` (8 now, test expects ≤ 4)? | Keep today's semantics (8 + the limit pass); decide from `policy_passes_per_turn` 2 weeks after PL3 (D6) |

### Counts (rows of §B, without §11)

| Status | Count |
|---|---|
| Covered | 5 |
| Partial | 32 |
| Missing | 70 |
| Differs | 9 |
| **Total** | **116** |

## C. `ROUTES` table vs the code

Source §6.2 table vs `ActionKind` (`domain/decision.py:13-25`), `route_policy` (`dialog/nodes/understand.py:132-145`),
graph nodes (`backend/tests/graph/graph_shape.json`, `graph.py`):

| ActionKind | Source → node | Today `route_policy` | Node exists | What follows the node (graph) | Continuation |
|---|---|---|---|---|---|
| `ANSWER_GENERAL` | `general` | `general` | yes | END (`graph.py:74`) | END |
| `ASK` | `ask` | `ask` | yes | END | END |
| `SELECT_CANDIDATES` | `select_candidates` | same | yes | `identify` or `general` (`graph.py:99-100`) — **not** assess | LOOP (via identify → assess) |
| `CONFIRM_INTAKE` | `prepare_intake` | same | yes | `wait_intake` interrupt; resumed next turn → `assess` / `interpret` / `identify` (`graph.py:58-60`) | SUSPEND |
| `CONFIRM_VARIANTS` | `prepare_variants` | same | yes | `wait_variants`, or straight to `assess` when nothing to confirm (`graph.py:64`) | SUSPEND (or LOOP) |
| `CONFIRM_COST` | `prepare_cost` | same | yes | `wait_cost` → `assess` / `interpret` | SUSPEND |
| `FEASIBILITY` | `prepare_feasibility` | same | yes | `wait_feasibility` → `assess` / `interpret` / `alternatives` (`graph.py:67-69`) | SUSPEND |
| `RESEARCH` | `plan_research` | same | yes | research rounds → `after_research` → `assess` (`graph.py:102-106`); may pause at `prepare_limit` | LOOP (or SUSPEND) |
| `ANSWER_FROM_CONTEXT` | `answer` | same | yes | END | END |
| `REPORT` | `report` | same | yes | END | END |
| `RESCORE` | `report` | same | yes | END | END |

Result: **no name mismatch** — all 11 kinds, all 10 targets exist; `set(ROUTES.values())` equals `POLICY_ROUTES`
(`graph.py:52-53`). Mismatches are of meaning:
1. "Terminal or back to assess" (source §6.2) misses SUSPEND (5 kinds end the turn in an interrupt) and
   `SELECT_CANDIDATES` re-entering through `identify`. A termination test that treats SUSPEND as "loop" never ends.
2. `"CONFIRM_LIMIT"` (`nodes/research.py:90`) is an outcome outside `ActionKind`; not a policy route, but it shows
   the turn outcome set ≠ `ActionKind` (matters for "outcome from `decision.last` or `reply.outcome`").
3. 13t T041 adds `ANSWER_AND_REASK` — a new kind that needs a route (completeness test T203 enforces it).

## D. Other checks requested

| Check | Result |
|---|---|
| OpenTelemetry in observability | None (§A) |
| import-linter configured | Yes, in CI (`scripts/check.sh:66`); no `chat.dialog.policy` contract |
| Hypothesis a dependency | Yes, dev (`backend/pyproject.toml:40`) |
| mypy --strict on `dialog/policy` | Yes, already clean |
| Existing policy tests | Yes: 32 unit + graph tests (§A) |
| `structure_baseline.txt` debt in policy | `scripts/structure_baseline.txt:1371-1372` `word` (strings compared in `intake_step`); 15 T202 should clear them (ratchet goes down) |

## E. Edits to 013/014 (proposed, not applied)

| # | File / place | Edit | Why |
|---|---|---|---|
| E1 | 13s §D5 | "One record per turn, `turn_understanding` (… intent, ~~policy_trail~~) …" + "Policy passes: `policy_decisions` (spec 015), joined by `turn_id`." | One owner of the policy trace: 015 |
| E2 | 13t T033 | Fields: drop `policy_trail`; add "the policy part is spec 015 `policy_decisions` (T220), read by `turn_id`." | Same |
| E3 | 13t T035 | "`turn show` prints … intent, and the policy passes through spec 015's `why` renderer (T223)" instead of `policy_trail` | One renderer |
| E4 | 13t T041 | Rewrite: "Policy reads `Intent` **on spec 015's `Rule`/`Situation`/`Decision`** (PL1–PL3 done first): `Situation.intent` replaces `request` (one, not both); new rules are `Rule` classes with `RuleOutcome` reasons (`ANSWER_AND_REASK`, `stop`, goal order per G6); `AnswerOrReport` split into goal rules here (015 §H D3); `ANSWER_AND_REASK` added to `ActionKind` and `ROUTES` (015 T203 completeness test); the trail is `Decision.trail` in `policy_decisions` (015 T220), not a `turn_understanding` field." | T041 otherwise writes rules in the old function shape that PL1 has just replaced |
| E5 | 14t T110 | Add: "`save_case` updates the cache; spec 015 T211 adds `last_report_fingerprint()` cached the same way." | 015 6.5/6.6 |
| E6 | 14s D4 + 14t T130 | "The policy stays a conditional edge; its path map and router are built from `ROUTES` (spec 015 T203); `POLICY_ROUTES` is deleted." | One routes table without breaking 014 G1 |
| E7 | 14s D1 table + 14t T120 | `decision` section: "~~Action, hops~~ `DecisionHistory` (spec 015 T230): the passes of this turn; pass number = length; no `hops`." `reply`: "`action` = the turn's outcome kind, the only `action`." | 015 6.7/6.8 |
| E8 | 14t T122 | Add: "the adapter maps `decision`, `hops`, `action`, `cost_approved`, `research_declined`, `research_done` of an old blob (spec 015 T231)." | 015 10.R3 |
| E9 | 13t T036 | Add: "Policy metrics are spec 015 T222 (not here)." | Avoid two metric owners |
| E10 | 13t T043 | "policy rules answer/general/limits" → "policy rules via `Situation.intent` (T041 on spec 015)". | Same reader moved once |
