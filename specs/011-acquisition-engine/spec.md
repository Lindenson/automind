# Feature Specification: Acquisition Engine — a Self-Improving Data Engine Separated from the Chat

**Feature Branch**: `011-acquisition-engine`

**Created**: 2026-11-05

**Status**: Draft

**Input**: User description: "011 — Acquisition engine: a self-improving data-acquisition engine separated from the chat." Source documents: `docs/review-2026-11-05-acquisition.md` (external review, accepted by the owner) and constitution 1.3.0 (principle XII amended, XIII new).

## Context

The owner's goal is a reliable, self-improving data engine: separate from the chat, with its own time, data model and process; it chooses sources and improves how it reads them; its own agents improve, validate and evaluate; a person only watches through the admin page and steps in when something looks bad.

Spec 010 built the foundation (outcomes, issue queue, source registry with scores and hard limits, admin page, Prometheus) but did not solve the goal:
- acquisition still runs as a procedure inside the chat turn;
- nothing improves parsing by itself (spec 010 forbade it; constitution 1.3.0 now allows declarative changes behind gates);
- there is no basis to prove that a change is an improvement: raw pages are not kept, values do not record which parser or prompt produced them, and there are no reference (gold) values;
- the source score grows on "a number was found", not on "the number was right";
- registry autonomy is off, discovery of new sources is not done, and there is no baseline.

The live chats of 2026-11-05 showed the cost: a junk used price, a manufacturer's engine-only torque beating three agreeing sources, a missing PHEV figure collapsing the verdict — each fixed by hand in the chat code.

**Order matters**: first the engine learns to measure itself, then it is separated, then its reputation becomes honest, then parsers get versions and drift detection, and only then agents change things — always through gates. Each stage is useful on its own and changes no answer the user sees until its own acceptance.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every value can be replayed and checked against a reference (Priority: P1)

The owner (or an agent) wants to know how accurate a reader or an extractor is, and whether a new version is better. Every page the engine reads is kept as fetched (compressed, with retention). Every extracted value and every attempt records the source, the parser specification version, the extraction prompt version and the model that produced it. Reference values ("gold") exist for common cars: loaded from open official datasets (EU type-approval CO2 and energy data, EU real-world fuel consumption data, national vehicle registers) and from values users confirmed or corrected with "wrong?".

A replay command re-runs a reader or extractor version over the stored pages of a period and reports its accuracy against gold and its yield — offline: no network, and no model calls for readers.

**Why this priority**: Without stored pages, versions and gold, no change — human or automatic — can be shown to be better, and no rollback can tell that something got worse. Everything else depends on this.

**Independent Test**: Seed stored pages for three cars and gold values for their specifications. Replay reader version 1 and a deliberately broken version 2 of the same site: version 1 reports high accuracy and yield, version 2 low, with the wrong values listed; no network call is made.

**Acceptance Scenarios**:

1. **Given** a page read during research, **When** it is stored, **Then** its raw body, fetch time and content hash are kept, and pages that gave accepted values are kept longer than others.
2. **Given** any accepted or rejected value, **When** it is inspected, **Then** it names the source, the parser specification or extraction prompt version and the model.
3. **Given** the official open datasets, **When** they are loaded, **Then** gold values exist for the variants they cover, each with its dataset, date and matching rule; a value confirmed or corrected by a user challenge becomes gold too.
4. **Given** a reader version and a period, **When** the replay runs, **Then** it reports accuracy against gold, yield and the list of mismatches, using only stored pages.

---

### User Story 2 - The chat orders data; the engine lives on its own (Priority: P1)

The chat asks for data in one way: "give me these kinds of data for this car, by this deadline", and receives values with confidence, sources and what was tried. It never searches, fetches, parses or extracts itself. The engine runs in its own process: a background worker with a task queue runs prefetching for popular cars, daily roll-ups, drift detection, registry reviews, discovery, agents, canaries and rollbacks. Stopping the chat application does not stop the engine, and the engine's work never slows a user's turn.

