# Next session: where to start

## State after spec 010 implementation (2026-11-05, evening): start here

- Spec 010 is implemented except 8 tasks (see `specs/010-self-observing-registry/tasks.md`, unchecked):
  T059 candidate label + half weight, T060 replacement/agreement truth signals, T065 gap-driven discovery search,
  T067 "no data" names the sources tried, T075 remove `domain/learned.py`, T076 docs, T077 quickstart walk-through,
  T078 switch `registry.autonomy: true`.
- **Autonomy is OFF** (`backend/config/registry.yaml`): the registry records attempts, scores, admits sites and
  journals, but research keeps the configured order. Turn it on (T078) after a live week gives a baseline.
- **No live run yet**: this checkout has no `.env`. Needed: `GOOGLE_API_KEY`, `SERPER_API_KEY`. Estimate cost first.
- **Admin**: `/admin` — Top problems (10 by impact, copy for Claude Code) and Sources (quality, changes, revert).
  Prometheus: `/metrics` (METRICS_TOKEN), rules `deploy/prometheus/automind-rules.yml`, `scripts/deploy.sh up --monitoring`.
- **Moving the install**: `docs/deploy.md` (`deploy.sh export / import / move`), rehearsed locally.
- **Tests**: `scripts/check.sh` green (962 backend, 101 frontend). Known pre-existing failure on main, deselect:
  `tests/integration/test_identify_ladder.py::test_fallback_without_a_sourced_list_asks_the_power_never_takes_the_first_row`.
  Never run two `check.sh` at once: they share `automind_test`.

## Redesign on 2026-11-05 (later): start here

- **Spec 010 supersedes 009**: `specs/010-self-observing-registry/spec.md`. Plan file of the redesign:
  `~/.claude/plans/composed-imagining-kernighan.md`. Constitution v1.2.0 adds principle XII.
- **Owner's boundary**: for logic, parsers, rules and dialogue the system only measures, groups failures,
  diagnoses and offers a "copy for Claude Code" task; it never changes them. For sources it is autonomous
  (order, admit, promote, demote, retire) inside hard limits, with a change journal and a Sources admin page.
- **What the system does today**: `docs/baseline.md` (one summary of specs 001–009).
- **009's open fixes** (PHEV, junk used price, relevance, year in queries, dialogue of chat 20b5b7f9) are
  not implemented directly: they become the first issues of 010's issue queue (US5).
- **Next**: `/speckit-plan`, `/speckit-tasks`, `/speckit-implement` for 010. Order: observation +
  Prometheus base → insight + Top problems → Prometheus rules → registry in DB (same behaviour) → registry autonomy and Sources screen. Admin page = 2 screens only; detailed metrics and alerts live in Prometheus.

## State on 2026-11-05 (before the redesign)

- **main** has specs 002–008, plus the 008 follow-ups:
  - PRs #48–#49: live-run fixes and the fallback ladder;
  - PR #50: used price and brand warranty researched for used cars; brand pages judged by the make; the warranty search collected apart; the used price searched by model year; a generation-wide range never stands for one year;
  - PR #51: spec 009, source survey, and ToS-forbidden favourites removed.
- **Next: implement spec 009** (`specs/009-source-registry/spec.md`). Spec Kit stage: spec written and checklist passed. Next come `/speckit-plan`, `/speckit-tasks` and `/speckit-implement`.
- **The owner's direction (2026-11-05)**, also in the spec:
  - Europe is ONE market and no country is preferred, Spain included;
  - "no data" is unacceptable when the data exists somewhere;
  - keep a curated registry of verified sources per kind of data, with lessons;
  - every live-chat lesson becomes a registry update in the same PR as the code fix;
  - new sources are admitted by a defined procedure: discovery → admission check (classifieds, robots, terms, content) → candidate (half weight, labelled) → verified (after 3 good runs + review);
  - demotion after 3 failures or any junk; re-checks every 90 days (verified) or 180 days (blocked or forbidden);
  - sources outside Europe (RU, CN, JP, US) may give specs, reliability and real consumption, never prices.
