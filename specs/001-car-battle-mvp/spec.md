# Feature Specification: Ultimate Car Battle (AutoMind MVP)

**Feature Branch**: `001-car-battle-mvp`

**Created**: 2026-11-01

**Status**: Superseded by `specs/002-conversational-mvp` (2026-11-01)

**Input**: User description: "AutoMind MVP 'Ultimate Car Battle' — technical vehicle research &
comparison for automotive experts and enthusiasts. Compare 2–4 vehicles (ICE, EV, HEV/PHEV),
resolve exact variants, approve a research plan, research technical specifications and known
technical issues in parallel with source attribution, verify and surface conflicts, compute
deterministic metrics, run a drag race simulation v0.1, produce a structured report, stateful and
resumable sessions with live progress and history, simple web demo UI. Market prices,
multi-user, and advanced physics are out of scope." (full description: see `sec.md` and
conversation of 2026-11-01)

## Clarifications

### Session 2026-11-01

- Q: When a variant was already researched earlier, should new research reuse stored data? → A: Build a local catalog of resolved variants and evidence-backed specs; the plan offers reuse if data is under 90 days old, or fresh research; the user decides per vehicle.
- Q: How are conflicts resolved when no manufacturer source exists? → A: Source authority order — manufacturer > instrumented test (performance figures) > established automotive publication > encyclopedia/spec database; among top-ranked disagreeing sources, majority if ≥2 independent sources agree, otherwise unresolved.
- Q: How is confidence expressed per value and per vehicle? → A: Three rule-based levels — High (manufacturer source, or ≥2 independent agreeing sources), Medium (single non-manufacturer source), Low (unresolved conflict or weak/indirect evidence); vehicle level = share of Tier 1 values rated High. (Initially answered as a 0–100 score; changed by the user to three levels.)
- Q: Can the user adjust drag race settings? → A: Yes, a small set — road surface (dry/wet), extra load (kg), ambient temperature/altitude, and an optional "predict the winner" step; each run is stored with its settings and model version. Vehicle specs are not editable (reserved for What-If Garage).
- Q: How can finished reports be exported? → A: No export in the MVP; reports are viewed in the app only.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Evidence-backed technical comparison (Priority: P1)

An automotive enthusiast wants to compare, for example, a Volkswagen Golf GTI (Mk8), a Hyundai
i30 N, and a Tesla Model 3 Performance. They enter the vehicles (free text, optionally with model
year), and the system proposes the exact variant it identified for each one (generation, trim,
powertrain, model year, market). The user reviews this research plan and approves it. The system
then researches each vehicle's technical specifications and presents a side-by-side comparison
in which every value shows where it came from and what kind of value it is (manufacturer claim,
measured, sourced fact, derived, etc.). Values that could not be found are clearly shown as
unavailable. Derived metrics such as power-to-weight are calculated and the vehicles are ranked
per metric.

**Why this priority**: This is the core value of the product — trustworthy, attributable,
variant-exact technical data side by side. Without it nothing else (simulation, issues) has a
reliable foundation.

**Independent Test**: Create a research with three well-known vehicles, approve the plan, and
verify that the resulting comparison shows Tier 1 specifications per vehicle, each with a source
and provenance label, plus derived metrics and rankings, with no unlabeled or unsourced values.

**Acceptance Scenarios**:

1. **Given** the user enters 3 vehicle descriptions, **When** they submit the research, **Then**
   the system shows a plan listing the resolved exact variant for each vehicle, the research
   categories, the planned tasks, the expected task count, and any ambiguities — and does not start
   research until the user approves.
2. **Given** a plan is shown, **When** the user edits a vehicle variant choice, **Then** no
   research is started for the old plan and a corrected plan is shown for approval; **When** the
   user rejects the plan, **Then** the research is cancelled without running any research
   tasks.
3. **Given** the plan is approved, **When** research completes, **Then** each vehicle shows Tier 1
   specifications (see FR-010) where available, each value with unit, source name, source link,
   source type, retrieval date, and provenance label.
4. **Given** a specification cannot be found in any source, **When** the comparison is shown,
   **Then** the value is displayed as "unavailable" and is not estimated or copied from another
   variant.