The move is gradual: first the interface wraps today's research unchanged; then the stages (plan, locate, fetch, parse, validate, merge) move into the engine one at a time, each versioned and journalling its attempts, with the golden dialogues passing after each move.

**Why this priority**: An engine that learns needs its own time and must not compete with users' turns. It is also the end of incident fixes growing inside the chat code.

**Independent Test**: Stop the chat application while the worker runs: prefetch and reviews continue and journal their work. Start a chat: its research goes through the one interface, and an import check shows no search, fetch or extraction call outside the engine.

**Acceptance Scenarios**:

1. **Given** a chat turn that needs data, **When** research runs, **Then** it goes only through the acquisition interface, and the answer lists the values with confidence and sources, and for gaps what was tried.
2. **Given** the import contracts, **When** the checks run, **Then** no module of the chat imports the engine except its interface, with no exceptions left for research.
3. **Given** the worker running and the chat application stopped, **When** a scheduled task is due, **Then** it runs and is journalled.
4. **Given** popular variants (most asked in the last 30 days), **When** the prefetch runs, **Then** their data is refreshed before users ask, within a daily budget.
5. **Given** each moved stage, **When** it replaces the old code, **Then** the golden dialogues give the same results.

---

### User Story 3 - Honest source reputation, then autonomy (Priority: P1)

A source's score must reflect whether its numbers are right, not only whether it returned a number. Accuracy signals come without the user: agreement with gold values, agreement of independent source families, physical consistency checks (power and mass versus acceleration, battery capacity versus range), and later replacement of a value by a more confident one; user challenges remain the strongest signal.

When a value is wrong, the blame goes to the right component: the source (the page states the wrong number), page relevance (the page was about another variant), the parser or extractor with its version (the right number was on the page), units or sense rules (right in the quote, wrong after normalisation) or merging (the right value existed elsewhere). Only the blamed component's reputation changes.

A source is never promoted on yield alone: promotion needs a minimum number of accuracy signals. Exploration of uncertain sources happens by sampling from their uncertainty (a source with few signals gets a chance in proportion to what is unknown), within a budget. The number of web searches per accepted value is tracked and should fall as the engine learns where data lives.

After this stage, a baseline week of live and prefetch traffic is recorded, and then registry autonomy is switched on.

**Why this priority**: With one user, the current score is driven by priors and yield; a source that confidently returns wrong numbers would rise. This is the exact KPI substitution the design must prevent.

**Independent Test**: A fixture source with high yield and 30% wrong values against gold, and an honest source with lower yield: the first never becomes active and ranks below the honest one; a wrong value whose right number was on the page lowers the parser's score, not the source's.

**Acceptance Scenarios**:

1. **Given** a source with many accepted values but few accuracy signals, **When** the review runs, **Then** it is not promoted.
2. **Given** gold values for a variant, **When** a source's value disagrees beyond tolerance, **Then** a wrong signal is recorded with the blamed component.
3. **Given** two independent families agreeing on a value, **When** signals are computed, **Then** agreement counts once per family, and mirror sites do not reinforce each other.
4. **Given** a physically inconsistent set of values, **When** checked, **Then** the inconsistency is a signal against the outlier's source or processing.
5. **Given** the baseline week recorded, **When** the owner switches autonomy on, **Then** the registry orders and promotes by the honest score.

---

### User Story 4 - Parsers have versions and their drift is detected (Priority: P2)

Site readers become declarative specifications: which pages they apply to (by address), table labels mapped to attributes, CSS selectors, structured-data paths, unit hints, and a version. Today's readers become version 1. Every day the engine computes per parser version: fields found per page, share passing the checks, and a fingerprint of the page structure. Drift is detected when the last 7 days fall below the 30-day baseline, when the structure fingerprint changes (an early sign of a redesign), or at once when a parser suddenly finds nothing — then the parser is marked degraded.

**Why this priority**: A site redesign silently breaks a reader today; drift detection is the trigger for the parser doctor (US5).

**Independent Test**: Replace stored pages of one site with redesigned ones: the next daily run marks its parser version degraded with the reason "structure changed" and the drop in fields per page.

