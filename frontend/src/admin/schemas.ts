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