- **Source survey**: `specs/009-source-registry/registry-survey.yaml`.
  - 198 sites, each with robots and terms checked and quoted.
  - Verdicts: 87 candidate, 45 classifieds, 22 tos_forbids, 12 blocked, 12 paywall, 12 js_only, 8 dead.
  - Seed the registry from it.
  - Most valuable open datasets:
    - EEA OBFCM: real-world fuel use, including PHEV;
    - EEA CO2: WLTP figures, electric range and kWh for every EU car;
    - RDW (NL), DVSA MOT (UK), Traficom (FI), KBA (DE);
    - fueleconomy.gov and NHTSA (US).

    These are datasets or APIs, not pages, so the plan needs a "dataset" source type with download and refresh.
  - Used price is the hard part: nearly every European valuer forbids robots. The open ones are:
    - DAT (dat.de);
    - the Spanish tax tables (BOE Orden HAC/1501/2025);
    - motor.es.

    Add an estimate from the new price × sourced residual values, labelled, and listing text pasted by the user (US8).
- **Incident behind 009: chat 20b5b7f9** (Kia Sorento 2024 1.6 T-GDI PHEV 288 CV new vs Toyota Land Cruiser Prado J150 2010 3.0 D-4D 173 CV used). Its flaws, all listed in the spec:
  - the PHEV had no charge-sustaining consumption, so its TCO had no fuel, yet the costs were still compared;
  - the Prado's used price came from a junk US-dollar page;
  - the gearbox rule matches " manual" inside "manuales";
  - generation "2024" is stored instead of MQ4;
  - brand-wide service pages were rejected;
  - used-car queries carry no year;
  - the first message got "could not map";
  - "find me a Kia" asked "which model" instead of proposing candidates.
- **Suggested order for 009**:
  1. PHEV consumption (EEA OBFCM + EU utility-factor estimate) and no TCO comparison when a main cost item is missing;
  2. relevance fixes and year in queries;
  3. the registry (git YAML + run statistics in DB + proposals + admission check);
  4. used price (DAT, BOE, residual estimate, user-pasted listings);
  5. the dialogue fixes;
  6. a paid replay of chat 20b5b7f9, after a cost estimate and the owner's yes.
- **Live driver** for WS replays: a small script connecting to `ws://127.0.0.1:8000/ws/chat/{id}` with the `automind_owner` cookie.
  - First send `{"type":"hello","last_seq":N}`.
  - Confirm messages use the field `choice` (not `option`).
  - "find it" is `{"type":"find","focus_cars":["car#2"],"areas":[...]}`.

## Earlier state (2026-11-04)