5. **Given** specifications were collected, **When** the comparison is shown, **Then** derived
   metrics (power-to-weight, torque-to-weight, weight-to-power, specific output where applicable)
   are shown with the "derived" label and traceable inputs, and vehicles are ranked per metric.
6. **Given** the user enters 1 vehicle or 5 vehicles, **When** they try to submit, **Then** the
   system explains that 2–4 vehicles are required.

---

### User Story 2 - Drag race simulation (Priority: P2)

After a comparison is complete, the user wants to see which car would win a straight-line race.
The system simulates a standing-start acceleration run for all vehicles and shows speed, distance,
and acceleration over time as charts, plus estimated 0–100 km/h, 0–200 km/h (when the vehicle can
reach it), 400 m time, and speed at the 400 m line. Results are clearly labeled as simulated
estimates. Where an independently measured result exists (e.g. an instrumented magazine test), it
is shown next to the simulated value, alongside the manufacturer's claimed figure.

**Why this priority**: The simulation is the most engaging part of the experience and the main
"engineering" differentiator, but it depends on the data from Story 1.

**Independent Test**: Provide a fixed set of vehicle specifications (one combustion, one electric,
one hybrid) and run the simulation twice; verify identical results both times, presence of all
result metrics, the "simulated estimate" label, and display of measured/claimed values for
comparison.

**Acceptance Scenarios**:

1. **Given** a completed comparison with sufficient data (at minimum power and weight),
   **When** the user runs the drag race, **Then** the system shows time-series charts of speed,
   distance, and acceleration and a results table with 0–100 km/h, 0–200 km/h (or "not reached"),
   400 m time, and 400 m speed, plus a finishing order.
2. **Given** an electric vehicle, **When** it is simulated, **Then** the EV powertrain behavior
   profile is used (full torque from standstill up to base speed, then power-limited), without gear
   shifts.
3. **Given** a hybrid vehicle, **When** it is simulated, **Then** the combined system output is
   used and the result notes this simplification.
4. **Given** a simulation input (e.g. drag coefficient) is not available from sources, **When** the
   simulation runs, **Then** a documented default is used, labeled "assumption", and listed in the
   simulation results; it is never shown as a vehicle fact.
5. **Given** a vehicle lacks power or weight, **When** the simulation is requested, **Then** that
   vehicle is excluded from the race with an explanation, and the remaining vehicles still race.
6. **Given** the same inputs and the same simulation model version, **When** the simulation is run
   again, **Then** the results are identical; the results show the model version used.
7. **Given** a completed comparison, **When** the user sets the surface to wet, adds 200 kg of
   load, optionally records a predicted finishing order, and runs the race, **Then** the results
   reflect the changed settings, show the settings used next to the results, compare the
   prediction with the simulated order, and the run is saved alongside earlier runs.

---

### User Story 3 - Conflict and data-quality transparency (Priority: P3)

An automotive researcher needs to know when sources disagree. When two sources report different
values for the same variant (e.g. 245 hp vs. 250 hp), or a source turns out to describe a
different variant or model year, the system detects it, attempts a bounded follow-up search to
resolve it, and — if it remains unresolved — shows all competing values with their sources rather
than silently choosing one. Each vehicle and value carries a confidence level (High / Medium / Low) based on source
type and agreement.

**Why this priority**: Verifiability is what distinguishes this product from a chatbot answer and
what experts need to trust results; it builds on Story 1's data.

**Independent Test**: Run a research using controlled test sources that contain a deliberate
conflicting value, a mismatched-variant source, and a value with an inconsistent unit; verify all
three are detected, follow-up research is attempted within the configured limit, and unresolved
conflicts are visible in the report.

**Acceptance Scenarios**:

1. **Given** two sources report different values for the same attribute of the same variant
   beyond a tolerance, **When** verification runs, **Then** a conflict is recorded showing each
   value, its source, and its source type.
2. **Given** a conflict exists, **When** a targeted follow-up search finds a value from a
   higher-ranked source type (per FR-017), **Then** that value is selected, the rule used is
   recorded, and the alternatives remain visible.
