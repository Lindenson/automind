# Feature Specification: Self-Observing AutoMind and an Autonomous Source Registry

**Feature Branch**: `010-self-observing-registry`

**Created**: 2026-11-05

**Status**: Draft

**Supersedes**: spec 009 (`specs/009-source-registry/spec.md`). Its registry, statistics, admission and discovery requirements are re-stated here with autonomy instead of manual review. Its data and dialogue fixes become the first entries of the issue queue (US5), not requirements of this spec.

**Input**: User description: "010 — Self-observing AutoMind and an autonomous source registry. Supersedes spec 009." Owner's decision of 2026-11-05 (full text in the conversation): complaints must stop reaching the coder as questions and new specs. For logic, parsers, rules and dialogue the system measures itself, groups failures, diagnoses them and hands the owner a ready task to paste into Claude Code; it never changes code or rules itself. For sources it is free: it orders, adds and retires them, and shows every change and every source's quality on its own page.

## Context

AutoMind improved one live chat at a time: a chat showed a flaw, a spec was written, the case was fixed. After four days and nine specs the system still has no memory of its own failures:

- report ratings are stored but only counted; their notes are never read;
- "wrong?" challenges change the data but nobody reads them afterwards;
- a typed complaint ("плохо", "useless") is recognised as a kind of request but never summed up;
- there is no way to say "this source is bad";
- the model that really answered (after a quota fallback to a weaker model) and the prompt version are not recorded;
- sources live in a hand-edited file plus a "learned after 3 accepted runs" rule that never learns whether the values were right.

So nobody can tell whether a change made things better or worse, and every lesson needs a human to notice it in a live chat.

**The owner's boundary.**
- **Logic, parsers, rules, dialogue**: observe, group, diagnose, propose. The fix is made by a person (with Claude Code) from the task the system wrote.
- **Sources**: act. The system orders, admits, promotes, demotes and retires sources by itself, inside hard limits it cannot change, and shows everything it did.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every turn leaves a scored outcome (Priority: P1)

The owner wants to know, without reading chats, where users are unhappy. Every turn records what was asked (the kind of request), what the system did, how long it took and what it cost, which failure classes occurred, and a score from 0 to 1.

The score comes from:
- an explicit rating when there is one (1 → 0, 5 → 1);
- otherwise from signals: the user moves on, thanks, accepts a card (success); or rephrases the same request, corrects ("no, I meant…"), complains, presses "wrong?" or "bad source", leaves right after the answer, or the turn failed, timed out or hit a limit (failure).

How the next message relates to the previous answer (continues, rephrase, correction, complaint, thanks, new topic) is read by the understanding step that already runs every turn, at no extra cost.

**Failure classes**:

| Class | How it is recognised |
|---|---|
| Did not understand | the next message is a rephrase or correction of the same request |
| Wrong car | the car was corrected on the card, not found, or the proposed version was refused |
| No data | a value was needed but not found; "no data" shown in the report |
| Wrong data | "wrong?" ended CORRECTED or REMOVED; "bad source" pressed |
| Bad text | sentences were removed by the number guard or the report check; a complaint about the answer |
| Process failure | error, timeout, limit pause, busy |
| Too costly | the turn hit the budget or the user refused the cost |

**Why this priority**: Nothing else in this spec works without a measured outcome per turn. It is also the baseline the owner asked for.

**Independent Test**: Replay golden dialogues with recorded model answers. Inject a rephrase after one answer and a "wrong?" ending CORRECTED after another. The first turn gets "did not understand", the second "wrong data", both with scores below 0.5; an untouched turn followed by "thanks" scores above 0.5.

**Acceptance Scenarios**:

1. **Given** a turn followed by a message the understanding step marks as a rephrase of the same request, **When** the outcome is recorded, **Then** the earlier turn gets the class "did not understand" and its score drops.
2. **Given** a turn rated 5, **When** its score is computed, **Then** the score is 1, whatever the signals say.
3. **Given** a turn that failed with an error, **When** it ends, **Then** its outcome is still recorded with the class "process failure".
4. **Given** any model call, **When** it is recorded, **Then** it names the model that actually answered (after any fallback) and the prompt name and version.

---

### User Story 2 - The user can say "this source is bad" (Priority: P1)

