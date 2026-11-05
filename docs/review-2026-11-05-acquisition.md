# Review 2026-11-05: compliance with "a self-improving acquisition engine"

External review of commit 652e691 (main after PR #58), accepted by the owner on 2026-11-05. It is the input of
spec 011 "Acquisition engine". Summary of findings (full text was given in the conversation of 2026-11-05):

- **Verdict**: good foundation (pure domain, DB registry, Wilson lower bound, decay, hard limits, change journal,
  import-linter, tests), but the task is not solved: acquisition is not separated from the chat, parsing does not
  improve itself (spec 010 forbade it), there is no improvement/validation/evaluation agent, no basis for
  validation (raw pages, gold values, versions), autonomy off, no discovery, no baseline.
- **P0-1** Spec 010 contradicts the task → constitution 1.3.0: agents change declarative data behind gates.
- **P0-2** No basis for validation: store raw snapshots (`page_snapshots`), record reader/extractor/prompt/model
  versions on every value and attempt, `gold_values` from EEA CO2, EEA OBFCM, RDW, KBA and confirmed challenges;
  acceptance: `replay --reader km77@v2 --since 30d` gives accuracy against gold and yield offline, no network, no LLM.
- **P0-3** Acquisition not separated: `acquisition.api.acquire(variant, kind, need, deadline)`, nodes call only it,
  stages moved to `acquisition/pipeline/<stage>.py` one by one (strangler), import contract without research
  exceptions; acceptance: no search/fetch/extract calls in application/ or orchestration/.
- **P0-4** No worker: compose service `worker`, Postgres queue (`acq_tasks`, SKIP LOCKED); prefetch, roll-ups,
  drift, registry review, discovery, agents, canaries/rollbacks move there; acceptance: stopping `app` does not stop
  background work.
- **P1-1** Score optimises yield, not accuracy: accuracy signals without the user (gold, agreement by family,
  physics checks, replacement); no promotion by yield before a minimum of accuracy signals.
- **P1-2** Parser versions and drift: Pydantic parser specs (v1 from site_readers.yaml), `parsers`,
  `parser_versions`, `parser_daily(fields_per_page, pass_rate, structure_hash)`; 7d vs 30d, structure hash change,
  sharp zero → degraded.
- **P1-3** Agents (small graphs in the worker, daily budgets, data-only levers): scout (discovery), parser doctor,
  rule auditor, extractor tuner, evaluator (changes nothing; owns KPIs, canary decisions, rollbacks). Gate rules:
  one change per object, KPI not worse, guard metrics within tolerance, journal with diff, reason, evidence,
  before/after metrics, one-sentence explanation.
- **P1-4** Blame as a vector (source / relevance / parser-extractor with version / units-sense / fusion); code for
  obvious cases, LLM judge + re-run for disputed ones; update only the blamed component.
- **P1-5** Thompson sampling over Beta(accuracy, yield); measure Serper queries per accepted value.
- **P2** close T059/T067/T075; baseline before `autonomy: true`; admin tabs "Parsers" and "Changes"; incident fixes go
  through the engine, not into research.py.
- **Keep**: registry domain (score, lifecycle, limits, admission), Wilson/decay/priors, the 198-site survey,
  registry_changes + admin revert, insight as the chat-side analytics and code-task source, one import contract per
  layer.
- **Do not**: let LLMs write executable parser code; let agents raise budgets or lift the deny-list; enable
  autonomy before a baseline and user-independent accuracy signals; keep growing research.py.
- **Stages of spec 011**: (1) measurability, (2) separation + worker + prefetch, (3) honest reputation then
  autonomy, (4) parser versions and drift, (5) agents and gates (acceptance: a simulated site redesign is detected,
  a new parser version generated, gated, accepted and journalled in one sentence with numbers, no human), (6) admin
  tabs "Parsers" and "Changes" with drill-down from a KPI drop to the page and quote.
