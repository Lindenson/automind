# Quickstart: validating a refactoring step

Every step (one PR) passes all of these before merge. Nothing here changes behaviour; if one fails, the step is
fixed, not the check.

## 1. Gate (every step)

```bash
scripts/check.sh                       # ruff, format, mypy, lint-imports, check_structure, pytest, frontend
cd backend && uv run alembic check     # ORM metadata == migrations (steps that move models)
```
Expected: green; test count not lower than before the step (moved tests are counted, deleted tests only with
deleted dead code).

## 1a. Behaviour diff and checkpoints (every step S3a–S13; R11, R4)

```bash
scripts/refactor/diff_behaviour.py --base origin/main --head HEAD   # goldens + 10–20 recorded chats, byte diff
scripts/check_checkpoints.py --dump backups/checkpoints-latest.sql.gz  # S3a, S6, S15: 0 automind. paths, resume ok
```
Expected: no difference after normalising times and ids; every `ConfirmKind` resumes.

## 1b. Coverage gate (before each restructure step S5–S12)

Branch coverage of the step's modules ≥ 80 % (`coverage-before.txt`); otherwise characterisation tests first.

## 2. Goldens and evaluation (every step touching chat or acquisition logic)

```bash
cd backend && uv run pytest -q tests/golden tests/eval tests/graph
```
Expected outputs of goldens are never edited in this feature.

## 3. Structure ratchet (every step)

```bash
cd backend && uv run python ../scripts/check_structure.py --report
```
Expected: no new violation; the baseline shrinks by the entries this step fixes (they are removed from
`scripts/structure_baseline.txt` in the same PR).

## 4. Live replay (deployed checkpoint steps only — see §6)

Deploy (`scripts/deploy.sh up --monitoring`), then replay the owner's chat ccd5f7d8 (Deepal S09 vs Li L9) with the
driver in the session scratchpad (`docs/next-session.md` §5): the answer, the blocks and the energy line are the
same as before (S09 EREV estimate; L9 "no data"). Show the result to the owner first (memory "show live result
first"). No paid research is started (the chat's data is cached; a replay that would cost money is announced first).

## 5. Readability walk-through (end of feature, SC-001, SC-004)

The owner gets 10 concepts (e.g. "case file delta", "intake card", "fallback when the catalogue has no model",
"CLTC normalisation", "parser spec", "who pays the scout's budget", "confirmation of research cost", "TCO period",
"site admission", "report energy block") and the tree + `docs/architecture.md`; he names the package for each.
Use cases identify, report composition and acquisition job are read from their entry points only.

## 6. Deploy policy and rollback (R15)

- Until the pre-autonomy baseline is closed (2026-11-12): merge to main, **no deploy**.
- After: deploy only S3a, S6, S9, S12, S15; note each deploy in the baseline/changes journal; live replay after
  each.
- Rollback: `git revert <step merge>` → `scripts/deploy.sh up --monitoring` → `check_checkpoints.py` on the
  reverted build → live replay. No schema change exists to roll back; worker task kinds are unchanged strings.
