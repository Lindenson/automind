# Next session: where to start

State on 2026-11-04:

- **main** contains specs 002–005 and spec 007 (the profile drives the assessment), increments A–J (PRs #14–#24; ADR-027). The review findings and their status are in `docs/review-2026-11-03.md`.
- **Spec 006 — electrified cars** is implemented (PRs #28–#36; ADR-028; `specs/006-electrified-cars/tasks.md`):
  - A: energy model per powertrain (`domain/energy.py`), EV attributes, meaning rules (`domain/sense_ev.py`), EV queries;
  - B: Spanish prices with dates (`config/energy.yaml`), home charging and the user's prices, the home-charging question;
  - C: climate and motorway factors;
  - D: efficiency in €/100 km, DGT label, break-even, market incentives (`market_facts`, area `incentives`);
  - E: new brands (`makes.yaml: new_in_market`), warranty and network facts, like-for-like period totals;
  - F/T050: electric block, TCO split, explainers, report sentences (share, €/100 km, break-even);
  - G: goldens G8–G12 and the FR-022 metric (`ENERGY_REPORT` intake event).
- **006 still open**: only the paid live check of BYD Seal U DM-i vs Ateca (T054, about €0.15–0.30). It waits for the owner's yes.
- **Waits for the owner's yes**: a data repair of 65 stored claims. A dry run with the new rules (scratch script, no writes) found:
  - 5 BYD 0.9 l/100 km → weighted;
  - 4 BYD 18.3 kWh → gross;
  - 4 maximum boot volumes rejected;
  - 47 older unit rejections now accepted (displacement, ground clearance in cm, small hybrid batteries);
  - 1 DSG "40,000 miles" rejected.

  Until it runs, the stored BYD has no priced consumption, so its energy line reads "cannot be computed".

## Steps

1. `git checkout main && git pull`.
2. With the owner's yes: back up the DB, run the repair dry run again, apply it, then run the paid live check (T054) and fix what it shows.
3. After each change:
   - run `scripts/check.sh`;
   - restart dev with `pkill -x automind-api; scripts/dev.sh`;
   - run `scripts/deploy.sh up`.

## Open after 007

- **Catalog cleanup (waits for the owner's yes).** Four Mazda CX-5 rows were invented during chat 0d7fd924: "3rd gen 2.0 165 CV" ×3, and model "Mazda CX-5" 2.5 140 CV. They have no data and no chat uses them. Also fix the 3rd gen 2.5 gearbox to automatic and the KF end year to 2025. The SQL is in the 007-F notes of the session; the code no longer creates such rows.
- The rescore queue is in memory: an edit waiting during a restart is lost.
- Candidates (US7) come only from cached line-ups and the catalog. A line-up refresh for the leading makes is paid and needs a cost estimate first.
- The live re-run of chats 757cff3d and 0d7fd924 is paid: estimate first, then the owner's approval.
- The flaky `test_limit_pause`; no front component tests.
- The rest of the security list in the review (chat isolation, metrics, WebSocket Origin, daily budget cap) is required before any external demo.

## Evidence to reuse

- **Chat 0d7fd924** (Mazda CX-5 vs Honda CR-V, family, new 2025): the intake incident fixed in PR #21. Its replay checks the chips, the current generation and "find it".
- **Chat 757cff3d** (BMW 320d Touring vs Golf Variant R): the search recall incident (US5).
- **Chat 5be54966** (BYD Seal U DM-i vs SEAT Ateca): the 006 incident.

## Rules that stay in force

- Never scrape classifieds (deny-list in `backend/config/sources.yaml`).
- Respect robots.txt.
- Announce any paid live run with a cost estimate first.
- API keys live only in `.env`; never print them.
- Reply to the owner in Russian.