Under each source link shown in a report the user can mark the source as bad for that value. The mark is stored with the car, the attribute, the source and the turn. It counts against that source for that kind of data (US6) and as "wrong data" for the turn (US1).

All feedback (rating with note, "wrong?", "bad source", a typed complaint, a detected rephrase or correction) lands in one feedback record, so it can be grouped and read in one place.

**Why this priority**: The source loop cannot learn without a direct signal from the user, and the issue queue cannot group what is stored in four different shapes.

**Independent Test**: Open a stored report, press "bad source" on one value and "wrong?" on another, rate the report 2 with a note. All three appear in the feedback list with their car, attribute and source; the source's counts on the Sources page change.

**Acceptance Scenarios**:

1. **Given** a report with a source link, **When** the user presses "bad source", **Then** the feedback is stored with car, attribute, source and turn, and the user sees a short acknowledgement.
2. **Given** a "wrong?" challenge, **When** it ends, **Then** its feedback record names the turn and the claim behind the value.
3. **Given** a rating with a note, **When** it is saved, **Then** the note is kept and is readable in the issue queue examples.

---

### User Story 3 - Failures are grouped and diagnosed, and the owner gets a ready task (Priority: P1)

Once a day, and earlier when failures pile up, the system groups failures by component and class:
- dialogue: kind of request × failure class × language;
- parsers: site reader × site (share of pages read falling);
- page relevance: rejection reason, especially rejected pages whose values other sources later confirmed;
- value checks: rejection rule × attribute;
- missing data: kind of data × market;
- models: share of calls answered by a fallback model, per role.

For each group above a threshold the system reads 5–10 examples and writes, in plain language: what goes wrong, how often, a likely cause, a suggested direction for the fix, the likely files, and how to verify the fix. The owner presses "copy for Claude Code" and gets a self-contained task.

The system never changes code, rules, prompts or parsers itself. When the owner marks an issue fixed, the system keeps watching that group; if it grows again, the issue reopens as a regression.

**Why this priority**: This is the owner's main request: complaints must not reach the coder as questions or new specs.

**Independent Test**: Feed synthetic outcomes: three rephrases of "compare" in Russian and five "wrong?" CORRECTED on one attribute from one site. Two issues appear, each with counts, examples, a diagnosis and a copy text that names the component, examples and a verification step. Mark one fixed, feed two more of the same: it reopens as a regression.

**Acceptance Scenarios**:

1. **Given** failures of the same component, class and key above the threshold, **When** the daily analysis runs, **Then** one issue exists for them (not one per failure), with counts, first and last seen, and examples linking to chats.
2. **Given** an issue, **When** the owner presses "copy for Claude Code", **Then** the copied text contains the problem, frequency, examples with quotes, likely cause, likely files, suggested direction and how to verify.
3. **Given** an issue marked fixed, **When** the same group grows again past the threshold, **Then** the issue reopens with the label "regression".
4. **Given** the analysis budget for the day is used up, **When** more groups qualify, **Then** they are listed without a diagnosis and get one the next day.
5. **Given** any analysis run, **When** it ends, **Then** no code, rule, prompt or parser has changed.

---

### User Story 4 - A short admin page: top problems and source quality (Priority: P1)

The admin page in the application is deliberately short. It has two screens and answers two questions: what to fix next, and what the system did with sources. Everything else (trends, rates, health, alerts) lives in Prometheus (US9).

- **Top problems**: the 10 open issues with the highest impact (failing turns and users affected in the last 7 days, weighted by severity of the class). Each line shows: what goes wrong in one sentence, how often, an example chat, and the **proposed fix**, marked as either
  - **code** — likely files and direction, or
  - **configuration** — which configuration file and which key or entry to change, and to what.
  The owner opens an issue to see examples and presses "copy for Claude Code"; marks it acknowledged, fixed (with a commit reference) or won't fix. The system itself applies neither kind of fix.
- **Sources**: per kind of data, the sources with their quality score (mean and lower bound), accuracy, yield and status; and the **recent changes**: promotions, demotions, retirements, re-ordering (a source moved up or down in the order), additions and blocks of the last 30 days, each with its one-sentence reason. The owner can freeze or block a source and revert a change.

**Why this priority**: The owner wants a page that is read in a minute and leads straight to action; detailed monitoring belongs to Prometheus.

