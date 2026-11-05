/** Spec 010 US4 (T044/T045): zod schemas of the admin REST API (contracts/admin-api.md). */
import { z } from "zod";

/** Issue statuses (data-model `insight_issues.status`); unknown values are kept as plain strings. */
export const STATUSES = ["open", "acknowledged", "fixed", "wontfix", "regression"] as const;
export type KnownStatus = (typeof STATUSES)[number];

const str = z.string().nullish();

/** The proposed fix: `code` (files, direction) or `config` (file, key, suggested value). */
export const FixSchema = z
  .object({
    kind: z.enum(["code", "config"]),
    files: z
      .array(z.string())
      .nullish()
      .transform((v) => v ?? []),
    direction: str,
    config_file: str,
    config_key: str,
    suggested_value: z.unknown().optional(),
  })
  .passthrough();
export type Fix = z.infer<typeof FixSchema>;

/** One line of GET /problems. */
export const ProblemItemSchema = z
  .object({
    id: z.string(),
    rank: z.number().int(),
    title: z.string(),
    component: str,
    status: z.string(),
    impact: z.number(),
    failing_turns_7d: z
      .number()
      .int()
      .nullish()
      .transform((v) => v ?? 0),
    chats_7d: z
      .number()
      .int()
      .nullish()
      .transform((v) => v ?? 0),
    example_chat: str,
    fix: FixSchema.nullish().transform((v) => v ?? null),
  })
  .passthrough();
export type ProblemItem = z.infer<typeof ProblemItemSchema>;
export const ProblemListSchema = z.array(ProblemItemSchema);

const id = z.union([z.string(), z.number()]).nullish();

/** An example: the contract says `chat, turn, quote, url, claim`; the data model says `chat_id, turn_id, …, claim_id`. */
export const ExampleSchema = z.preprocess(
  (x) => {
    if (!x || typeof x !== "object") return x;
    const o = x as Record<string, unknown>;
    return {
      ...o,
      chat_id: o.chat_id ?? o.chat ?? null,
      turn_id: o.turn_id ?? o.turn ?? null,
      claim_id: o.claim_id ?? o.claim ?? null,
    };
  },
  z
    .object({
      chat_id: str,
      turn_id: id,
      quote: str,
      url: str,
      claim_id: id,
    })
    .passthrough(),
);
export type Example = z.infer<typeof ExampleSchema>;

export const DiagnosisSchema = z
  .object({
    summary: str,
    likely_cause: str,
    fix: FixSchema.nullish(),
    verify: str,
  })
  .passthrough();
export type Diagnosis = z.infer<typeof DiagnosisSchema>;

export const HistoryEntrySchema = z
  .object({
    at: str,
    status: z.string(),
    by: str,
    author: str,
    fixed_ref: str,
    note: str,
  })
  .passthrough();
export type HistoryEntry = z.infer<typeof HistoryEntrySchema>;

/** GET /problems/{id}. The status history may come as `history` or `status_history`. */
export const ProblemDetailSchema = z.preprocess(
  (x) => {
    if (!x || typeof x !== "object") return x;
    const o = x as Record<string, unknown>;
    return { ...o, history: o.history ?? o.status_history ?? [] };
  },
  z
    .object({
      id: z.string(),
      title: z.string(),
      component: str,
      key: str,
      status: z.string(),
      impact: z.number().nullish(),
      failing_turns_7d: z.number().nullish(),
      chats_7d: z.number().nullish(),
      count_total: z.number().nullish(),
      count_7d: z.number().nullish(),
      first_seen: str,
      last_seen: str,
      fixed_at: str,
      fixed_ref: str,
      examples: z
        .array(ExampleSchema)
        .nullish()
        .transform((v) => v ?? []),
      diagnosis: DiagnosisSchema.nullish().transform((v) => v ?? null),
      history: z.array(HistoryEntrySchema),
      copy_text: z
        .string()
        .nullish()
        .transform((v) => v ?? ""),
    })
    .passthrough(),
);
export type ProblemDetail = z.infer<typeof ProblemDetailSchema>;