3. **Given** two encyclopedia/database sources disagree and a third independent one agrees with
   one of them, with no higher-ranked source, **When** verification runs, **Then** the majority
   value is selected with rule "majority of same-rank sources" recorded.
4. **Given** the follow-up limit is reached without resolution, **When** the report is produced,
   **Then** the conflict is listed as unresolved and the comparison shows the competing values
   rather than a single chosen one.
5. **Given** a source describes a different variant, generation, or model year than the resolved
   one, **When** verification runs, **Then** its values are rejected for that vehicle and the
   mismatch is recorded.
6. **Given** a value is stated without a supporting source excerpt, **When** verification runs,
   **Then** it is flagged as unsupported and not shown as a fact.

---

### User Story 4 - Live progress, interruption, resume, and cancel (Priority: P4)

While research runs (it may take several minutes), the user watches live progress: overall phase
(planning, awaiting approval, researching, verifying, analyzing, completed) and the status of each
individual research task per vehicle. If the user closes the browser or the application restarts,
the research continues or resumes from where it stopped without redoing completed work. The user
can cancel a running research at any time.

**Why this priority**: Essential for a multi-minute workflow to feel reliable, but the core
results (Stories 1–3) can be demonstrated without it.

**Independent Test**: Start a research, observe task-level status updates; restart the
application mid-research and verify it resumes without repeating completed tasks; start another
research and cancel it, verifying it stops and is marked cancelled.

**Acceptance Scenarios**:

1. **Given** a running research, **When** the user views it, **Then** they see the current phase
   and each task's status (pending, running, completed, failed, retrying) updating live, without
   internal AI reasoning text.
2. **Given** the user loses connection and reconnects, **When** the view reloads, **Then** it
   shows the current state and continues receiving updates without missing state changes.
3. **Given** the application is restarted while research is running or awaiting approval,
   **When** it comes back, **Then** the research can be continued from its last saved point and
   completed tasks are not re-executed.
4. **Given** a running research, **When** the user cancels it, **Then** no new tasks start,
   the research is marked cancelled, and already collected results remain viewable.
5. **Given** one vehicle's research task fails (e.g. a source is unreachable), **When** the
   research continues, **Then** other tasks still complete, the failure is shown, and the report
   marks the affected data as unavailable.

---

### User Story 5 - Known technical issues (Priority: P5)

An enthusiast considering a car wants to know its known technical weak points — recurring
mechanical problems such as timing-chain wear, gearbox mechatronic failures, or battery
degradation. For each vehicle variant the system lists known technical issues with their sources,
and distinguishes recurring, multi-source problems from isolated reports. General opinions
("fun to drive", "boring interior") are not included.

**Why this priority**: Valued by experts and enthusiasts, but secondary to specifications and
performance for the MVP.

**Independent Test**: Run research on a vehicle with a well-documented known issue; verify the
issue appears with sources, an affected component, and a recurring/isolated classification, and
that no subjective opinions are listed.

**Acceptance Scenarios**:

1. **Given** a completed research, **When** the user views a vehicle, **Then** known technical
   issues are listed with affected component, description, sources, and a classification of
   "recurring" (reported by multiple independent sources) or "isolated".
2. **Given** no technical issues were found, **When** the user views the vehicle, **Then** the
   system states that no documented issues were found (not that the vehicle has none).

---

### User Story 6 - Research history and reports (Priority: P6)

The user wants to revisit past research sessions, reopen completed reports, and continue sessions
that were interrupted.

**Why this priority**: Convenience feature that adds value once the core flow works.

**Independent Test**: Complete two researches and interrupt a third; verify all three appear in
history with status and date, completed reports open unchanged, and the interrupted one can be
resumed.

**Acceptance Scenarios**:

1. **Given** previous researches exist, **When** the user opens history, **Then** they see each
   research with its vehicles, status, creation date, and links to its report or to resume it.
2. **Given** a completed research, **When** the user opens its report, **Then** it shows the same
   data, evidence, and simulation results as when it was completed.

---

### Edge Cases

