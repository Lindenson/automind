# Quickstart: validating spec 007

## Prerequisites

- Docker Postgres up (`scripts/deploy.sh up` or the dev compose), migrations applied (`0010_learned_sources`).
- `scripts/check.sh` green.
- No paid calls are needed for the checks below. They use fakes and recorded search. The live re-run of chat 757cff3d (step A3) costs money: give an estimate and ask the owner first.

## A. Search recall (increment A)

1. Unit: `pytest backend/tests/unit/domain/test_search_plan.py -k short`. The variant "Volkswagen Golf Mk8.5 Golf Variant R 2.0 TSI 333 CV DSG 4MOTION" gives the short form "Volkswagen Golf Variant R 333". "BMW 3 Series G21 320d Touring M Sport Steptronic" gives "BMW 320d Touring" (the engine code names the model). No query contains "Mk8.5", "G21", "DSG" or a repeated word.
2. Unit:
   - a DE reliability favourite uses "Pannenstatistik";
   - an ES one uses "fiabilidad";
   - a zero-hit favourite produces one retry query;
   - an empty cached result expires after 6 h.
3. Recorded replay: `pytest backend/tests/unit/test_recall_757cff3d.py`. Round 0 has pages for specs, measured and reliability for both cars (SC-006).
4. Learned sources: `pytest backend/tests/unit/domain/test_learned.py`. Expected behaviour:
   - promotion after 3 accepted runs;
   - expiry after 5 misses;
   - a deny-listed or look-alike brand domain is never MANUFACTURER and never learned when denied.
5. Manual: open `/research/metrics`. It shows learned sources and the empty-search share per area.

## B. Profile understood (increment B)

- Golden G31: "BMW 320d M Sport или Golf R?" gives persona PERFORMANCE, INFERRED, with evidence "M Sport". Ownership and km are ASSUMED. At most 1 question.
- Golden G32: "вожу детей в школу, по выходным в горы, бюджет 30к" gives family FAMILY (INFERRED), usage MOUNTAINS and budget 30,000. The card shows "correct?" chips.
- Unit: `numbers_in("до 20 тыщ") == {20000}`, `numbers_in("1,5 млн") == {1500000}`, `numbers_in("Golf 7 2015") == {7, 2015}`.
- Unit (ask_value): km is asked only when 8,000 vs 30,000 km flips the winner in the fixture.

## C. Weights (increment C)

- `pytest backend/tests/unit/domain/test_weights.py`:
  - one test per rule in profile_rules.yaml;
  - the cap is applied;
  - a manual +10 survives a persona change;
  - "reset" removes it;
  - an old case with `weights_overridden` shows the same numbers after the upgrade.
- vitest: the Weights card lists reasons and shows a "set manually" badge and a "back to automatic" button.

## D. RESCORE (increment D)

- Graph test: a finished fixture report, then PATCH `{persona: "PERFORMANCE"}`. Expected:
  - one rescore turn;
  - 0 search calls and 0 interpreter calls;
  - weights and scores change;
  - the message says what changed;
  - it finishes under 2 s (SC-004).
- Graph test: PATCH during a RUNNING turn returns 409. The store queues the patch and sends it after `turn_done`.
- Graph test: PATCH `{condition: "USED"}` returns `rescore: "research_needed"` with `missing`.
- Manual (dev UI): edit km in the panel; changed scores are highlighted.

## E. Verdict per profile (increment E)

- Three-profile test (SC-005), same fixture pair:
  - racer, 3 years;
  - family, 8 years, 20,000 km;
  - used buyer with a 400 €/month limit.

  At least two verdicts differ, and each text names the profile reason.
- TCO block title shows the user's period ("за 8 лет").
- `OVER_BUDGET` appears when the price exceeds the budget. The over-budget car is "best if the budget allows".

## F–I

- F: replay the chat 757cff3d intake. The offered label sent as text is accepted. The option lists for a new car contain no F30/F31 rows.
- G: `pytest -k review_regressions`. Each example from the review passes (excerpt gap, "150" vs "1500 rpm", gearbox conflict, guard "10 л/100 км, гарантия 7 лет", "además").
- H: graph tests for the hop cap (partial answer), a provider error on interpret (retry then a localized message) and a timeout with saved data (report from saved data).
- I: golden G36, "посоветуй семейный кроссовер до 25к", gives a card with 2–3 candidates, each with a reason.

## After each increment

Run `scripts/check.sh`, restart dev (`pkill -x automind-api; scripts/dev.sh`), then `scripts/deploy.sh up`. Commit, push and merge the increment's PR to main.