/** PATCH /problems/{id} body. */
export const StatusPatchSchema = z.object({
  status: z.enum(["acknowledged", "fixed", "wontfix", "open"]),
  fixed_ref: z.string().min(1).optional(),
});
export type StatusPatch = z.infer<typeof StatusPatchSchema>;

// --- Sources (spec 010 US7, FR-028; backend/src/automind/api/admin.py `_cap_out`, `_change_out`) ---------------

/** The kinds of data (areas) a source can serve. */
export const AREAS = [
  "specs",
  "price",
  "used_price",
  "maintenance",
  "reliability",
  "reviews",
  "measured",
  "engineering",
  "manufacturer",
  "depreciation",
  "used_issues",
  "incentives",
] as const;
export type Area = (typeof AREAS)[number];

/** Statuses a capability is used in; the rest (blocked, retired) are "not used". */
export const USABLE_STATUSES: readonly string[] = ["active", "candidate", "degraded"];

const num0 = z
  .number()
  .nullish()
  .transform((v) => v ?? 0);
const numNull = z
  .number()
  .nullish()
  .transform((v) => v ?? null);
const bool = z
  .boolean()
  .nullish()
  .transform((v) => v ?? false);
const strOr = (d: string) =>
  z
    .string()
    .nullish()
    .transform((v) => v ?? d);
const record = z
  .record(z.unknown())
  .nullish()
  .transform((v) => v ?? null);

/** One capability (domain × area × market) — `_cap_out`. */
export const CapabilitySchema = z
  .object({
    capability_id: z.string(),
    domain: z.string(),
    market: strOr(""),
    status: z.string(),
    rank: numNull,
    score: num0,
    acc_mean: num0,
    acc_lb: num0,
    yield: num0,
    attempts: num0,
    accepted: num0,
    wrong_w: num0,
    right_w: num0,
    cost_per_value: numNull,
    frozen: bool,
    access: strOr("unknown"),
    source_type: str,
    last_used: str,
  })
  .passthrough();
export type Capability = z.infer<typeof CapabilitySchema>;

/** GET /sources?area=… */
export const SourceListSchema = z
  .object({
    area: z.string(),
    sources: z.array(CapabilitySchema),
    counts: z
      .record(z.number())
      .nullish()
      .transform((v) => v ?? {}),
    autonomy: bool,
  })
  .passthrough();
export type SourceList = z.infer<typeof SourceListSchema>;

/** One registry journal entry — `_change_out`. */
export const ChangeSchema = z
  .object({
    id: z.string(),
    at: str,
    author: str,
    domain: z.string(),
    area: str,
    market: str,
    change: z.string(),
    before: record,
    after: record,
    reason: strOr(""),
    evidence: record,
    held: bool,
    reverted: bool,
    revertible: bool,
    capability_id: str,
  })
  .passthrough();
export type Change = z.infer<typeof ChangeSchema>;
export const ChangeListSchema = z.array(ChangeSchema);

/** A truth signal about one of the source's capabilities. */
export const SignalSchema = z
  .object({
    at: str,
    kind: z.string(),
    verdict: str,
    weight: z.number().nullish(),
    blame: str,
    attribute: str,
    variant_id: id,
  })
  .passthrough();
export type Signal = z.infer<typeof SignalSchema>;

/** The `sources` row as the server sends it (every column). */
export const SourceInfoSchema = z
  .object({
    domain: z.string(),
    source_type: str,
    family: str,
    markets: z
      .array(z.string())
      .nullish()
      .transform((v) => v ?? []),
    languages: z
      .array(z.string())
      .nullish()
      .transform((v) => v ?? []),
    access: strOr("unknown"),
    access_evidence: z
      .record(z.unknown())
      .nullish()
      .transform((v) => v ?? {}),
    checked_at: str,
    next_check_at: str,
    reader: str,
    frozen: bool,
    note: str,
    created_at: str,
  })
  .passthrough();
export type SourceInfo = z.infer<typeof SourceInfoSchema>;

/** GET /sources/{domain} */
export const SourceDetailSchema = z
  .object({
    source: SourceInfoSchema,
    capabilities: z.array(CapabilitySchema),
    changes: z.array(ChangeSchema),
    signals: z
      .array(SignalSchema)
      .nullish()
      .transform((v) => v ?? []),
  })
  .passthrough();