**Independent Test**: With seeded outcomes and registry changes, open the admin page with the token: exactly the 10 highest-impact open issues are listed, each with a fix marked code or configuration; the Sources screen lists scores and the last changes; without the token everything is refused.

**Acceptance Scenarios**:

1. **Given** no admin token, **When** anyone opens the admin page or its data, **Then** access is refused.
2. **Given** 15 open issues, **When** the owner opens Top problems, **Then** the 10 with the highest impact are shown in order, each with the proposed fix and its kind (code or configuration).
3. **Given** an issue caused by a configurable threshold or list (for example a plausibility range or a question template), **When** it is diagnosed, **Then** the proposed fix names the configuration file and key and the suggested new value.
4. **Given** a source promoted yesterday and another moved down in the order, **When** the owner opens Sources, **Then** both appear in recent changes with their reasons.

---

### User Story 5 - Spec 009's open fixes enter as issues (Priority: P2)

The flaws found in chats 20b5b7f9 and 8c6a2a58 that spec 009 would have fixed directly are entered as the first issues, each with its chat, examples and a suggested direction:
- the PHEV had no fuel-with-empty-battery consumption, and ownership costs were still compared;
- a junk used price (US-dollar market floor) was accepted;
- the gearbox rule matched "manual" inside "manuales";
- a generation stored as a bare year rejected facelift pages;
- brand-wide service and warranty pages were rejected;
- used-car searches carried no year;
- the first message got "could not map"; "find me a Kia" asked "which model" instead of proposing candidates; engines not sold in the car's year were offered; seats and boot differed between reports of one chat.

**Why this priority**: It proves the path "issue → copy → fix → watch" on known cases and keeps 009's work from being lost.

**Independent Test**: Open the issue queue: every item above is present with its chat and a copy text.

**Acceptance Scenarios**:

1. **Given** the seeded issues, **When** one is fixed and marked fixed, **Then** a replay of its chat no longer produces the failure group, and the issue stays closed.

---

### User Story 6 - Sources are scored per kind of data and ordered by the score (Priority: P1)

Research asks the registry which sources to use for a car, a kind of data and a market, in order. Each pair "source × kind of data × market" (a capability) has:
- **yield**: the share of attempts that gave an accepted value;
- **accuracy**: how often accepted values turned out right, from signals weighted by strength — a reference value or a "wrong?" outcome (strong), a later replacement of the value by a more confident one (medium), agreement with sources of other families (weak); "bad source" counts as wrong;
- a starting level by source type (manufacturer above specification database above publication above forum);
- the cost of an attempt.

The score uses the lower bound of the accuracy estimate, not its mean, so a new source with two lucky values does not outrank a proven one. Old signals fade (half-life 90 days, configurable), so a source that went bad loses trust instead of living on old merit. Mirror sites that copy each other count as one family for agreement.

**Why this priority**: The owner's complaint is data quality. Ordering by measured quality is what makes the registry better than a fixed list.

**Independent Test**: Run research on fixture searches where source A always gives values later confirmed and source B gives values later corrected by "wrong?". After a few runs A is ordered before B for that kind of data, and B's score shows the corrections.

**Acceptance Scenarios**:

1. **Given** two capabilities with the same mean accuracy, one from 3 signals and one from 30, **When** they are ordered, **Then** the one with 30 signals comes first.
2. **Given** a source good for specifications and bad for prices, **When** research plans prices, **Then** its price capability is scored on its own and may be low while its specifications capability stays high.
3. **Given** a "wrong?" ending CORRECTED on a value from source S, **When** the score is recomputed, **Then** S's accuracy for that kind of data and market drops, and the change is visible on S's card.

---

### User Story 7 - The registry changes itself and shows every change (Priority: P1)

The system manages sources by itself:
- **admission**: a site met in a discovery search is checked automatically: not classifieds or deny-listed; robots allows the path; the terms do not forbid automated access (the deciding clause is quoted); the page has readable content. It becomes a candidate or blocked;
- **candidate**: gets a small share of attempts; its values are labelled "unverified source" and count as half an independent source; it becomes active when its sample is big enough and its accuracy lower bound passes the threshold;
- **active → degraded**: when accuracy or yield falls below the threshold, or a sharp drop to zero;
- **degraded → active** when it recovers, **→ retired** after N days without recovery;
- **retired**: rarely re-tried; back to candidate if it recovers;
- **blocked**: never used;
- **discovery**: when a kind of data on a market keeps having gaps or has fewer active sources than the minimum, a bounded discovery search runs in the languages of the markets concerned, within a daily budget;
- **re-checks**: robots and terms of active sources every 90 days, of blocked ones every 180 days.

