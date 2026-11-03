# Research: Understanding the User — Intake and Identification

**Feature**: 005-user-intake-identification | **Date**: 2026-11-03

Every decision below is backed by the code as of `main` d872fb8 and by the incident chat 5be54966.

## R0. What actually broke (code trace of the incident)

| Reply | What the code did | Why it failed |
|---|---|---|
| "BYD Seal U допустим" | The interpreter set make BYD, model Seal U (`set_car_context`). `prepare_variants` → `resolve_with_llm` → `_check_known` raised `UnknownModel`. | BYD is in neither the catalog nor `generations.yaml`. The resolver returned no generation, so `known_model and generation` was false. `closest` was empty because the pool for BYD was empty. |
| (question) | `ask.fill_questions` used the `UNKNOWN_MODEL` template with `request_text` = "byd" and `options = "make and model"`. | `request_text` is never updated from the parsed facts. An empty option list falls back to an English literal. The template is English, and the asker paraphrased it. |
| "byd.com — вот он! и Seat 1.5" | URL → `constraints.url`. Resolver called again, `UnknownModel` again. Seat: `trim_hint="1.5"`. | `byd.com` is a global brand home page, not a model page. The Seat was `AUTO_OK`; `revalidate` checks the generation and level, not the engine. |
| "BYD это Build Your Dream…" | The interpreter returned `general_question`. Policy rule 1 → `ANSWER_GENERAL` → the `general` role greeted the user and named Atto 3. | Rule 1 fires before anything else, even while an intake question is pending. |
| "сравни byd seal u с атекой 1.5" | Make and model were unchanged, so `answer_settles(UNKNOWN_MODEL)` was false ("not understood"). The car stayed `UNKNOWN_MODEL` and policy rule 2 asked again. No resolver call was made. | `UNKNOWN_MODEL` is sticky. Only a *different* make/model counts as an answer, so a repeated correct answer loops forever. |

Conclusions:
1. Identification must run on every intake turn from the current facts.
2. "Unknown" requires an open-world lookup first.
3. Corrections must invalidate a resolved variant.
4. Generic chat must be unreachable while an intake question is pending.
5. Question texts must be localized templates, never English fallbacks.

## R1. An "identify" step on every intake turn

**Decision**: Add a node `identify` between `apply_delta` and `assess`. For every car that is not settled, or whose identity facts changed, it runs the identification pipeline (R2–R5) in the same turn:
- catalog;
- known makes and brand line-up;
- resolver with sources;
- engine matching.

The step returns one of four outcomes per car:
- `IDENTIFIED`: one version fits;
- `CHOICES`: 2–6 concrete options;
- `NEED`: a named missing item;
- `NOT_FOUND`: after a lookup.

`UNKNOWN_MODEL` stops being a sticky resolution. It is recomputed every turn.

**Rationale**: in the incident the identification ran only inside `prepare_variants`, and only when the policy chose CONFIRM_VARIANTS. A car marked `UNKNOWN_MODEL` was never looked up again unless the make or model text changed.

**Alternatives considered**:
- Fix `answer_settles` only. Rejected: it would still not look the car up again.
- Let the interpreter decide. Rejected: constitution III/VI put control flow in code.

## R2. Open-world brands: known makes and brand line-ups

**Decision**:
- **Make registry**: `config/makes.yaml` lists the makes sold in Spain (about 60: European, Japanese, Korean, US, Chinese including BYD, MG, Omoda, Jaecoo, Chery, Leapmotor, Xpeng, Lynk & Co, EBRO, DFSK, Zeekr, Polestar, Cupra). Each entry has:
  - canonical name;
  - aliases and transliterations (ru/es);
  - official Spanish site domain (e.g. `byd.com/es`);
  - parent group (for "EBRO is built on Chery").
- **Line-up lookup**: `application/lineup.py` finds the models of a make on sale in Spain:
  - `query_lineup(make)` searches ES for `"<make> gama modelos precios España"` plus the official site;
  - pages are read cache-first, respecting robots.txt and the deny-list;
  - a web-reader role `lineup` (no tools) returns `[{model, body, powertrains[], price_from_eur, excerpt}]`;
  - every model must occur in its document (`evidence.occurs`), and the price must appear in the excerpt;
  - stored in a new table `brand_lineups` with sources and `fetched_at`, refreshed after 30 days (config).
- **Known model** = in the catalog, in `generations.yaml`, or in the make's line-up. `_check_known` accepts a model from the line-up without the resolver returning a generation. For a NEW car the generation is "current" and is labelled as taken from the line-up source.

**Rationale**: the Spanish market grows mostly through new Chinese brands. A closed catalog locks the user out. Line-ups are facts with sources (constitution I), not model memory.

**Alternatives considered**:
- Trust the resolver's `known_model`. Rejected: it invents (Atto 3) or refuses.
- Hard-code line-ups in config. Rejected: they go stale within months. Config keeps only makes and domains.