export type SourceDetail = z.infer<typeof SourceDetailSchema>;

// --- Acquisition engine (spec 011 US6, FR-021; backend/src/automind/acquisition/admin_api.py) ----------------------

const anyRecord = z
  .record(z.unknown())
  .nullish()
  .transform((v) => v ?? {});
const EMPTY_WINDOW = { pages: 0, fields_per_page: null, pass_rate: null };

/** Yield and pass rate over a window (`_agg`). */
export const WindowStatsSchema = z
  .object({
    pages: num0,
    fields_per_page: numNull,
    pass_rate: numNull,
  })
  .passthrough();
export type WindowStats = z.infer<typeof WindowStatsSchema>;

export const ParserVersionSchema = z
  .object({
    key: z.string(),
    version: z.number().int().nullish(),
    status: z.string(),
    author: str,
    created_at: str,
    activated_at: str,
    change_id: str,
    degraded_reason: str,
  })
  .passthrough();
export type ParserVersion = z.infer<typeof ParserVersionSchema>;

export const DriftSignalSchema = z
  .object({
    day: str,
    at: str,
    kind: z.string(),
    version: str,
    detail: str,
  })
  .passthrough();
export type DriftSignal = z.infer<typeof DriftSignalSchema>;

export const CanarySchema = z
  .object({
    change_id: z.string(),
    phase: z.string(),
    ends_at: str,
    day: numNull,
    of: numNull,
  })
  .passthrough();
export type Canary = z.infer<typeof CanarySchema>;

const parserFields = {
  reader: z.string(),
  domains: z
    .array(z.string())
    .nullish()
    .transform((v) => v ?? []),
  frozen: bool,
  active: str,
  active_status: str,
  versions: z.array(ParserVersionSchema),
  last_7d: WindowStatsSchema.nullish().transform((v) => v ?? EMPTY_WINDOW),
  spark_30d: z
    .array(z.object({ day: z.string(), fields_per_page: numNull, pass_rate: numNull }).passthrough())
    .nullish()
    .transform((v) => v ?? []),
  baseline_30d: WindowStatsSchema.nullish().transform((v) => v ?? EMPTY_WINDOW),
  drift: DriftSignalSchema.nullish().transform((v) => v ?? null),
  canary: CanarySchema.nullish().transform((v) => v ?? null),
};

/** One line of GET /parsers. */
export const ParserItemSchema = z.object(parserFields).passthrough();
export type ParserItem = z.infer<typeof ParserItemSchema>;
export const ParserListSchema = z.array(ParserItemSchema);

export const ParserDaySchema = z
  .object({
    version_key: z.string(),
    day: z.string(),
    pages: num0,
    fields_per_page: numNull,
    pass_rate: numNull,
    zero_pages: num0,
    structure_hash: str,
    structure_sim: numNull,
  })
  .passthrough();
export type ParserDay = z.infer<typeof ParserDaySchema>;

/** GET /parsers/{reader}: the line plus 60 days of daily metrics, drift signals and each version's spec. */
export const ParserDetailSchema = z
  .object({
    ...parserFields,
    daily: z
      .array(ParserDaySchema)
      .nullish()
      .transform((v) => v ?? []),
    drift_signals: z
      .array(DriftSignalSchema)
      .nullish()
      .transform((v) => v ?? []),
    specs: anyRecord,
  })
  .passthrough();
export type ParserDetail = z.infer<typeof ParserDetailSchema>;

const changeFields = {
  id: z.string(),
  origin: z.string(),
  created_at: str,
  author: str,
  object_kind: z.string(),
  object_key: z.string(),
  from_version: str,
  to_version: str,
  status: z.string(),
  explanation: strOr(""),
  reason: str,
  gates: record,
  revertible: bool,
  rejectable: bool,
};

/** One line of GET /changes: engine (`acq_changes`) and registry (`registry_changes`) rows in one shape. */
export const JournalChangeSchema = z.object(changeFields).passthrough();
export type JournalChange = z.infer<typeof JournalChangeSchema>;
export const JournalChangeListSchema = z.array(JournalChangeSchema);