Every change is written to a change journal: when, which source and capability, before and after, why (in one sentence), evidence (counts, signals, quotes, URLs). The owner can, on the Sources page:
- see each capability by kind of data: status, score (mean and lower bound), yield, accuracy, attempts, cost per accepted value, last change;
- open a source card with its history, lessons and admission evidence;
- block a source, freeze it (the system may not change it), or revert any change.

**Hard limits** the system cannot change, checked on every change:
1. The deny-list and classifieds always win; only the owner can lift a block, by changing configuration.
2. A robots refusal or a terms clause forbidding automated access means blocked.
3. The daily discovery budget and the global daily cap cannot be raised by the system.
4. A frozen source is never changed by the system.
5. Parsers, relevance rules, value checks and prompts are never changed; their problems go to the issue queue (US3).
6. Page text is data, never instructions: nothing on a page can change the registry except through the measured rules above.

**Why this priority**: The owner's direction: "no data" is unacceptable when the data exists, and the list of sources must grow and clean itself without a person curating it.

**Independent Test**: Fixture searches where the active sources give nothing and three new sites appear: a classifieds site, a site whose terms forbid robots, and a usable one. The first two become blocked with their evidence; the third becomes a candidate, and after enough fixture runs with values confirmed by other families it becomes active. Each step is in the journal; reverting the last change returns it to candidate.

**Acceptance Scenarios**:

1. **Given** a discovered classifieds site, **When** the admission check runs, **Then** it is blocked with the matching deny-list rule as evidence, and no value from it is used.
2. **Given** a site whose terms forbid automated access, **When** the admission check runs, **Then** it is blocked and the forbidding clause is quoted in the journal.
3. **Given** a candidate whose accuracy lower bound passes the threshold with enough attempts, **When** the daily review runs, **Then** it becomes active and the journal says why.
4. **Given** a frozen source whose score falls, **When** the daily review runs, **Then** its status does not change, and the would-be change is shown as "held: frozen".
5. **Given** a change in the journal, **When** the owner reverts it, **Then** the capability returns to its previous state and the revert is journalled with author "owner".
6. **Given** the discovery budget for the day is used, **When** another gap qualifies, **Then** no discovery search runs and the gap waits for the next day.
7. **Given** a gap for a kind of data on a market, **When** active sources give nothing, **Then** "no data" is shown only after the active sources and a bounded discovery have failed, and the report names the sources tried.

---

### User Story 8 - The registry starts from what is already known (Priority: P2)

The registry is seeded from:
- the current favourite sources and their readers;
- the 009 survey of 198 sites with robots and terms checked and quoted (candidates, classifieds, terms forbid, blocked, paywall, JS-only, dead);
- the domains learned so far, with their counts.

The old "learned after 3 accepted runs" rule stops; the registry replaces it. Until autonomy is switched on, research uses the seeded registry in the same order as today, so the change of storage alone changes no report.

**Why this priority**: Starting empty would throw away the survey and the lessons of the live chats.

**Independent Test**: After seeding, the Sources page lists every surveyed site with its verdict and evidence; the golden dialogues give the same results as before the registry.

**Acceptance Scenarios**:

1. **Given** the 009 survey, **When** the registry is seeded, **Then** classifieds and terms-forbid entries are blocked with their quoted evidence, and none is ever queried.
2. **Given** the seeded registry with autonomy off, **When** the golden dialogues run, **Then** their results are unchanged.

---

### User Story 9 - Metrics and alerts in Prometheus (Priority: P1)

All detailed metrics and all alerts go to Prometheus; the admin page does not duplicate them. The application exposes a metrics endpoint and ships alert rules for the owner's Prometheus and Alertmanager.

Metrics cover:
- **dialogue**: turns by kind of request, outcome and action; failure classes; the satisfaction index per kind of request, language and persona;
- **complaints**: every kind of feedback (ratings, "wrong?", "bad source", complaints, rephrases, corrections);
- **inaccuracy**: wrong values by kind of data, source and blame (source, parser, extractor, relevance, check, merge); accuracy per kind of data;
- **sources**: capabilities by status per kind of data, active sources per kind of data and market, quality score, accuracy lower bound and yield of each candidate, active or degraded source, registry changes by kind;
- **self-diagnostics**: background loops (last success, failures in a row), model calls, errors and fallback share per role, search and page-fetch failures, site readers reading nothing, research jobs failing;
- **cost**: spend today against the daily cap, background spend against its budgets.

