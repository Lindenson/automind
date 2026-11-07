# Self-check of every spec 012 PR

Copied into the PR body and answered item by item (owner, 2026-11-07, after the challenge.py antipattern). A "no"
blocks the merge or is written down as a named follow-up task in tasks.md, never left silent.

## Machine (the gate)

- [ ] `scripts/check.sh` green; `check_structure.py`: **no NEW entry, and the baseline shrank in every package the PR
      touched** (a touched module leaves with fewer `any`/`doc`/`public`/`ignore`/`lazy` entries, never more)
- [ ] `lint-imports` 11+ kept; no new `ignore_imports` line (rule `exempt`)
- [ ] every package the PR creates or finishes passes `mypy --strict` and joins the strict list in `scripts/check.sh`
      and `pyproject.toml`
- [ ] behaviour diff "differs 0" (run alone, never beside another test run); `check_checkpoints.py` 0 module paths

## Reader (I answer, honestly)

- [ ] **Types**: every public signature I wrote says what goes in and out without `Any`; collaborators are ports
      (Protocols), results are DTOs, closed value sets are `Literal`/`StrEnum`
- [ ] **Storage and errors**: no DB access outside infrastructure; every port call that can fail has its failure named
      in the docstring and handled (propagate / retry / notice), and a test drives one failure path
- [ ] **Shape**: public callables ≤ 40 lines reading as named steps; the decision is a pure domain function with tests
- [ ] **Docs**: each public module, class and callable says what it is and promises (params, result, errors, side
      effects); a reader new to the code can follow the flow from the package docstring
- [ ] **Clarity** (memory "refactoring clarity criterion"): one concept per module, no logic in nodes, no helper
      "somewhere convenient", no flag arguments added, names say what the thing is
- [ ] **Hatches**: each `type: ignore` and lazy import I kept carries its reason on the line