## R3. Names in other scripts and transliterations

**Decision**: deterministic first, model second:
1. `domain/identity.transliterate_ru(text)` (GOST-like table) plus the aliases in `makes.yaml`: "сеат" → SEAT, "атека" → Ateca, "биад" / "бид" → BYD, "хендай" / "хюндай" → Hyundai.
2. Fuzzy match (`rapidfuzz.WRatio` ≥ 85) against the make registry, then against the make's line-up.
3. The interpreter prompt keeps writing make and model in Latin. A mismatch between its output and step 1/2 is logged.

**Rationale**: reproducible and testable without a model (constitution IX). The model still helps with free phrasing.

**Alternatives considered**:
- Model-only. Rejected: not testable, and it varies between calls.

## R4. Engine as part of the identity

**Decision**:
- `Constraints` gains `engine_hint`: `{displacement_l?, power_hp?, power_kw?, fuel?: petrol|diesel|hybrid|phev|bev|lpg, family?: "TSI" | "TDI" | "DM-i" | "e:HEV" …}`.
- A deterministic parser `domain/identity.parse_engine(text)` reads:
  - "1.5", "1,5", "1.5 TSI", "150 CV", "150 л.с.", "110 kW";
  - "diesel" / "дизель" / "gasóleo";
  - "DM-i", "PHEV", "eléctrico".
  It fills the hint even if the interpreter missed it. The interpreter rule "engine goes to engine_hint, not trim_hint" is added.
- `vehicle_variants` gains `engine_cc`, `power_kw` and `fuel`, filled by the resolver and upsert. They are back-filled from `variant_name` for existing rows (deterministic parse, migration script).
- `_fits` uses the engine: a variant fits if every stated engine field matches:
  - displacement ±0.05 L;
  - power ±3 kW;
  - fuel equal.

**Rationale**: in the incident "1.5" went to `trim_hint` and changed nothing. Constitution II requires the powertrain to be part of the identity.

## R5. Corrections re-identify the car

**Decision**:
- `domain/intake.identity_key(car)` is a tuple of make, model, generation, engine_hint, gearbox, drive, year, condition and trim.
- `apply_delta` compares it before and after for every car. On a change:
  - `variant_id`, `label` and `resolution` are cleared, and the car becomes `UNRESOLVED`;
  - `previous_label` keeps the old label for the "before → after" line;
  - `request_text` is rebuilt from the facts (`display_name`), so questions never show stale text like "byd".
- This applies to `AUTO_OK` and `CONFIRMED` cars too.
- Research results are keyed by `variant_id`, so values of the old version are not reused for the new one (already true; covered by a test).
- Corrections during research: the hub cancels the pending research of that car (jobs keyed by the old variant are ignored at collect) and re-plans after the new identity is confirmed.

## R6. No repeated questions; bounded attempts; proposing a guess

**Decision**:
- `CaseFile.intake` holds `attempts: {car_key: {item: n}}` and `last_questions: [hash(car, item, text)]`.
- Policy rules in `domain/intake.next_step`:
  - a question with the same (car, item) as last time must use the "rephrase" template variant and carry concrete options;
  - an identical text hash is never sent twice in a row (assert in code, test);
  - after 2 attempts on one item, the step becomes `PROPOSE`: the most likely candidate (top line-up or catalog match at the comparison level) offered as yes/no;
  - after 4 attempts in total for one car (configurable `intake.max_attempts_per_car`), the car is offered for removal or "choose for me". Constitution VI: every loop is bounded.
- An answer counts as progress if any identity fact changed, OR if the identify step's outcome improved (`NOT_FOUND` → `CHOICES` → `IDENTIFIED`). The same make/model repeated now triggers a fresh lookup instead of "not understood".

## R7. One confirmation card (intake card)

**Decision**:
- A new pending kind `CONFIRM_INTAKE` replaces CONFIRM_VARIANTS for new chats and is shown once all cars are `IDENTIFIED`.
- Contents:
  - per car: make, model, generation, engine (cc, kW/CV, fuel), gearbox, drive, year, condition, mileage (used), trim with level, official price (new, with source);
  - profile items: usage, km/year range, region and climate, budget, priorities, family, experience;
  - the research cost estimate.
- Each item carries a `basis`: `STATED`, `INFERRED` (with evidence words), `LOOKED_UP` (with a source) or `ASSUMED` (the default).
- **One "yes" confirms the variants and approves the cost** when the estimate is below the hard cap. Above the cap, the card states that research stops at the cap (as today). This removes one round trip compared with today's two confirmations (variants, then cost).
- Edits:
  - a chip sends `intake_edit {car_key|null, field, value}`, applied by code with no model call;
  - free text goes through the interpreter.
  After an edit the card is shown again with `changed: true` on the edited fields.
- CONFIRM_VARIANTS stays for chats already waiting on one (backward compatible); the frontend renders both.