- **Ambiguous vehicle input** (e.g. "Golf GTI" without generation): the system proposes the most
  likely variant, lists alternatives, and marks the ambiguity in the plan; the user chooses before
  approval.
- **Unrecognizable vehicle** (typo, fictional car): the plan marks the vehicle as unidentified;
  the user must correct or remove it before approval.
- **Same vehicle entered twice**: the system warns and asks the user to confirm or change it.
- **Variant not sold in Spain**: the system may resolve the closest market variant but MUST state
  the market difference explicitly.
- **Model-year change mid-generation** (facelift with different power): treated as different
  variants; values are not mixed.
- **Unit ambiguity** (PS vs hp vs kW, curb weight with vs without driver): values are converted
  deterministically and the weight definition is recorded; unconvertible values are flagged.
- **Plug-in hybrid with multiple outputs** (electric-only, combustion-only, combined): combined
  system output is used for simulation; all available outputs are listed in specs.
- **Simulation-insufficient data**: vehicle excluded from the race with an explanation (Story 2).
- **All sources unavailable** for a vehicle: research completes with that vehicle's data marked
  unavailable; the session does not fail.
- **Resource limits reached** (LLM call or retry limit): research stops expanding, completes with
  what it has, and the report states which limit was reached.
- **Variant already in catalog**: the plan shows the stored data's age and lets the user choose
  "reuse" or "research again" per vehicle; stale data (over 90 days) is never reused silently.
- **User never approves the plan**: the research remains in "awaiting approval" and can be
  approved, edited, or cancelled later.

## Requirements *(mandatory)*

### Functional Requirements

**Research creation and planning**

- **FR-001**: Users MUST be able to create a research session with 2 to 4 vehicles, each entered
  as free text with optional model year, plus an optional natural-language research question.
- **FR-002**: The system MUST use Spain as the default market and record the market on each
  research; the design MUST allow other markets later.
- **FR-003**: The system MUST resolve each vehicle to an exact variant identity consisting of
  manufacturer, model, generation, variant/trim, powertrain type (combustion, electric, hybrid,
  plug-in hybrid), model year range, and market.
- **FR-004**: The system MUST mark ambiguous or unidentified vehicles in the plan, offer
  alternative candidates where possible, and require the user to resolve them before approval.
- **FR-005**: Before any research begins, the system MUST present a plan containing resolved
  variants, research categories, planned tasks, planned source types, expected task count, and
  ambiguities, and MUST start research only after explicit user approval.
- **FR-006**: Users MUST be able to approve the plan, change vehicle variant choices (which
  produces a new plan version for approval), or reject the plan (which cancels the research).
- **FR-040**: The system MUST maintain a local vehicle catalog of resolved variants and their
  evidence-backed specifications collected by completed researches. When a planned vehicle matches
  a catalog variant whose data is less than 90 days old (configurable), the plan MUST offer the
  user, per vehicle, to reuse the stored data or research it again; stored data older than the
  threshold MUST be marked stale and offered only together with fresh research. Reused data keeps
  its original evidence and retrieval dates.

**Technical research**

- **FR-007**: The system MUST research each approved vehicle in independent, concurrently running
  tasks, so that the failure of one task does not stop the others.
- **FR-008**: The system MUST prefer manufacturer/official sources and MAY use independent
  automotive publications, encyclopedic sources, and specification databases; it MUST respect
  source terms of use.
- **FR-009**: Every collected value MUST carry: value, unit, source name, source link, source
  type, retrieval date, the supporting excerpt, the vehicle variant, and a provenance label (one
  of: manufacturer claim, measured, sourced fact, derived, simulated estimate, assumption).
  Provenance of collected values MUST be assigned deterministically from the source type:
  manufacturer/official source → manufacturer claim; independent instrumented test source for a
  Tier 3 (measured performance) attribute → measured; any other case → sourced fact.
- **FR-010**: The system MUST attempt to collect **Tier 1** specifications for every vehicle:
  maximum power (with rpm), maximum torque (with rpm range), curb weight (with its definition,
  e.g. with/without driver), drivetrain, transmission type and number of gears, claimed 0–100 km/h,
  claimed top speed, engine type, displacement, fuel type; and for electric/plug-in vehicles:
  battery capacity (usable/gross), number of motors, and motor power.
