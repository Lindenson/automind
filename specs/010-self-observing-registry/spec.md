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

### User Story 4 - The owner sees the state of the system in a minute (Priority: P1)

An admin page, behind the existing admin token, answers three questions: is it better or worse, what broke, what did the system change by itself.

- **Overview**: satisfaction index per kind of request, with 7- and 30-day trends and cuts by language and persona; share of "no data"; data accuracy from signals; share of model calls served by a fallback model; spend today and this month; firing alerts.
- **Issues**: the issue queue with diagnosis, examples, status and the copy button; the owner can mark an issue acknowledged, fixed (with a commit reference) or won't fix.
- **Sources**, **Source changes**: see US7 and US9.
- **Inaccuracies**, **Complaints**, **Self-diagnostics**, **Alerts**: see US9.

Every number leads to its reason: a drop in accuracy leads to the sources, from there to the wrong values, from there to the page and the quote.

**Why this priority**: Without the page, the measurements stay in tables nobody opens.

**Independent Test**: With seeded outcomes, open the admin page with the token: the overview shows the index per kind of request with trends; without the token the page and its data are refused.

**Acceptance Scenarios**:

1. **Given** no admin token, **When** anyone opens the admin page or its data, **Then** access is refused.
2. **Given** a drop of the index in one kind of request, **When** the owner opens the overview, **Then** that kind is listed among the top declines with a link to its issues.

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

### User Story 9 - Metrics and alerts: in the admin page and for Prometheus (Priority: P1)

The owner does not want to open the admin page to learn that something broke. The system keeps metrics over time and raises alerts, in two places:
- **in the admin page**: an Alerts tab and a badge on every tab while an alert is firing; charts over time for the satisfaction index, accuracy, complaints, sources and the system's own health;
- **for Prometheus**: a metrics endpoint scraped by Prometheus, plus ready alert rules with the same conditions and thresholds as the in-app alerts, so the owner's own monitoring can page them.

The admin page gets dedicated views:
- **Sources**: per capability, score, accuracy (mean and lower bound), yield and cost per value over time (daily points, 30 and 90 days); counts by status per kind of data over time; recent status changes.
- **Inaccuracies**: every value shown wrong (challenge CORRECTED/REMOVED, bad source, later replacement): car, attribute, shown value, corrected value, source, page quote, who was blamed (source, parser, extractor, relevance, check, merge), with filters by kind of data, source and blame; trend of wrong values per day.
- **Complaints**: every feedback item (ratings with notes, "wrong?", "bad source", typed complaints, detected rephrases and corrections) with its chat, turn, kind of request and language; trend per day by kind.
- **Self-diagnostics**: health of the system itself — the background loops (last successful run, last error, duration), model provider errors and fallback share per role, search provider failures, page-fetch refusals and errors, site readers with a falling share of pages read, research jobs failing, spend against the daily cap and the background budgets.

**Alert conditions** (configurable thresholds; each has a severity: warning or critical):

| Area | Fires when |
|---|---|
| Satisfaction | the 7-day index of a kind of request falls by more than a set margin below its 30-day level, with a minimum number of turns |
| Complaints | complaints, rephrases or corrections in the last 24 h exceed a multiple of their daily average |
| Inaccuracy | wrong values in the last 7 days exceed a share of values shown, or one source collects several wrong values in a day |
| Sources | an active source becomes degraded or blocked (terms changed, robots), active sources for a kind of data and market fall below the minimum, or a site reader reads zero values in a row |
| No data | the "no data" share of a kind of data rises above its 30-day level by a margin |
| Models | the fallback share of a role exceeds a threshold, or a provider is unavailable for several minutes |
| Budget | spend today passes 80% of the daily cap, or a background budget is used up |
| Self | a background loop has not completed on time, or failed twice in a row |
| Issues | an issue reopens as a regression |

An alert is raised once, stays firing while the condition holds, and resolves by itself when it clears. The owner can acknowledge it or mute it for a period. Each alert links to its reason (the chart, the source card, the issue). Optionally an alert is also sent to a configured webhook (for example a chat bot).

**Why this priority**: The owner asked for metrics and alerts as part of the product and its admin interface, with an export for Prometheus. Without alerts, a degraded source or a wave of complaints is found only by chance.

