# AutoMind baseline: what the system does on 2026-11-05

This page replaces reading specs 001–009. It says what is built, where it lives, and what is still open.
Paths are under `backend/src/automind/` unless stated. Config files are under `backend/config/`.
"Per spec, not verified in code" marks claims taken from a spec that were not checked in code.

## 1. Purpose and boundary

AutoMind is a chat-first automotive research system. The user talks to a car expert (the hub).
The hub keeps a versioned case file per chat: who the user is, new or used, budget, usage, priorities and the cars.
It identifies the exact versions of 1–3 cars, researches them on the web with evidence for every value,
scores them for this user's profile, costs ownership (TCO, energy, incentives) and writes a verdict-first report.
The market is Europe (owner's direction 2026-11-05: Europe is one market, no country preferred; much config is still Spain-first).
It is not a classifieds scraper, a dealer, or a price robot: it never scrapes classifieds and respects robots.txt and terms.

**Spec 010** (`specs/010-self-observing-registry/spec.md`, Draft) supersedes spec 009.
It adds self-observation (every turn leaves a scored outcome; failures are grouped, diagnosed and handed
to the owner as a ready task; the system never changes its own code or rules) and an autonomous source
registry (sources scored per kind of data; the system orders, adds and retires them and shows each change).
Spec 009's open data and dialogue fixes become the seeded issues of 010 US5.

## 2. Capabilities by area

### 2.1 Conversation and case file

- One LangGraph thread per chat (`thread_id = chat_id`); checkpoints in Postgres, separate from domain tables.
- Case file: Pydantic model, a new version per change, `changed_by` hub or user.
- The LLM proposes a typed `CaseDelta`; code applies it deterministically and logs the change.
- Profile fields record their basis (how each is known).
- User-stated energy figures are kept as `CaseFile.stated_energy`, labelled "your figure".
- Chats can be deleted (003 US4).
- WebSocket per chat with event `seq`; events persisted and replayed after `hello{last_seq}`.

| Where in code | From |
|---|---|
| `domain/casefile.py`, `application/chats.py`, `orchestration/state.py`, `infrastructure/checkpoint.py` | 002; ADR-003, ADR-011, ADR-013 |
| `api/ws.py`, `api/rest.py`, `infrastructure/events.py` | ADR-009 |

### 2.2 Understanding (interpreter, request kinds)

- Interpreter role turns each message into an `Interpretation` and a `CaseDelta`.
- Request kinds (`domain/policy.py: RequestKind`): compare, single, follow_up_question, weights_change,
  correction, research_more, general_question, confirm_yes, confirm_no, choose_for_me, and more.
- A code safety net takes two named cars from the user's words when the model returns none (PR #37–#40).
- Free-text replies to a confirmation resume the interrupt and are interpreted (may be a correction).

| Where in code | From |
|---|---|
| `application/interpret.py`, `orchestration/nodes/understand.py`, `orchestration/prompts/` | 002, 005, 007; ADR-007 |

### 2.3 Identification (ladder, versions cache, used cars)

- Open-world makes: make registry (`makes.yaml`, `aliases.yaml`) plus sourced line-ups of models on sale.
- `identify` runs after every `apply_delta` for each unsettled or changed car: IDENTIFIED, CHOICES, NEED or NOT_FOUND.
- Pure ladder: generation → engine (fuel → family → power) → gearbox → drive.
- What does not exist is said, and the question moves one level up. Never loops.
- "Choose for me" or two asks settle a level by the base version.
- Versions of each model generation: sourced shared cache `model_versions`, 60-day TTL; a miss costs one search, ≤ 3 pages, role `versions`.
- A version is kept only when its power is in its excerpt and the excerpt occurs in its document.
- Property test over 1,500 scenarios.
- Variant identity includes gearbox, drive and equipment level.

| Where in code | From |
|---|---|
| `domain/ladder.py`, `domain/identification.py`, `domain/identity.py`, `application/identify.py`, `application/resolve.py` | 005, 008; ADR-024, ADR-030, ADR-022 |
| `application/versions.py`, `application/lineup.py`, `application/makes.py`, `infrastructure/models_on_sale.py` | 005, 008 |
| `generations.yaml`, `makes.yaml`, `aliases.yaml` | |

### 2.4 Intake and questions

- Intake by code: questions from `questions.yaml`, chosen by value (`domain/ask_value.py`) and profile gaps (`domain/profile_gaps.py`).
- Profile asked when it matters: persona, ownership years, new or used, km per year, budget.
- Home charging question for electrified cars.
- One confirmation card before research (`CONFIRM_INTAKE`): cars, profile, cost estimate.
- Intake stays on task and replies in the user's language.

| Where in code | From |
|---|---|
| `domain/intake.py`, `application/intake_card.py`, `application/ask.py`, `orchestration/nodes/confirm.py`; front `IntakeCard.tsx` | 005, 007; ADR-025, ADR-027 |

### 2.5 Policy, actions and confirmations

- `domain.policy.decide` picks the action by fixed rules: ASK, CONFIRM_VARIANTS, CONFIRM_COST, CONFIRM_INTAKE,
  RESEARCH, ANSWER_FROM_CONTEXT, REPORT, ANSWER_GENERAL, FEASIBILITY, RESCORE.
- Case fingerprint prevents repeated actions. One unit test per rule.
- Confirmations: prepare → `interrupt` → apply, so side effects never repeat on resume.
- RESCORE recomputes scores, cost and verdict from validated data, no new research.
- Feasibility: honest answer when the request does not fit budget or usage.

| Where in code | From |
|---|---|
| `domain/policy.py`, `orchestration/graph.py`, `orchestration/nodes/*` | 002, 007; ADR-002, ADR-007, ADR-014 |
| `domain/feasibility.py`, `application/feasibility.py`, `feasibility.yaml` | 003 US3; ADR-019 |

### 2.6 Research pipeline

- **Plan**: `research_jobs` rows, run in parallel with `Send`; gap rounds by depth (Quick 0, Standard 1, Deep 2).
- **Search providers**: cache-first `Searcher` port over Serper (default), SerpAPI, Tavily; cache in `search_cache`.
- **Queries**: `queries.yaml`; used-car queries still carry no year in some paths (see section 3).
- **Favourites**: favourite sources per area and market in `sources.yaml`; deny-list of classifieds and ToS-forbidden sites there too.
- **Learned sources**: removed in spec 011 (T124); the source registry (`registry.yaml`) replaced them. The `learned_sources` table is no longer read or written.
- **Fetch**: own fetcher with deny-list, robots incl. Crawl-delay, 401/403 = disallow, redirect re-check, SSRF guard on user URLs.
- **Site readers**: deterministic parsers for favourite spec sites (`site_readers.yaml`).
- **Relevance**: gate before extraction; is this page about the exact variant? (role `relevance`). Brand pages judged by the make.
- **Extraction**: role `extractor`; every value carries a verbatim excerpt.
- **Checks**:
  - evidence/excerpt: excerpt must occur in the document; ellipsis and substring bugs fixed (007);
  - units: normalized by code;
  - sense: the value means what the attribute means (`sense.yaml`, `domain/sense_ev.py` for EV);
  - plausibility: ranges per attribute (`plausibility.yaml`);
  - generation-wide ranges rejected; uncertain pages go to the `validator` role;
  - each area has a minimum; below it the report says "insufficient data".
- "Find it" from the data panel researches only the chosen cars and areas, no interpretation call.

| Where in code | From |
|---|---|
| `application/research.py`, `domain/research_plan.py`, `domain/search_plan.py`, `orchestration/nodes/research.py` | 002, 003; ADR-006 |
| `infrastructure/search/{cache,serper,serpapi,tavily}.py` | 003; ADR-017 |
| `infrastructure/fetch.py`, `infrastructure/pages.py`, `infrastructure/site_readers/` | 003; ADR-018 |
| `domain/relevance.py`, `application/extraction.py`, `domain/evidence.py`, `domain/units.py`, `domain/sense.py`, `domain/plausibility.py` | 003, 006, 007; ADR-010, ADR-022, ADR-027 |

### 2.7 Report and guard

- Four steps: deterministic insights → code-built verdict → AI writes → guard checks the text.
- Verdict first; personal and concrete; sections per profile from `report_layouts.yaml`, collapsible, with depth.
- One data panel lists gaps with "find it" per car and area.
- Tech explainers (`tech_explainers.yaml`), insights (`insights.yaml`).
- Guard rejects numbers and claims not in the data; word-boundary matching (fixed in 007).
- Reporter has no tools. Reply in the user's language.

| Where in code | From |
|---|---|
| `domain/insights.py`, `domain/verdict.py`, `domain/report_layout.py`, `application/compose.py`, `orchestration/report_text.py`, `orchestration/guard.py`, `orchestration/nodes/report.py` | 004; ADR-021, ADR-023, ADR-026 |

### 2.8 Scoring, criteria, profiles, personas

- 13 criteria in `criteria.yaml`, 0–100 indices with named inputs.
- Persona default weights; profile rules shift weights (`profile_defaults.yaml`, `profile_rules.yaml`).
- Weight breakdown is visible; a change in the panel recalculates at once (RESCORE).
- Verdict and text speak to the profile (racer, expert, family).
- Status = price class + segment + sourced brand positioning, age-adjusted.
- Advice without named cars: candidates from cached line-ups and the catalog only (007 US7).

| Where in code | From |
|---|---|
| `domain/criteria.py`, `domain/weights.py`, `domain/metrics.py`, `domain/suggestions.py`, `application/candidates.py` | 002, 007; ADR-015, ADR-027 |

### 2.9 TCO, energy, EV/PHEV, incentives

- TCO rules `tco-1.0`, stored per turn with inputs; like-for-like period totals.
- One deterministic energy model per powertrain (ICE, HEV, MHEV, PHEV, BEV).
- Energy prices with dates (`energy.yaml`); home charging and the user's own prices.
- Climate and motorway factors; efficiency in €/100 km; break-even.
- EV facts: range, battery, charging; DGT label; new-brand warranty and network (`makes.yaml: new_in_market`).
- Incentives: market facts with dates, area `incentives`.
- PHEV without charge-sustaining consumption: energy line reads "cannot be computed" unless the user states it.
- Drag race: deterministic Euler model `dragrace-0.1.0` (002 US6; ADR-008).

| Where in code | From |
|---|---|
| `domain/tco.py`, `domain/cost.py`, `domain/energy.py`, `domain/incentives.py`, `application/incentives_research.py`, `application/electric_block.py`, `domain/dragrace.py` | 002, 006; ADR-008, ADR-012, ADR-028 |
| `energy.yaml`, `rates.yaml`, `prices.yaml`, `regions.yaml` | 006 |

### 2.10 Used cars

- A year not given is asked once, then assumed from mileage or generation (never age 0).
- Purchase price = used price, else "no data". Depreciation runs from the used price.
- Used price searched by model year; a generation-wide range never stands for one year (PR #50).
- Brand warranty researched; shown as remaining or expired.
- Mileage counts in reliability.

| Where in code | From |
|---|---|
| `domain/used.py`, `domain/reliability.py`, `domain/reviews.py` | 008 US4; ADR-019, ADR-030 |

### 2.11 Challenge "wrong?" and ratings

- `application/challenge.py` exists: the user can dispute a value and trigger a re-check.
- Ratings of answers and the "this source is bad" action are spec 010 US1–US2, not built yet.
- Checked in code: `recheck()` re-runs the research checks on the accepted claims behind the value, re-selects, and answers CONFIRMED / CORRECTED / REMOVED / UNRESOLVED without a model call. Rows go to `value_challenges` (turn_id and claim_id are left NULL); nothing reads them afterwards. Ratings (`report_ratings`) are only counted and averaged in the operator metrics.

### 2.12 Limits, budget, daily cap

- Per-turn limits enforced in the model gateway callback; every call recorded in `llm_calls`; searches in `search_calls`.
- Daily spend cap across all chats: `DAILY_CAP_EUR` (default €5.00, `config.py`); research pauses and asks.
- Limits ask "continue?", never cancel.
- Model per role in `models.yaml` (Gemini today), with fallbacks when a quota runs out.
- Hop counter, retries on LLM nodes, partial result on timeout (007).

| Where in code | From |
|---|---|
| `infrastructure/llm_gateway.py`, `infrastructure/usage_callback.py`, `application/usage.py`, `orchestration/retry.py` | 002, 007; ADR-005, ADR-029 |

### 2.13 Security and access

- Owner per browser: cookie `automind_owner`, random 32 bytes, HttpOnly, SameSite=Lax; chats isolated per owner.
- Same-site only; operator metrics behind `Authorization: Bearer <ADMIN_TOKEN>` (or localhost when unset).
- SSRF guard on user URLs (PR #22).
- API keys only in `.env`.
- Not done: accounts, per-owner rate limits, TLS.

| Where in code | From |
|---|---|
| `api/access.py`, `api/rest.py`, `config.py` | ADR-029 |

### 2.14 Deployment

- Modular monolith: domain → application → orchestration → infrastructure → api, enforced by import-linter.
- One API process (`--workers 1`), one container; per-chat advisory lock and a unique index forbid two running turns.
- One Docker Postgres 16 for dev, tests and deployment; Alembic migrations.
- Front: React + Vite + Tailwind + Zustand (`frontend/`).
- Scripts: `scripts/check.sh`, `dev.sh`, `deploy.sh up`, `db.sh`, `repair-data.sh`.
- MCP server: `mcp_server.py` (deterministic tools).

| Where in code | From |
|---|---|
| `api/app.py`, `infrastructure/db/`, `backend/alembic`, `docker-compose.yml` | ADR-001, ADR-004, ADR-020, ADR-026 |

## 3. Known limits and open flaws

Spec 009 is superseded by 010 (its header still reads "Draft"). Its fixes were never implemented.
"010 US5" = seeded as an issue in the 010 issue queue.

| Flaw | Source | 010 US5 |
|---|---|---|
| PHEV without charge-sustaining consumption; TCO compared anyway | 009, chat 20b5b7f9 | yes |
| Junk used price accepted (US-dollar market floor page) | 009 | yes |
| Gearbox rule matches " manual" inside "manuales" | 009 | yes |
| Generation stored as a bare year ("2024" not MQ4); facelift pages rejected | 009 | yes |
| Brand-wide service and warranty pages rejected | 009 | yes |
| Used-car searches carry no year | 009 | yes |
| First message got "could not map" | 009 | yes |
| "Find me a Kia" asks "which model" instead of proposing candidates | 009 | yes |
| Engines not sold in the car's year offered | 010 (chat 8c6a2a58) | yes |
| Seats and boot differ between reports of one chat | 010 (chat 8c6a2a58) | yes |
| No verified source registry; no per-source stats; no admission procedure | 009 US3/US4/US7 | no: 010 US6–US8 requirements |
| Used price from open sources (DAT, BOE tables, motor.es), residual estimate, user-pasted listings | 009 US2/US8 | per 010 text, not listed in US5 |
| Datasets (EEA OBFCM, EEA CO2, RDW, KBA…) need a "dataset" source type | next-session | no |
| Mirror sites counted as independent (no domain families) | review | no |
| Accounts, per-owner rate limits, TLS missing | review, ADR-029 | no |
| WebSocket Origin check | review | no (status not re-verified) |
| Prompt version not recorded per model call (the served model *is* recorded: the usage callback is built per fallback model) | code check 2026-11-05 | no — fixed by 010 FR-004 |
| Rescore queue in memory: lost on restart | next-session | no |
| Candidates only from cached line-ups and the catalog | next-session | no |
| Gemini + Serper stack not validated on the golden set (paid run) | review | no |
| No front component tests; mobile not checked | review | no |
| `.env.example` and layer table docs behind | review | no |
| BYD Seal U DM-i charge-sustaining consumption not found in sources | next-session | no (data gap) |
| Config still Spain-first (energy prices, DGT, incentives, versions "sold in Spain") vs Europe-as-one-market | owner 2026-11-05 | no |

## 4. Rules still in force

Copied from `docs/next-session.md`:

- Never scrape classifieds (deny-list in `backend/config/sources.yaml`); the robot never imitates a browser or bypasses anti-bot protection.
- Respect robots.txt and the site's terms of use (a terms clause forbidding automated access = deny-list).
- Announce any paid live run with a cost estimate first.
- API keys live only in `.env`; never print them.
- Reply to the owner in Russian.
- Destructive DB changes need the owner's yes and a backup first.
- Limits ask "continue?", never cancel.
- Commit, push and merge to main without review (owner's standing instruction).

## 5. Spec index

| Spec | Title | Status | One line |
|---|---|---|---|
| 001 | Ultimate Car Battle (MVP) | Superseded by 002 and `docs/vision.md` | Form-style 2–4 car battle; replaced by the chat-first design. |
| 002 | Conversational MVP | Implemented | Hub agent, case file, policy, research, criteria, TCO, drag race, limits. |
| 003 | Research quality and search v2 | Implemented | Search port (Serper), own fetcher, site readers, relevance, feasibility, chat delete, one Postgres. |
| 004 | Report experience | Implemented | Verdict first, insights before the AI, data panel with "find it", exact cars settled first. |
| 005 | User intake and identification | Implemented | Open-world makes, identify every turn, corrections, one confirmation card. |
| 006 | Electrified cars | Implemented (closed 2026-11-04) | Energy model per powertrain, EV facts, prices, incentives, new brands. |
| 007 | Profile drives the assessment | Implemented | Profile basis, visible weights, RESCORE, learned sources, review fixes. |
| 008 | Identification ladder, used cars as used | Implemented (plus PRs #48–#50) | Ladder over sourced versions cache; used price, depreciation, warranty. |
| 009 | Verified source registry | Superseded by 010 (not implemented) | Registry, admission, used price, 20b5b7f9 fixes; survey of 198 sites kept. |
| 010 | Self-observing AutoMind and autonomous source registry | Draft (current branch) | Scored turns, issue queue with ready tasks, self-ordering source registry. |

Spec status headers in files 002–008 still say "Draft"; "Implemented" here follows `docs/next-session.md` (all merged to main).
Survey data: `specs/009-source-registry/registry-survey.yaml` (198 sites; seed for 010 US8).
