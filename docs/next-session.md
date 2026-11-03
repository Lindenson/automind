# Next session: where to start

State on 2026-11-03:

- **main** contains specs 002–005, the review fixes (PR #11, ADR-026) and the specs of 006 and 007 (spec only, no plan).
- **Spec 007 — the profile drives the assessment** (`specs/007-profile-assessment/spec.md`) is next. It covers the owner's critique (profile inferred and asked, ownership period, new or used, km, budget; weights from the profile; instant recalculation; verdict per profile), the search recall fix for chat 757cff3d (short favourite queries, empty-result TTL, learned sources), the intake bugs, and the open validation items of the review.
- **Spec 006 — electrified cars** (`specs/006-electrified-cars/spec.md`) follows. It is independent of 007; its energy cost plugs into the ownership period of 007 FR-016.
- `.specify/feature.json` points to 007.

## Steps

1. `git checkout main && git pull`, then `git checkout -b 007-profile-assessment` (the branch name the spec expects; the earlier spec branch was merged).
2. `/speckit-plan` for 007. Plan first the parts that unblock the rest:
   - profile model + statuses;
   - `profile_rules.yaml` + the weight breakdown;
   - fingerprint split + RESCORE;
   - search recall: US5 can ship first as its own PR, it is small and independent.
3. `/speckit-tasks`, `/speckit-analyze`, `/speckit-implement`.
4. After each change:
   - run `scripts/check.sh`;
   - restart dev with `pkill -x automind-api; scripts/dev.sh`;
   - run `scripts/deploy.sh up`.

## Evidence to reuse

- **Chat 757cff3d** (BMW 320d Touring M Sport vs VW Golf Variant R): empty profile, round-0 queries with 0 hits, offered option rejected, F30 chosen. Its replay is the acceptance test for US5, US6 and SC-006/SC-008.
- **Chat 5be54966** (BYD Seal U DM-i vs SEAT Ateca): the 006 incident.
- `docs/review-2026-11-03.md` lists every review finding with its status and the spec that takes it.

## Rules that stay in force

- Never scrape classifieds (deny-list in `backend/config/sources.yaml`).
- Respect robots.txt.
- Announce any paid live run with a cost estimate first.
- API keys live only in `.env`; never print them.
- Reply to the owner in Russian.