**Independent Test**: With seeded data, push the complaint rate of one day above its threshold and degrade one active source. Two alerts fire in the admin page with links, the metrics endpoint shows the matching values, and the shipped Prometheus rule for each fires on the same data; when the data returns to normal, both alerts resolve.

**Acceptance Scenarios**:

1. **Given** a condition above its threshold, **When** the evaluation runs, **Then** exactly one alert is firing for it (not one per evaluation), with severity, value, threshold, start time and link.
2. **Given** a firing alert whose condition clears, **When** the evaluation runs, **Then** the alert is resolved with an end time and stays in the history.
3. **Given** a muted alert, **When** its condition fires again inside the mute period, **Then** it is recorded but not shown as a badge or sent to the webhook.
4. **Given** Prometheus scrapes the metrics endpoint, **When** it reads it, **Then** it gets the satisfaction index per kind of request, accuracy, complaints, source counts by status, loop health, fallback share and spend, and the request is refused without the metrics token outside the local network.
5. **Given** the shipped Prometheus alert rules, **When** they are checked against the in-app alert configuration, **Then** each in-app alert has a rule with the same condition and threshold.
6. **Given** the Sources view, **When** the owner opens a source, **Then** the score, accuracy and yield of each of its capabilities are shown as daily series for 30 and 90 days.

---

### Edge Cases

- **Alert storm.** Many sources degrade at once (for example the search provider is down): one alert per condition and source, and the self-diagnostics alert for the provider points to the common cause; the webhook sends at most a configured number of messages per hour.
- **Too few signals.** One user produces few truth signals: transitions use the accuracy lower bound and minimum sample sizes, so a source does not flip status on one or two values.
- **Copying sites.** Mirror sites agree with each other: agreement counts by family, so copies do not raise each other's accuracy.
- **Our own fault, not the source's.** A value was wrong because our parser or extractor misread a correct page: when the page quote holds the right number, the error is attributed to the parser/extractor and goes to the issue queue, and the source's accuracy is not lowered.
- **Outcome of a turn the user never answers.** The last turn of a chat has no following message: its score comes from the rating and its own signals only.
- **Fallback storms.** A provider quota runs out mid-day and every call goes to a weaker model: the fallback share shows on the overview, and a model issue is created if it passes the threshold.
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
- **FR-009**: For each qualifying issue, within a daily analysis budget, the system MUST write a diagnosis, likely cause, suggested direction, likely files and a verification step, and MUST offer the whole as a copyable task for Claude Code.
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
- **FR-026**: The overview MUST show the satisfaction index per kind of request (7- and 30-day trends, by language and persona), share of "no data", data accuracy from signals, share of fallback-model calls, spend today and this month, and the top declines.
- **FR-027**: The issues view MUST list issues with diagnosis, examples, status and the copy action; the owner MUST be able to set the status and a commit reference.
- **FR-028**: The sources view MUST list capabilities per kind of data (status, score mean and lower bound, yield, accuracy, attempts, cost per accepted value, last change), open a source card with history and evidence, and let the owner block, freeze or revert.
- **FR-029**: The change journal MUST list every registry change with its reason and evidence, newest first.

**Metrics and alerts**

- **FR-030**: The system MUST keep daily series of: satisfaction index per kind of request, language and persona; failure-class shares; feedback counts per kind; wrong values and accuracy per kind of data and source; "no data" share per kind of data and market; per-capability score, accuracy (mean and lower bound), yield and cost; capability counts by status per kind of data; model calls, fallback share and errors per role; search and fetch failures; spend. Series MUST cover at least 180 days.
- **FR-031**: The admin page MUST include views for Sources (with daily series per capability), Inaccuracies, Complaints and Self-diagnostics as described in US9, each linking down to the chat, value, page or source behind a number.
- **FR-032**: The system MUST evaluate the alert conditions of US9 at least every 5 minutes in the background, with configurable thresholds and severities; an alert MUST have one firing instance per condition and subject, resolve automatically, and keep a history.
- **FR-033**: The owner MUST be able to acknowledge an alert and mute a condition (optionally for one subject) for a period. Firing alerts MUST be visible as a badge on every admin view.
- **FR-034**: When a webhook is configured, firing and resolved alerts (not muted) MUST be sent to it, rate-limited per hour.
- **FR-035**: The system MUST expose a metrics endpoint in the Prometheus text format with the metrics of FR-030 (current values and counters), protected by a metrics token or restricted to the local network, with bounded label sets (per-source series only for candidate, active and degraded sources).
- **FR-036**: The project MUST ship Prometheus alert rules equivalent to the in-app alert conditions, generated from the same configuration, and a check MUST fail when they drift apart.
- **FR-037**: The self-diagnostics alerts MUST fire when a background loop misses its schedule or fails twice in a row, so a silent stop of observation is itself visible.