- **FR-011**: The system MUST attempt to collect **Tier 2** specifications where available: engine
  code, layout, number of cylinders, aspiration, bore × stroke, compression ratio, redline, gear
  ratios and final drive, weight distribution, length/width/height/wheelbase, tyre sizes, brakes,
  suspension type, drag coefficient and frontal area, and platform.
- **FR-012**: The system MUST attempt to collect **Tier 3** data: independently measured
  performance results (e.g. 0–100 km/h, 400 m) from instrumented tests, labeled "measured" and kept
  separate from manufacturer claims.
- **FR-013**: Missing values MUST be recorded and displayed as "unavailable" and MUST NOT be
  estimated, invented, or copied from another variant.

**Known technical issues**

- **FR-014**: The system MUST collect known technical issues per variant (affected component,
  description, sources) and classify each as "recurring" (multiple independent sources) or
  "isolated"; subjective opinions MUST be excluded.

**Verification**

- **FR-015**: The system MUST detect variant/generation/model-year mismatches, conflicting values
  for the same attribute beyond a defined tolerance, incompatible or ambiguous units, and values
  lacking supporting evidence.
- **FR-016**: When conflicts or critical gaps (missing Tier 1 values) are detected, the system
  MUST run targeted follow-up research, bounded by a configurable maximum number of follow-up
  rounds (default 2).
- **FR-017**: Conflicts MUST be resolved only by this documented rule, and the rule applied MUST be
  recorded per conflict:
  1. Source authority order: manufacturer/official > independent instrumented test (for
     performance figures only) > established automotive publication > encyclopedia or
     specification database.
  2. The value from the highest-ranked source type wins.
  3. If sources of the highest-ranked type disagree, the value agreed by at least two independent
     sources of that type wins; otherwise the conflict stays unresolved.
  Unresolved conflicts MUST be shown with all competing values and sources; resolved conflicts
  MUST keep the alternatives visible.
- **FR-018**: The system MUST assign a confidence level per value using these rules:
  **High** — from a manufacturer/official source, or at least two independent sources agree
  (values within the FR-017 conflict tolerance, sources on different domains);
  **Medium** — a single non-manufacturer source; **Low** — unresolved conflict, or only weak or
  indirect evidence, meaning the value is known only from a search snippet of a source that may
  not be fetched, or the source states it for the whole generation/engine rather than the
  specific variant. The vehicle-level confidence MUST be shown as the share of its Tier 1 values
  rated High (unavailable Tier 1 values count as not High). Confidence MUST NOT be presented as a
  probability, and the user MUST be able to see which rule produced each level.

- **FR-019**: The system MUST normalize all values to consistent units and present them in metric
  units (kW and hp, N·m, kg, km/h, s, mm).
- **FR-020**: The system MUST compute derived metrics — power-to-weight, torque-to-weight,
  weight-to-power, specific output (power per litre) for combustion engines, and differences
  between vehicles — with each result traceable to its inputs.
- **FR-021**: The system MUST rank vehicles per metric and show an overall comparison table;
  rankings MUST skip vehicles whose required inputs are unavailable or unresolved.
- **FR-022**: All calculations MUST be deterministic: identical inputs produce identical outputs.

**Drag race simulation**

- **FR-023**: The system MUST simulate a standing-start straight-line acceleration run for each
  vehicle with sufficient data, accounting for mass, power, aerodynamic drag, rolling resistance,
  drivetrain efficiency, and traction limits (dependent on driven axles).
- **FR-024**: The simulation MUST use powertrain-specific behavior: combustion — power-limited
  with traction limit and an allowance for shift losses; electric — full torque to base speed then
  constant power, no shifts; hybrid/plug-in hybrid — combined system output, with the
  simplification noted.
- **FR-025**: Simulation results MUST include speed, distance, and acceleration over time; 0–100
  km/h; 0–200 km/h (or "not reached"); 400 m time; speed at 400 m; and finishing order.