Shipped alert rules:

| Area | Fires when |
|---|---|
| Satisfaction | the 7-day index of a kind of request falls by more than a set margin below its 30-day level, with a minimum number of turns |
| Complaints | complaints, rephrases or corrections in the last 24 h exceed a multiple of their daily average |
| Inaccuracy | accuracy of a kind of data falls below a threshold, or one source collects several wrong values in a day |
| Sources | an active source becomes degraded or blocked, active sources for a kind of data and market fall below the minimum, or a site reader reads nothing in a row |
| No data | the "no data" share of a kind of data rises above its 30-day level by a margin |
| Models | the fallback share of a role exceeds a threshold, or a provider is unavailable for several minutes |
| Budget | spend today passes 80% of the daily cap, or a background budget is used up |
| Self | a background loop has not completed on time, or fails twice in a row |
| Issues | an issue reopens as a regression |

**Why this priority**: The owner wants alerts and detailed monitoring in Prometheus, and a short admin page in the application.

**Independent Test**: With seeded data, scrape the endpoint: the values match the seeded outcomes, feedback and registry. Load the shipped rules into Prometheus; a seeded complaint spike and a degraded source make the matching rules fire, and they clear when the data returns to normal.

**Acceptance Scenarios**:

1. **Given** Prometheus scrapes the endpoint, **When** it reads it, **Then** it gets the metrics listed above, and the request is refused without the metrics token outside the local network.
2. **Given** a background loop that stopped, **When** two of its intervals pass, **Then** its last-success metric is stale and the shipped rule fires.
3. **Given** the shipped rules, **When** they are validated by the project's checks, **Then** they parse, and every metric they use is exported.

---

### User Story 10 - The user sees what was understood and corrects it cheaply (Priority: P1)

Source: UI audit of 2026-11-05 (`docs/ux-audit-2026-11-05.md`, findings F1–F6 and its quick wins). The owner's first complaint, "the assistant loses the dialogue and picks the wrong version", is partly a UI problem: what the system understood disappears or is hidden, and correcting it costs a free-text turn that the model must reinterpret.

- **Agreed version stays visible**: after the user confirms the cars, a compact read-only "Agreed" entry stays in the chat with the final values and their basis. The full version line (engine · gearbox · trim · year) is shown in the case summary, in the case panel and under the verdict headline.
- **Cheap structured correction**: each car in the case panel and in the report's spec-table header has a "Change" action offering the same choices as the intake card (generation, engine, gearbox, trim) plus "Not this car" and "Remove"; the change is applied by code, not reinterpreted by the model. Intake-card fields without choices get an inline edit.
- **Case panel speaks up**: on wide screens it opens on the first case file; a badge on "Your case" shows unseen changes; each set of changes leaves a one-line "Noted: … — Edit" entry in the chat.
- **Answer starts at the top**: a new answer scrolls to its start; a slim "Based on: …" strip with an Edit link sits above the verdict.
- **Data quality is legible**: provenance and basis badges are readable in both themes; confidence is shown as text, not only colour; reasons are visible on tap, not only on hover; a one-line legend sits above the spec table.
- **"wrong?" says why and answers in place**: it offers "wrong for this version", "outdated", "wrong value" and a note; the result is shown in the table cell (old value struck, new value, "re-checked"), using the row's label.
- **Interface language**: the interface is English (as in the product vision); replies stay in the user's language. Mixed-language screens disappear.
- **Quick wins of the audit**: composer keeps text when sending fails; connection state visible on phones; accessibility fixes (labels, roles, Escape); rating with scale anchors and reason chips on low scores; one "find the missing data" action per report; legend and elapsed time in the progress grid.

**Why this priority**: it attacks the main complaint directly and cheaply, and the outcome measurements of US1 will show whether "wrong car" and "did not understand" fall.

**Independent Test**: In the browser with the chat store fed the stored messages of a chat: after confirming, the "Agreed" entry stays; the version line is visible in three places; "Change" on a car switches the version without a free-text turn (the case file changes, the model is not called for interpretation); badges pass contrast AA in the light theme; the accessibility scan has no critical or serious issues.

