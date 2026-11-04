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

- Never scrape classifieds (deny-list in `backend/config/sources.yaml`).
- Respect robots.txt.
- Announce any paid live run with a cost estimate first.
- API keys live only in `.env`; never print them.
- Reply to the owner in Russian.