- **FR-026**: Simulation results MUST be labeled "simulated estimate", MUST show the simulation
  model version, MUST list every assumption used, and MUST be shown next to manufacturer-claimed
  and measured values where available.
- **FR-027**: Simulation inputs not available from sources (e.g. drag coefficient, frontal area,
  tyre grip) MUST use documented defaults based on vehicle class, labeled "assumption".
- **FR-028**: Vehicles lacking power or weight MUST be excluded from the simulation with an
  explanation.
- **FR-041**: Users MUST be able to adjust a limited set of race settings before running a drag
  race: road surface (dry / wet), extra load in kg (passengers/cargo, 0–500 kg), and ambient
  conditions (air temperature and altitude); defaults are dry, 0 kg, 20 °C, sea level. Users MAY
  first record a prediction of the finishing order, which is shown next to the simulated result.
  Vehicle specifications MUST NOT be editable in the drag race (reserved for a later What-If
  feature). Users MAY run the race repeatedly with different settings; each run is stored with its
  settings, assumptions, and model version.

**Report**

- **FR-029**: The system MUST produce a structured report per research containing: resolved
  variants, specifications by tier, comparison tables, derived metrics and rankings, simulation
  results, known technical issues, evidence list with links, conflicts (resolved and unresolved),
  confidence indicators, limits reached, and resource usage (AI usage and estimated cost). Any
  AI-written narrative in the report MUST contain only numbers that appear among the report's
  computed or sourced values (within display rounding); sentences that fail this check are
  removed.
- **FR-030**: Completed reports MUST remain reproducible: they preserve inputs, sources, and
  model versions used, and display the same content when reopened.

**Session lifecycle**

- **FR-031**: A research MUST move through the states: created → planning → awaiting approval →
  running → verifying → analyzing → completed, with terminal states failed and cancelled.
- **FR-032**: The system MUST show live progress: current state and per-task status (pending,
  running, completed, failed, retrying), without exposing internal AI reasoning.
- **FR-033**: Research sessions MUST survive application restarts and MUST resume from the last
  saved point without repeating completed tasks.
- **FR-034**: Users MUST be able to cancel a research at any time before completion; partial
  results remain viewable.
- **FR-035**: Users MUST be able to list past research sessions with vehicles, status, and date,
  open completed reports, and resume interrupted sessions.

**Limits and cost control**

- **FR-036**: Each research MUST be bounded by configurable limits: maximum AI calls, maximum
  follow-up rounds, maximum concurrent tasks, and per-request timeouts. When a limit is reached,
  the research completes with available data and reports which limit was hit.
- **FR-037**: The system MUST record AI usage (calls, tokens, duration) and estimated cost per
  research and display them in the report.

**Interface**

- **FR-038**: The system MUST provide a web interface in English with: research creation
  (vehicle entry), plan review and approval, live progress view, comparison view with evidence
  links and provenance labels, conflict view, drag race view with charts and results table, and
  research history.
- **FR-039**: Market price research is out of scope; the design MUST allow it to be added later as
  an additional research category without changing existing flows.

### Key Entities

- **Vehicle Variant**: The exact identity of a car — manufacturer, model, generation, variant/trim,
  powertrain type, model year range, market. Separate from its specifications. Unique within the
  local vehicle catalog; reused across researches.
- **Vehicle Catalog**: The local, growing collection of variants and their evidence-backed
  specifications from completed researches, each with last-research date and freshness status
  (fresh / stale).
- **Specification Value**: One attribute of a variant (e.g. maximum power) with value, unit,
  provenance label, confidence, and links to its evidence.
- **Evidence**: A source record — source name, link, type (manufacturer, publication,
  encyclopedia, database, instrumented test), retrieval date, supporting excerpt, variant it
  refers to.
- **Claim**: A statement extracted from evidence (e.g. "max power 180 kW") that verification
  checks against other claims.
- **Conflict**: Two or more disagreeing claims for the same attribute and variant, with status
  (resolved/unresolved) and resolution rule.
- **Technical Issue**: A known problem of a variant — component, description, sources,
  recurring/isolated classification.