**Acceptance Scenarios**:

1. **Given** the user confirms the proposed cars, **When** the card closes, **Then** an "Agreed" entry with the versions remains in the chat after a reload.
2. **Given** a report for the wrong version, **When** the user presses "Change" on that car and picks another engine, **Then** the case file changes by code, the affected results are recomputed or re-researched, and the interpreter is not called for that edit.
3. **Given** a long report arrives, **When** it renders, **Then** the view is at the start of the answer and "Based on: …" is above the verdict.
4. **Given** the light theme, **When** provenance, basis and confidence are shown, **Then** each has contrast ≥ 4.5:1 and a text form.
5. **Given** a "wrong?" with reason "wrong for this version", **When** the re-check corrects the value, **Then** the cell shows the corrected value and the reason is stored in the feedback (US2).

---

### Edge Cases

- **Alert storm.** Many sources degrade at once because the search provider is down: the provider alert names the common cause; grouping and rate limits are Alertmanager's job.
- **Too few signals.** One user produces few truth signals: transitions use the accuracy lower bound and minimum sample sizes, so a source does not flip status on one or two values.
- **Copying sites.** Mirror sites agree with each other: agreement counts by family, so copies do not raise each other's accuracy.
- **Our own fault, not the source's.** A value was wrong because our parser or extractor misread a correct page: when the page quote holds the right number, the error is attributed to the parser/extractor and goes to the issue queue, and the source's accuracy is not lowered.
- **Outcome of a turn the user never answers.** The last turn of a chat has no following message: its score comes from the rating and its own signals only.
- **Fallback storms.** A provider quota runs out mid-day and every call goes to a weaker model: the fallback share shows in Prometheus (and its alert fires), and a model issue is created if it passes the threshold.
- **Diagnosis prompt injection.** Examples in an issue contain page or user text: the analysis treats it as data; the analysis has no tools that change anything.
- **Owner reverts a change the system then repeats.** A reverted change is not repeated for the same capability until new evidence arrives; the owner can also forbid similar changes by freezing the source.
- **A site's terms change.** A re-check finds a new forbidding clause on an active source: it becomes blocked at once with the clause quoted.

## Requirements *(mandatory)*

### Functional Requirements

**Observation**

- **FR-001**: Every turn MUST leave an outcome record: kind of request, action taken, path through the steps, duration, cost, failure classes, signals and a score from 0 to 1, including turns that failed, timed out or were cancelled.
- **FR-002**: The understanding step MUST classify how each message relates to the previous answer (continues, rephrase, correction, complaint, thanks, new topic) in the same call it already makes; the result updates the previous turn's outcome.
- **FR-003**: The score MUST equal the explicit rating mapped to 0–1 when there is one; otherwise it MUST be computed from configured signal weights.
- **FR-004**: Every model call record MUST include the model that actually answered and the prompt name and version.
- **FR-005**: The user MUST be able to mark a source as bad for a shown value.
- **FR-006**: All feedback (rating with note, "wrong?", "bad source", typed complaint, detected rephrase or correction) MUST be stored in one feedback record naming the chat, turn and, where they apply, the car, attribute, source and claim. A "wrong?" record MUST name its turn and claim.

**Diagnosis (no self-change)**