- **main** contains specs 002–005 and spec 007 (the profile drives the assessment), increments A–J (PRs #14–#24; ADR-027). The review findings and their status are in `docs/review-2026-11-03.md`.
- **Spec 006 — electrified cars** is implemented (PRs #28–#36; ADR-028; `specs/006-electrified-cars/tasks.md`):
  - A: energy model per powertrain (`domain/energy.py`), EV attributes, meaning rules (`domain/sense_ev.py`), EV queries;
  - B: Spanish prices with dates (`config/energy.yaml`), home charging and the user's prices, the home-charging question;
  - C: climate and motorway factors;
  - D: efficiency in €/100 km, DGT label, break-even, market incentives (`market_facts`, area `incentives`);
  - E: new brands (`makes.yaml: new_in_market`), warranty and network facts, like-for-like period totals;
  - F/T050: electric block, TCO split, explainers, report sentences (share, €/100 km, break-even);
  - G: goldens G8–G12 and the FR-022 metric (`ENERGY_REPORT` intake event).
- **Spec 006 is closed** (T054 done 2026-11-04). The data repair ran with the owner's yes (backups
  `backups/pre-repair-006-20261104-0905.dump` and `pre-repair-006b-20261104-0929.dump`). The live run of the
  incident pair (≈ €0.16) found and fixed (PRs #37–#40):
  - Gemini returned no cars, or context for cars added in the same message: a code safety net takes two named cars
    from the user's words, and such context is folded into the added cars;
  - an electrified car missing energy inputs now retries its specs area even when an old run met the minimum;
  - the repair checks pairs with the car's known values.
- **Open data gap**: the BYD Seal U DM-i charge-sustaining consumption is not published in the sources found
  (one Czech table row could not be verified), so without the user's figure its energy line reads "cannot be
  computed". PR #42: the user can state it ("в гибридном режиме 5,5 л", also fuel l/100 km, kWh/100 km, electric
  km): `CaseFile.stated_energy`, tied to the named car or the only car it fits, labelled "your figure".

- **Spec 008 — identification ladder and used cars as used** (ADR-030; `specs/008-identification-ladder`):
  - the versions of each model generation are a sourced cache (`model_versions`, 60 days; `application/versions.py`, role `versions`);
  - a pure ladder narrows a car (`domain/ladder.py`): generation → engine (fuel → family → power) → gearbox → drive;
  - what does not exist is said; "choose for me" or two asks settle a level by the base version; no PROPOSE or REMOVE_OR_CHOOSE on the ladder;
  - a property test covers 1,500 scenarios;
  - used cars (`domain/used.py`): a year not given is asked once, then assumed from mileage or generation (never age 0); the used price is the purchase price (else no data); depreciation runs from the used price; mileage counts in reliability; the warranty is shown as remaining or expired.

## Steps

1. `git checkout main && git pull`.
2. Done 2026-11-04 (PR #43, ADR-029): owner cookie per browser, same-site only, operator metrics behind
   ADMIN_TOKEN, DAILY_CAP_EUR. Still before a public deployment: accounts, per-owner rate limits, TLS.
   Catalog clean-up done (PR #44). Candidates: scheduled re-checks of stored data;
   Gemini for extraction measured on the goldens.
3. After each change:
   - run `scripts/check.sh`;
   - restart dev with `pkill -x automind-api; scripts/dev.sh`;
   - run `scripts/deploy.sh up`.

## Open after 007

- **Catalog cleanup: done 2026-11-04 (PR #44).** `scripts/repair-data.sh --duplicates` (dry run; `--apply` after a backup) folds rows that are one car (same engine, gearbox, wheels, body, version) into the row with the most claims and repoints case files, events and saved state. Applied (backups/pre-catalog-merge-20261104-1822.dump): BMW G20 320d ×3, Golf R Variant ×2, Range Rover Sport HSE ×2, Cupra Terramar 1.5 eTSI ×2; Škoda → Skoda; an estate's boot from another body's page or < 400 L is rejected (Golf R Variant 611 L). The Mazda CX-5 rows of chat 0d7fd924 were already gone. Left as is (different versions or not enough data): Hyundai i30 N 275 vs 280 PS, RAV4 XA50 2.5 Hybrid without power.
- The rescore queue is in memory: an edit waiting during a restart is lost.
- Candidates (US7) come only from cached line-ups and the catalog. A line-up refresh for the leading makes is paid and needs a cost estimate first.
- The live re-run of chats 757cff3d and 0d7fd924 is paid: estimate first, then the owner's approval.
- No front component tests. (`test_limit_pause` was a real bug: the report hit the call limit; fixed.)
- The rest of the security list in the review (chat isolation, metrics, WebSocket Origin, daily budget cap) is required before any external demo.

## Evidence to reuse

- **Chat 0d7fd924** (Mazda CX-5 vs Honda CR-V, family, new 2025): the intake incident fixed in PR #21. Its replay checks the chips, the current generation and "find it".
- **Chat 757cff3d** (BMW 320d Touring vs Golf Variant R): the search recall incident (US5).
- **Chat 5be54966** (BYD Seal U DM-i vs SEAT Ateca): the 006 incident.

## Rules that stay in force

- Never scrape classifieds (deny-list in `backend/config/sources.yaml`); the robot never imitates a browser or bypasses anti-bot protection.
- Respect robots.txt and the site's terms of use (a terms clause forbidding automated access = deny-list).
- Announce any paid live run with a cost estimate first.
- API keys live only in `.env`; never print them.
- Reply to the owner in Russian.
- Destructive DB changes need the owner's yes and a backup first.
- Limits ask "continue?", never cancel.
- Commit, push and merge to main without review (owner's standing instruction).