/** GET /changes/{id}: the line plus diff, evidence, full gates, metrics before/after, cost, experiment. */
export const JournalChangeDetailSchema = z
  .object({
    ...changeFields,
    diff: z.unknown().optional(),
    evidence: anyRecord,
    metrics_before: record,
    metrics_after: record,
    cost_eur: num0,
    reverted_by: str,
    experiment: record,
  })
  .passthrough();
export type JournalChangeDetail = z.infer<typeof JournalChangeDetailSchema>;

export const ComponentRowSchema = z
  .object({
    component: z.string(),
    kind: strOr(""),
    key: strOr(""),
    wrong: num0,
    right: num0,
    acc_lb: numNull,
    last_at: str,
  })
  .passthrough();
export type ComponentRow = z.infer<typeof ComponentRowSchema>;

export const AreaAccuracySchema = z
  .object({
    area: z.string(),
    accepted: num0,
    wrong: num0,
    wrong_share: numNull,
    gold_checked: num0,
    gold_wrong: num0,
    gold_wrong_share: numNull,
    baseline: numNull,
  })
  .passthrough();
export type AreaAccuracy = z.infer<typeof AreaAccuracySchema>;

/** GET /accuracy: the KPI against the baseline, by kind of data, and the components to blame. */
export const AccuracySchema = z
  .object({
    kpi: z
      .object({
        wrong_share: numNull,
        gold_wrong_share: numNull,
        baseline: numNull,
        baseline_name: str,
        accepted: num0,
        wrong: num0,
      })
      .passthrough(),
    by_component: z.array(ComponentRowSchema),
    by_area: z
      .array(AreaAccuracySchema)
      .nullish()
      .transform((v) => v ?? []),
  })
  .passthrough();
export type Accuracy = z.infer<typeof AccuracySchema>;

const scalar = z
  .union([z.number(), z.string(), z.boolean()])
  .nullish()
  .transform((v) => v ?? null);

/** One line of GET /accuracy/{component}/values. */
export const WrongValueSchema = z
  .object({
    signal_id: z.string(),
    variant: str,
    attribute: str,
    ours: scalar,
    unit: str,
    truth: scalar,
    truth_origin: str,
    blame_vector: z
      .record(z.number())
      .nullish()
      .transform((v) => v ?? null),
    claim_id: str,
    snapshot_id: str,
    created_at: str,
  })
  .passthrough();
export type WrongValue = z.infer<typeof WrongValueSchema>;
export const WrongValueListSchema = z.array(WrongValueSchema);

export const ValueSignalSchema = z
  .object({
    id: str,
    at: str,
    kind: z.string(),
    verdict: str,
    component: str,
    weight: z.number().nullish(),
  })
  .passthrough();

/** GET /values/{claim_id} */
export const ValueDetailSchema = z
  .object({
    claim: z
      .object({ id: z.string(), variant: str, attribute: str, raw_value: str, raw_unit: str, status: str })
      .passthrough(),
    evidence: z.object({ url: str, domain: str, source_type: str }).passthrough(),
    quote: strOr(""),
    snapshot: z
      .object({ id: z.string(), fetched_at: str, url: str })
      .passthrough()
      .nullish()
      .transform((v) => v ?? null),
    producer: str,
    producer_version: str,
    model: str,
    signals: z
      .array(ValueSignalSchema)
      .nullish()
      .transform((v) => v ?? []),
  })
  .passthrough();
export type ValueDetail = z.infer<typeof ValueDetailSchema>;

/** GET /engine — the header strip. */
export const EngineStatusSchema = z
  .object({
    worker: z
      .object({ beat_at: str, age_s: numNull, version: str, tasks_running: num0 })
      .passthrough()
      .nullish()
      .transform((v) => v ?? null),
    tasks: z
      .record(z.record(z.number()))
      .nullish()
      .transform((v) => v ?? {}),
    budgets_today: z
      .record(z.object({ spent: num0, limit: numNull }).passthrough())
      .nullish()
      .transform((v) => v ?? {}),
    baseline: z
      .object({ name: str, started_at: str, ended_at: str })
      .passthrough()
      .nullish()
      .transform((v) => v ?? null),
    autonomy: bool,
    open_changes: num0,
  })
  .passthrough();
export type EngineStatus = z.infer<typeof EngineStatusSchema>;