### Key Entities

- **Turn outcome**: one per turn; kind of request, action, path, duration, cost, relation of the next message, failure classes, signals, score.
- **Feedback**: one per user signal; kind, chat, turn, message, car, attribute, source, claim, text, outcome.
- **Issue**: a group of failures; component, class, key, counts, first/last seen, examples, diagnosis, suggested direction, likely files, verification, status, fix reference.
- **Source**: a site; type, markets, languages, family, robots and terms status with evidence and dates.
- **Capability**: source × kind of data × market; status, score, yield and accuracy evidence, attempts, cost, frozen flag.
- **Truth signal**: evidence that a shown value was right or wrong; kind (reference, challenge, bad source, later replacement, agreement), weight, date, value and capability concerned, blame (source or our processing).
- **Registry change**: a journal entry; time, author, capability, before, after, reason, evidence, reverted flag.
- **Daily series point**: a metric, its labels (kind of request, kind of data, source, role…), a day and a value.
- **Alert rule**: a named condition with threshold, window, severity, subject type and link target; from configuration.
- **Alert**: one firing instance of a rule for a subject; started, resolved, value, threshold, acknowledged, muted until, notifications sent.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of turns, including failed ones, have an outcome with a score; 100% of model calls name the model that answered and the prompt version.
- **SC-002**: A baseline of the satisfaction index per kind of request and of data accuracy exists within one week of release.
- **SC-003**: The owner can answer "what got worse, what broke, what changed by itself" from the admin page in under one minute.
- **SC-004**: Every live-chat complaint the owner would have turned into a question or a spec is visible as an issue with a copyable task, with no manual write-up; zero new specs are needed for single-chat fixes.
- **SC-005**: A fixed issue whose failure returns is reopened as a regression within one analysis cycle.
- **SC-006**: Zero code, rule, prompt or parser changes are made by the system; zero values are used from blocked, classifieds or terms-forbid sites.
- **SC-007**: Every registry change is in the journal with a reason and evidence, and any one can be reverted in one action.
- **SC-008**: After one month, the share of "no data" for kinds of data with an existing open source falls, and the accuracy of shown values does not fall, compared with the baseline.
- **SC-009**: Background analysis and discovery stay within their daily budgets on every day.
- **SC-010**: A degraded source, a complaint wave or a stopped background loop raises an alert within 10 minutes, visible in the admin page and through Prometheus.
- **SC-011**: Every in-app alert condition has an equivalent shipped Prometheus rule (zero drift, checked automatically).
- **SC-012**: Every number on the Sources, Inaccuracies and Complaints views leads in at most three clicks to the chat, value, page quote or source behind it.

## Assumptions

- One owner and few users: decisions rely on lower bounds, minimum samples and slow transitions; no live A/B or canary.
- Background work runs inside the existing single application process on a schedule, like the existing retention task; no new service.
- The existing admin token protects the admin page; no user accounts are added. A separate metrics token protects the Prometheus endpoint.
- Alerts are delivered in the admin page, through Prometheus (the owner's Alertmanager routes them), and optionally to one generic webhook; e-mail and SMS are not built in.
- Prometheus and Alertmanager themselves are optional: the project ships a scrape and rules configuration and an optional monitoring profile for the local deployment, but works without them.
- Signal weights, thresholds, half-life, budgets and minimum samples are configuration with sensible defaults (strong signal 1, later replacement 0.7, agreement 0.3; half-life 90 days); the system cannot change them.
- Dataset sources (EEA CO2/OBFCM, RDW, DVSA MOT, fueleconomy.gov), JS rendering, automatic parser repair and a weekly model-judge calibration of implicit signals are out of scope and may follow in later specs.
- The current specs 001–009 are summarised in one baseline document of what the system does today; they remain as history.