- **FR-007**: The system MUST group failures by component, class and key (as listed in US3) once a day and earlier when a configured number of new failures arrives, without slowing any turn.
- **FR-008**: Each group above a configured threshold MUST be one issue, deduplicated across runs, with counts, first and last seen, examples linking to chats, pages and claims, and a status (open, acknowledged, fixed, won't fix, regression).
- **FR-009**: For each qualifying issue, within a daily analysis budget, the system MUST write a diagnosis, likely cause, a proposed fix marked "code" (likely files, direction) or "configuration" (file, key or entry, suggested value — chosen only from a declared list of configuration levers) and a verification step, and MUST offer the whole as a copyable task for Claude Code.
- **FR-010**: The system MUST NOT change code, rules, prompts, parsers or their configuration as a result of diagnosis.
- **FR-011**: An issue marked fixed MUST reopen as "regression" when its group passes the threshold again after the fix date.
- **FR-012**: The open flaws of spec 009 (US5) MUST be entered as issues with their chats and suggested directions.

**Source registry**

- **FR-013**: The system MUST keep a source registry in its database: sources (site, type, markets, languages, family, robots and terms status with evidence and check date) and capabilities (source × kind of data × market) with status, score, counts, accuracy signals and a frozen flag. Kinds of data: new price, used price, specifications, plug-in and electric consumption (including fuel with an empty battery), maintenance, warranty, residual value, reliability, measured performance, used-car issues.
- **FR-014**: The registry MUST be seeded from the favourite sources, the 009 survey and the learned domains, and MUST replace the "learned sources" rule.
- **FR-015**: Research MUST take the order of sources for a car, kind of data and market from the registry, and MUST record every attempt (accepted, rejected with reason, robots refusal, junk) against the capability used.
- **FR-016**: Each capability's score MUST combine yield, the lower bound of accuracy from weighted, decaying truth signals, a prior by source type and the cost of an attempt; agreement MUST count by source family.
- **FR-017**: When a value is shown wrong and its page quote holds the correct value, the error MUST be attributed to the parser or extractor (an issue), not to the source.
- **FR-018**: The system MUST move capabilities through discovered, candidate, active, degraded, retired and blocked by configured thresholds based on the score's lower bound and minimum sample sizes, without review.
- **FR-019**: The system MUST run an automatic admission check on every discovered site (deny-list and classifieds, robots per path, terms with the deciding clause quoted, readable content) and MUST re-check active sources every 90 days and blocked ones every 180 days.
- **FR-020**: The system MUST run a bounded discovery search for a kind of data on a market when gaps persist or active sources fall below a minimum, within a daily discovery budget, in the languages of the markets concerned. Prices only from European markets; other kinds may come from any market where the car is sold.
- **FR-021**: Values from a candidate MUST be labelled "unverified source" and count at most as half an independent source.
- **FR-022**: "No data" MUST be shown only after the active sources and a bounded discovery have failed; the report MUST name the sources tried.
- **FR-023**: Every registry change MUST be journalled with time, author (system or owner), capability, before and after, a one-sentence reason and evidence. Every change MUST be revertible by the owner; a reverted change MUST NOT be repeated for that capability without new evidence.
- **FR-024**: The hard limits of US7 MUST be checked by code on every change and MUST NOT be changeable by the system.

**Admin page**

- **FR-025**: The admin page and its data MUST require the admin token.
- **FR-026**: The Top problems screen MUST list the 10 open or regression issues with the highest impact in the last 7 days (failing turns, chats affected, class severity), each with a one-sentence summary, frequency, an example chat and a proposed fix marked "code" (likely files, direction) or "configuration" (file, key or entry, suggested value).
- **FR-027**: An issue MUST open to its examples, diagnosis and the "copy for Claude Code" text; the owner MUST be able to set the status and a commit reference.
- **FR-028**: The Sources screen MUST list, per kind of data, each source's status, quality score (mean and lower bound), accuracy, yield and attempts, and the registry changes of the last 30 days (promotions, demotions, retirements, re-ordering, additions, blocks) with their reasons; the owner MUST be able to freeze or block a source and revert a change.
- **FR-029**: The admin page MUST NOT duplicate the detailed metrics or alerts of Prometheus.

**Metrics and alerts (Prometheus)**

- **FR-030**: The system MUST expose a metrics endpoint in the Prometheus text format with the metrics of US9, protected by a metrics token or restricted to the local network, with bounded label sets (per-source series only for candidate, active and degraded sources).
- **FR-031**: Scraping MUST NOT run database queries; slow values MUST be refreshed in the background at least every minute.
- **FR-032**: The project MUST ship Prometheus alert rules for every condition of US9, with configurable thresholds, and a check MUST validate that they parse and use only exported metrics.
- **FR-033**: Every background loop MUST export its last success time and failures in a row, so that a silent stop is caught by Prometheus.
- **FR-034**: The project MUST ship a Prometheus scrape configuration and an optional local monitoring setup (Prometheus and Alertmanager); the application MUST work without them.

**Interface (US10)**

- **FR-035**: After a confirmation, the chat MUST keep a persisted read-only "Agreed" entry with each car's final version and basis.
- **FR-036**: The full version line (engine, gearbox, trim, year) MUST appear in the case summary, the case panel and under the verdict headline.
- **FR-037**: The user MUST be able to change a car's generation, engine, gearbox or trim, mark it "not this car" or remove it, from the case panel and the report, as a structured edit applied by code without an interpretation call.
- **FR-038**: The case panel MUST signal unseen changes, open automatically on wide screens on the first case file, and each change set MUST leave a one-line note in the chat with an edit link.
- **FR-039**: A new answer MUST scroll to its start, with "Based on: …" above the verdict.
- **FR-040**: Provenance, basis and confidence MUST be readable in both themes (contrast ≥ 4.5:1), have a text form, and their reasons MUST be reachable by tap and keyboard; a legend MUST precede the spec table.
- **FR-041**: "wrong?" MUST let the user choose a reason, and its result MUST be shown in the challenged cell with the row's label.
- **FR-042**: The interface text MUST be English in every screen; replies remain in the user's language.
- **FR-043**: The audit's quick wins listed in US10 MUST be implemented, and the accessibility scan MUST report no critical or serious issues.

### Key Entities

- **Turn outcome**: one per turn; kind of request, action, path, duration, cost, relation of the next message, failure classes, signals, score.
- **Feedback**: one per user signal; kind, chat, turn, message, car, attribute, source, claim, text, outcome.
- **Issue**: a group of failures; component, class, key, counts, impact, first/last seen, examples, diagnosis, proposed fix, status, fix reference.
- **Source**: a site; type, markets, languages, family, robots and terms status with evidence and dates.
- **Capability**: source × kind of data × market; status, score, yield and accuracy evidence, attempts, cost, frozen flag.
- **Truth signal**: evidence that a shown value was right or wrong; kind (reference, challenge, bad source, later replacement, agreement), weight, date, value and capability concerned, blame (source or our processing).
- **Registry change**: a journal entry; time, author, capability, before, after, reason, evidence, reverted flag.
- **Proposed fix** (part of an issue): kind (code or configuration), files or configuration key, direction or suggested value, verification.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of turns, including failed ones, have an outcome with a score; 100% of model calls name the model that answered and the prompt version.
- **SC-002**: A baseline of the satisfaction index per kind of request and of data accuracy exists within one week of release.
- **SC-003**: The owner sees what to fix next and what the system did with sources from the admin page in under one minute.
- **SC-004**: Every live-chat complaint the owner would have turned into a question or a spec is visible as an issue with a copyable task, with no manual write-up; zero new specs are needed for single-chat fixes.
- **SC-005**: A fixed issue whose failure returns is reopened as a regression within one analysis cycle.
- **SC-006**: Zero code, rule, prompt or parser changes are made by the system; zero values are used from blocked, classifieds or terms-forbid sites.
- **SC-007**: Every registry change is in the journal with a reason and evidence, and any one can be reverted in one action.
- **SC-008**: After one month, the share of "no data" for kinds of data with an existing open source falls, and the accuracy of shown values does not fall, compared with the baseline.
- **SC-009**: Background analysis and discovery stay within their daily budgets on every day.
- **SC-010**: A degraded source, a complaint wave or a stopped background loop makes a shipped Prometheus rule fire within 10 minutes.
- **SC-012**: After US10, the share of turns with class "wrong car" or "did not understand" falls compared with the baseline of US1.
- **SC-011**: Every proposed fix in Top problems is marked code or configuration, and every configuration fix names an existing file and key.

## Assumptions

- One owner and few users: decisions rely on lower bounds, minimum samples and slow transitions; no live A/B or canary.
- Background work runs inside the existing single application process on a schedule, like the existing retention task; no new service.
- The existing admin token protects the admin page; no user accounts are added. A separate metrics token protects the Prometheus endpoint.
- Alerts and detailed metrics live only in Prometheus; routing (chat bot, e-mail) is configured by the owner in Alertmanager. Prometheus and Alertmanager are optional for running the application.
- Signal weights, thresholds, half-life, budgets and minimum samples are configuration with sensible defaults (strong signal 1, later replacement 0.7, agreement 0.3; half-life 90 days); the system cannot change them.
- Dataset sources (EEA CO2/OBFCM, RDW, DVSA MOT, fueleconomy.gov), JS rendering, automatic parser repair and a weekly model-judge calibration of implicit signals are out of scope and may follow in later specs.
- The current specs 001–009 are summarised in one baseline document of what the system does today; they remain as history.