- **Research**: A session with its vehicles, question, market, state, limits, plan, tasks, usage,
  and report.
- **Research Plan**: Proposed variants, categories, tasks, source types, task count, ambiguities;
  approved or rejected by the user.
- **Research Task**: A unit of work (e.g. "technical specs for vehicle 2") with status, attempts,
  and outcome.
- **Comparison**: Normalized values, derived metrics, and rankings across the research's vehicles.
- **Simulation**: A drag race run — model version, race settings, optional user prediction, inputs, assumptions, per-vehicle results and
  time series, finishing order.
- **Report**: The assembled, reproducible output of a completed research.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can enter 3 vehicles and reach the plan-approval step in under 3 minutes,
  including resolving any ambiguity.
- **SC-002**: A research with 3 vehicles completes (from approval to report) in under 10 minutes
  in 90% of runs under normal source availability.
- **SC-003**: 100% of specification values shown in reports carry a provenance label, and 100% of
  sourced values link to at least one evidence record.
- **SC-004**: On a reference set of at least 20 vehicles with known specifications, the correct
  exact variant is resolved (or correctly flagged as ambiguous) in at least 90% of cases.
- **SC-005**: On the same reference set, at least 80% of Tier 1 values are found, and at least
  95% of found Tier 1 values match the reference within tolerance (e.g. ±2% for power/torque,
  ±3% for weight).
- **SC-006**: Zero invented values: no value appears in a report without a source, derivation, or
  "assumption" label (verified across the reference set).
- **SC-007**: 100% of deliberately planted conflicts and variant mismatches in test scenarios are
  detected and shown to the user.
- **SC-008**: Repeated simulations with identical inputs and model version produce identical
  results in 100% of runs.
- **SC-009**: For reference vehicles with published instrumented test results, the simulated
  0–100 km/h is within ±15% of the measured value for at least 80% of vehicles before simulation
  results are described as realistic estimates.
- **SC-010**: Progress changes become visible to the user within 5 seconds of occurring.
- **SC-011**: After an application restart, 100% of interrupted researches can be resumed and none
  re-execute already completed tasks.
- **SC-012**: A single failed source or task never causes a whole research to fail (verified by
  failure-injection test scenarios).
- **SC-013**: No research exceeds its configured AI call limit; every report shows usage and
  estimated cost.
- **SC-014**: The research plan (resolved variants) is shown within 60 seconds of submitting the
  vehicles in 90% of runs under normal source availability.

## Assumptions

- **Single local user**: the MVP runs locally for one user (e.g. a family); no accounts or login.
  The design must not block adding users later.
- **Language**: interface and reports in English; source content may be in any language (Spanish
  sources expected for the Spain market).
- **Market**: Spain is the default market; specifications are largely market-independent, but
  market-specific variants are recorded.
- **Prices out of scope**: no market price research in the MVP; only a placeholder category.
- **Sources**: the user has (or will obtain) access to a general web search capability and AI
  model access from at least one of the two supported AI providers; no paid automotive data feed
  is required.
- **Simulation v0.1 fidelity**: no individual gear ratios, torque curves, or launch-control
  modeling; gear-ratio-based simulation is a later version. Default physics constants (rolling
  resistance, drivetrain efficiency, tyre grip, drag by body class) are documented and versioned.
- **Conflict tolerance** defaults: ±2% for power/torque, ±3% for weight/dimensions, ±0.2 s for
  claimed 0–100 km/h, exact match for categorical values (drivetrain, cylinders); configurable.
- **Data retention**: research history is kept indefinitely on the local machine until the user
  deletes it.
- **Reference set**: a curated set of ≥20 vehicles (mix of combustion, electric, hybrid) with
  known specifications and published instrumented tests will be assembled for evaluation.
- **Report export** (JSON, Markdown, PDF, CSV) is out of scope for the MVP; reports are viewed in
  the app. The stored report structure must allow adding export later.
- **Out of scope**: Car Hunter, Market Intelligence, Track Battle, Engine Detective, What-If
  Garage, Car Championship, ownership cost, 3D visualization, multi-user collaboration,
  semantic/vector search.