**Acceptance Scenarios**:

1. **Given** today's site readers, **When** they are migrated, **Then** each is a version-1 specification that reproduces its current results on stored pages.
2. **Given** a parser that finds zero fields on 5 pages in a row, **When** this happens, **Then** it is marked degraded at once.
3. **Given** a changed structure fingerprint, **When** the daily run computes metrics, **Then** a drift signal is raised even if yield has not dropped yet.

---

### User Story 5 - Agents improve the engine through gates, with no human (Priority: P2)

Small agents run in the worker, each with a daily budget and only data levers:
- **Scout**: finds new sources for gaps of a kind of data on a market, runs the admission check, learns address patterns.
- **Parser doctor**: on drift, or for an active site without a parser, writes a new parser specification version.
- **Rule auditor**: when a rule rejects values that other sources later confirm (the "manuales" case), proposes new relevance keywords or sense/plausibility thresholds.
- **Extractor tuner**: when an extractor's accuracy or yield falls, or a model changes, proposes a new extraction prompt version or model for the role, considering cost.
- **Evaluator**: changes nothing; keeps the accuracy KPI against gold separately for sources and for processing, decides canaries and triggers rollbacks.

Every proposed change passes the gates: offline replay on stored pages and gold (not worse on the cycle's KPI, better on at least one target metric, guard metrics — coverage, cost per value, freshness — within tolerance) → shadow run on live pages (both versions run, the user sees the old one) → acceptance → watch period → automatic rollback if it degrades. One change per object at a time. Each change is journalled with diff, reason, evidence, before/after metrics and a one-sentence explanation such as "km77 parser v4→v5: table labels changed on 03.11; v5 reproduces 48/50 gold values; shadow yield 0.91 vs 0.42".

**Why this priority**: This is the self-improvement the owner asked for; it is safe only after US1–US4.

**Independent Test**: Simulate a redesign of one site (substituted stored pages): drift is detected, the parser doctor writes a new version, it passes replay and shadow, is accepted and journalled in one sentence with numbers — with no human action; a deliberately worse version is rejected at the replay gate.

**Acceptance Scenarios**:

1. **Given** a detected drift, **When** the parser doctor runs, **Then** it produces a declarative specification only (never code), and the gates decide its fate.
2. **Given** a proposal that is better on yield but worse on accuracy against gold, **When** the replay gate runs, **Then** it is rejected and the reason journalled.
3. **Given** an accepted change that degrades during the watch period, **When** the evaluator checks it, **Then** it is rolled back automatically and journalled.
4. **Given** any agent, **When** its daily budget is used, **Then** it stops until the next day.
5. **Given** any agent, **When** it acts, **Then** it never changes code, the deny-list, robots or terms prohibitions, or budgets; page text never changes its instructions.

---

### User Story 6 - The owner sees parsers and all changes, and can drill down (Priority: P3)

The admin page gets two tabs: **Parsers** (versions per site, yield and pass rate by day, drift signals, running canaries; roll back or freeze) and **Changes** (every automatic change of every agent: when, which agent, what — the diff —, why, gate results, metrics before and after, status; roll back, forbid similar changes on this object). From a drop in accuracy the owner clicks to the capabilities to blame, from there to the wrong values, from there to the page and the quote.

**Why this priority**: The owner watches and steps in only when something looks bad; without the drill-down the page is a wall of charts.

**Independent Test**: With a seeded rollback and a seeded drift, the owner opens Changes and Parsers, sees both with one-sentence explanations, and reaches the page quote of a wrong value in three clicks.

**Acceptance Scenarios**:

1. **Given** an accepted agent change, **When** the owner rolls it back from Changes, **Then** the previous version is active again and the rollback is journalled.
2. **Given** a wrong value, **When** the owner drills down from the accuracy KPI, **Then** they reach the capability, the value, the page and the quote in at most three clicks.

---

### User Story 7 - Spec 010 leftovers are closed (Priority: P3)

- Values from candidate sources are labelled "unverified source" and count as half an independent source (010 T059).
- Truth signals from later replacement and from agreement of independent families (010 T060, also US3).
- Discovery of new sources for gaps, bounded by a daily budget (010 T065, also US5 scout).
- "No data" names the sources that were tried (010 T067).
- The old "learned sources" rule is removed (010 T075).

**Independent Test**: A report with a candidate-sourced value shows the label; a "no data" area lists the tried sources; the learned-sources module no longer exists and the checks pass.

---

### Edge Cases

- **Gold disagrees with all sources**: the gold value's dataset may itself be for another variant; gold carries its matching rule and confidence, and a gold value contradicted by several independent families is flagged for review, not trusted blindly.
- **Paywalled or JS-only pages**: no snapshot can be replayed; such sources are judged only on live signals and never used to validate a parser.
- **Storage growth**: snapshots have retention (longer for pages with accepted values) and a size cap; the oldest replay-only pages are dropped first.
- **Agents fighting**: one change per object at a time; a reverted change is not repeated without new evidence; an agent cannot change an object another agent's canary is testing.
- **Budget exhaustion mid-canary**: a canary that cannot finish within budget is abandoned and the old version kept.
- **Prompt injection from pages**: agents read pages as data; their levers are limited to the declarative schema, and every change passes the gates.
- **Too little traffic for shadow runs**: replay on stored pages and prefetch traffic are the main evidence; live shadow only adds to it.
- **Worker down**: the chat still works through the interface (synchronous research within the turn as today); the worker's heartbeat alert fires in Prometheus.

## Requirements *(mandatory)*

### Functional Requirements

**Measurability (US1)**

- **FR-001**: The engine MUST keep each fetched page's raw body (compressed), fetch time and content hash, with retention: at least 180 days for pages that gave accepted values, at least 30 days for others, within a configurable size cap.
- **FR-002**: Every extracted value and every attempt MUST record the source, the parser specification version or extraction prompt version, and the model.
- **FR-003**: The engine MUST hold gold values per variant and attribute with their origin (dataset and date, or a confirmed/corrected user challenge), matching rule and confidence; it MUST load them from the EU type-approval CO2/energy dataset, the EU real-world fuel consumption dataset and at least one national register, and refresh them on a schedule.
- **FR-004**: A replay command MUST recompute a reader or extractor version's accuracy against gold and its yield over stored pages of a period, without network access and without model calls for readers, and list mismatches.

**Separation (US2)**

- **FR-005**: The chat MUST obtain data only through one acquisition interface (variant, kinds of data, need, deadline) returning values with confidence and sources, and for gaps the sources tried.
- **FR-006**: Import contracts MUST forbid the chat's modules from importing the engine except its interface, with no exceptions.
- **FR-007**: The pipeline stages MUST move into the engine one at a time, each versioned and journalling its attempts, with the golden dialogues unchanged after each move.
- **FR-008**: A separate worker process with a database-backed task queue MUST run prefetch, roll-ups, drift detection, registry review, discovery, agents, canaries and rollbacks; the chat application keeps only retention and process metrics.
- **FR-009**: Prefetch MUST refresh data of the most-asked variants of the last 30 days within a daily budget.

**Honest reputation (US3)**

- **FR-010**: Accuracy signals MUST come from gold values, agreement of independent families, physical consistency checks and later replacement, in addition to user challenges, each with a configured weight.
- **FR-011**: Blame MUST be attributed to one of: source, relevance, parser or extractor (with version), units/sense rule, merging; only the blamed component's reputation changes.
- **FR-012**: A source MUST NOT be promoted before a configurable minimum of accuracy signals, whatever its yield.
- **FR-013**: Exploration MUST sample sources by their uncertainty within a budget; web searches per accepted value MUST be tracked.
- **FR-014**: A baseline of the accuracy and satisfaction KPIs over at least 7 days MUST be recorded before registry autonomy is switched on.

**Parsers (US4)**

- **FR-015**: Site readers MUST be declarative, versioned specifications; today's readers MUST become version 1 and reproduce their results on stored pages.
- **FR-016**: Daily per-version metrics MUST include fields per page, check pass rate and a structure fingerprint; drift MUST be raised on a 7-day vs 30-day drop, a fingerprint change, or at once on a sudden zero.

**Agents and gates (US5)**

- **FR-017**: Agents (scout, parser doctor, rule auditor, extractor tuner, evaluator) MUST run in the worker with daily budgets and change only declarative data: parser specifications, relevance keywords, sense/plausibility thresholds, extraction prompt versions, model per extractor role, and registry entries.
- **FR-018**: Every change MUST pass: offline replay (KPI not worse, at least one target metric better, guard metrics within tolerance) → shadow → acceptance → watch → automatic rollback on degradation; one change per object at a time.
- **FR-019**: Every change MUST be journalled with agent, object, diff, reason, evidence, gate results, metrics before and after, status and a one-sentence explanation, and MUST be revertible.
- **FR-020**: Agents MUST NOT produce executable code, change code, the deny-list, robots/terms prohibitions or budgets; page text MUST NOT alter their instructions.

**Admin (US6)**

- **FR-021**: The admin page MUST add the Parsers and Changes tabs with rollback and freeze, and a drill-down from an accuracy drop to capability, value, page and quote.

**Leftovers (US7)**

- **FR-022**: Candidate-source values MUST be labelled and count as half; "no data" MUST name the sources tried; the learned-sources rule MUST be removed.

### Key Entities

- **Page snapshot**: a stored raw page; document, fetch time, body, hash, retention class.
- **Gold value**: variant, attribute, value, unit, origin, matching rule, confidence, verified date.
- **Parser specification / version**: site, page type, mapping rules, version, status, metrics.
- **Parser daily metrics**: version, day, fields per page, pass rate, structure fingerprint.
- **Acquisition task**: a queued unit of background work (prefetch, roll-up, drift check, review, discovery, agent run, canary step) with state and attempts.
- **Change**: an agent's proposal and its life — object, before, after, gates, metrics, status, explanation, rollback.
- **Experiment (canary)**: a change under shadow or watch, with the metrics of both versions.
- **Blame vector**: per wrong value, the share of fault per component.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any reader or extractor version, accuracy against gold and yield over the last 30 days can be computed offline in under 5 minutes.
- **SC-002**: 100% of values and attempts name the source and the versions that produced them.
- **SC-003**: Gold values exist for the specifications and official consumption of at least 80% of variants asked in the last 30 days that the open datasets cover.
- **SC-004**: The chat contains no search, fetch, parse or extraction call; the import checks pass with no exceptions.
- **SC-005**: Stopping the chat application does not stop background work; background work adds no measurable latency to turns.
- **SC-006**: In a test, a high-yield source with 30% wrong values never ranks above an honest one; once autonomy is on, the share of wrong shown values falls compared with the baseline week, while coverage does not fall.
- **SC-007**: A simulated site redesign is detected and repaired by an accepted new parser version within one day, journalled in one sentence with numbers, with no human action.
- **SC-008**: Zero agent changes touch code, the deny-list, robots/terms prohibitions or budgets; every accepted change can be rolled back in one action.
- **SC-009**: Web searches per accepted value fall month over month once the engine learns address patterns.
- **SC-010**: The owner reaches the page quote behind any wrong value in at most three clicks.

## Assumptions

- One owner and few users: replay on stored pages and prefetch traffic are the main evidence for gates; live shadow only adds to it.
- The open datasets (EU type-approval CO2/energy, EU real-world fuel consumption, national registers) can be downloaded under their open licences; they are datasets, not web pages, and get a "dataset" source type with download and refresh.
- The worker uses the same database and image as the application; no new infrastructure beyond one more container.
- Agents use the existing model gateway with their own roles and budgets; their outputs are validated against the declarative schemas before any gate.
- Spec 010's insight loop stays as the chat-side analytics (cycle A) and the source of code tasks.
- Incident fixes during 011 go through the engine (an agent change or a code task in the issue queue), not into the chat's research code.