**Alternatives considered**:
- Keep two separate confirmations. Rejected: the user asked for one step, and today the cost dialog hides what is being researched.

## R8. Staying on task

**Decision**:
- **Policy rule 0**: while `pending.kind in (QUESTIONS, CONFIRM_INTAKE, CONFIRM_VARIANTS)` and the request is `general_question` or `chitchat`, the reply is handled as an intake answer:
  - a brand explanation ("BYD is Build Your Dream, Chinese") sets the make through the registry or line-up;
  - otherwise the next intake step is sent, with a one-line acknowledgement.
- The `general` role is reachable only without a pending intake. Its prompt gets "no greeting after the first assistant message" and "never name a car model the user did not name; suggestions must be marked as such".
- A model that the user did not name is shown only as `suggested: true` with a reason (card and chips).

## R9. Localized questions without English leaks

**Decision**:
- `config/questions.yaml` v2: every template has `en`, `ru` and `es` variants, plus a `rephrase` variant for repeated items.
- Options are always concrete (models, engines, generations, years). There is no literal fallback. When the option list is empty:
  - for the make step: the make's line-up, or the registry's makes close to the text;
  - for the model step: an open question in the user's language, without "did you mean".
- The asker model writes only the acknowledgement sentence; the questions are inserted verbatim by code.
- A language guard (`phrases.guess_language` on the output) re-asks once, then falls back to the template text.

## R10. URL replies

**Decision**: a URL in an intake reply is classified deterministically:
1. Deny-listed (classifieds): not read. The reply says why and asks for the car in words.
2. A maker home page (domain of a make in the registry): sets the make, then shows its line-up.
3. A model or version page: read cache-first, robots respected, `<untrusted_document>`. The resolver extracts the identity, and the reply says "from the page I took: …".

**Rationale**: `byd.com` in the incident is a brand home page; reading it as a model page cannot work.

## R11. Profile intake

**Decision**: Profile gains:
- `region` (free text plus a normalized province or autonomous community, `config/regions.yaml`);
- `climate` (`HOT` | `MILD` | `COLD` | `MOUNTAIN`, derived from the region in config, labelled `INFERRED`);
- `annual_km_min` / `annual_km_max`. A range is kept, the middle is used for costs, and the range is shown.

Usage and priorities are unchanged. The deterministic parser `domain/intake.parse_distance(text)` reads:
- "1–2 тыс км в месяц" → 12,000–24,000 per year;
- "20k a year";
- "мало езжу".

New/used:
- `CONDITION` question kind, asked once for all cars whose condition is `UNKNOWN`;
- inferred from the words "new", "0 km", a year ≥ the current year minus 0, "replace my old", a mileage.

Year:
- asked for USED cars;
- set to "current" for NEW cars.

Climate is used later (spec 006) for battery and AC loads. In 005 it is stored and shown.

## R12. "Find the matching model for me"

**Decision**:
- `domain/intake.rank_lineup(lineup, profile, other_cars)` scores line-up models by:
  - body and size against usage and family (FAMILY → SUV/estate/MPV ≥ compact);
  - powertrains against priorities and km (efficiency or high km → hybrid/PHEV/BEV first; HOT climate does not penalize);
  - price band against the budget, or against the other compared cars when there is no budget (same segment ±30%).
- It returns the top 1–3 with machine reasons (`["family SUV", "PHEV: low running cost at 18,000 km/yr", "price close to the Ateca"]`). The text phrases them. Deterministic (constitution III).

## R13. Measurement

**Decision**:
- A new table `intake_events` (chat-scoped, cascade on delete) records:
  - `asked` (car, item, attempt, text_hash);
  - `answered` (progress yes/no);
  - `corrected` (before → after);
  - `proposed`, `confirmed`;
  - `research_started` (all_confirmed: bool).
- `domain/metrics` adds:
  - replies to a confirmed identity;
  - repeated questions;
  - corrections that changed the identity;
  - research on an unconfirmed car (must be 0).
- They are shown on the existing metrics endpoint.

## R14. Golden dialogues

**Decision**: replay goldens G21–G30 with recorded model and search cassettes:
- G21: the incident (BYD Seal U vs Ateca 1.5);
- G22: an unknown brand by name only ("MG vs Dacia");
- G23: an engine correction;
- G24: a URL answer (model page, and a classifieds link refused);
- G25: transliteration ("хендай туссан или киа спортейдж");
- G26: "find a model for me" (Omoda / Jaecoo for a family);
- G27: used with mileage;
- G28: EV vs combustion (Seal U EV vs DM-i as different cars);
- G29: region and climate ("Sevilla, 2,000 km/month");
- G30: a brand explanation while a question is pending (no general chat).

Assertions:
- no identical question twice;
- confirmed identity within ≤3 user replies;
- engine on the card equals the user's;
- language;
- no greeting after the first turn;
- research only after the card's "yes".

Live recording waits for paid Gemini and is announced with a cost estimate first.
