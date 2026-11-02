/**
 * Zod schemas for the AutoMind chat protocol v2 (specs/002-conversational-mvp/contracts/chat-protocol.md),
 * backward-compatible with the demo protocol v1 (docs/demo-protocol.md).
 * Every incoming WebSocket / REST payload is validated here. Unknown block
 * types and unknown server message types are ignored (forward compatibility).
 */
import { z } from "zod";

export const ProvenanceSchema = z.enum([
  "MANUFACTURER_CLAIM",
  "MEASURED",
  "SOURCED_FACT",
  "DERIVED",
  "SIMULATED_ESTIMATE",
  "ASSUMPTION",
]);
export type Provenance = z.infer<typeof ProvenanceSchema>;

export const ConfidenceSchema = z.enum(["HIGH", "MEDIUM", "LOW"]);
export type Confidence = z.infer<typeof ConfidenceSchema>;

export const SourceRefSchema = z.object({
  name: z.string(),
  url: z.string(),
  type: z.enum(["MANUFACTURER", "INSTRUMENTED_TEST", "PUBLICATION", "ENCYCLOPEDIA", "SPEC_DATABASE"]),
  retrieved_at: z.string(),
  excerpt: z.string().nullish(),
  // spec 003 (FR-012): favourite source, values read from the site's table, or rejected for another variant
  favourite: z.boolean().nullish(),
  extracted_by: z.enum(["READER", "LLM"]).nullish(),
  rejected: z
    .object({ reason: z.string(), other: z.string().nullish() })
    .nullish(),
});
export type SourceRef = z.infer<typeof SourceRefSchema>;

export const CarSchema = z.object({
  id: z.string(),
  label: z.string(),
  powertrain: z.enum(["ICE", "BEV", "HEV", "PHEV", "MHEV"]),
  from_cache: z.boolean(),
  researched_at: z.string(),
});
export type Car = z.infer<typeof CarSchema>;

const SpecValueSchema = z.object({
  car_id: z.string(),
  available: z.boolean(),
  display: z.string().nullable(),
  value: z.union([z.number(), z.string()]).nullable(),
  provenance: ProvenanceSchema.nullable(),
  confidence: ConfidenceSchema.nullable(),
  sources: z.array(SourceRefSchema),
});
export type SpecValue = z.infer<typeof SpecValueSchema>;

export const SpecTableBlockSchema = z.object({
  type: z.literal("spec_table"),
  title: z.string(),
  cars: z.array(CarSchema),
  rows: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      unit: z.string().nullable(),
      values: z.array(SpecValueSchema),
    }),
  ),
});

export const MetricBarsBlockSchema = z.object({
  type: z.literal("metric_bars"),
  title: z.string(),
  metrics: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      unit: z.string(),
      better: z.enum(["higher", "lower"]),
      values: z.array(z.object({ car_id: z.string(), label: z.string(), value: z.number().nullable() })),
    }),
  ),
});

export const RaceChartBlockSchema = z.object({
  type: z.literal("race_chart"),
  title: z.string(),
  prediction: z.string().nullish(),
  prediction_correct: z.boolean().nullish(),
  model_version: z.string(),
  settings: z.object({
    surface: z.enum(["DRY", "WET"]),
    extra_load_kg: z.number(),
    temperature_c: z.number(),
    altitude_m: z.number(),
  }),
  series: z.array(
    z.object({
      car_id: z.string(),
      label: z.string(),
      t: z.array(z.number()),
      v_kmh: z.array(z.number()),
      s_m: z.array(z.number()),
    }),
  ),
  results: z.array(
    z.object({
      car_id: z.string(),
      label: z.string(),
      rank: z.number(),
      t_0_100: z.number(),
      t_0_200: z.number().nullable(),
      t_400m: z.number(),
      v_400m: z.number(),
      claimed_0_100: z.number().nullable(),
    }),
  ),
  excluded: z.array(z.object({ car_id: z.string(), label: z.string(), reason: z.string() })),
  assumptions: z.array(
    z.object({
      car_id: z.string(),
      items: z.array(
        z.object({ name: z.string(), value: z.union([z.number(), z.string()]), unit: z.string().nullable() }),
      ),
    }),
  ),
});

export const ProfileScoresBlockSchema = z.object({
  type: z.literal("profile_scores"),
  title: z.string(),
  profile: z.enum(["performance", "smart_buyer", "tech"]),
  criteria: z.array(z.object({ key: z.string(), label: z.string(), weight: z.number() })),
  scores: z.array(
    z.object({
      car_id: z.string(),
      label: z.string(),
      total: z.number(),
      parts: z.record(z.string(), z.number().nullable()),
    }),
  ),
  winner_car_id: z.string().nullable(),
});

export const MaintenanceBlockSchema = z.object({
  type: z.literal("maintenance"),
  title: z.string(),
  items: z.array(
    z.object({
      car_id: z.string(),
      label: z.string(),
      interval_km: z.number().nullable(),
      interval_months: z.number().nullable(),
      annual_cost_eur: z.number().nullable(),
      basis: z.enum(["SOURCED", "ASSUMPTION"]),
      notes: z.array(z.string()),
    }),
  ),
});

export const SourcesBlockSchema = z.object({
  type: z.literal("sources"),
  title: z.string(),
  items: z.array(SourceRefSchema),
});

export const NoticeBlockSchema = z.object({
  type: z.literal("notice"),
  level: z.enum(["info", "warning"]),
  text: z.string(),
});

export const BasisSchema = z.enum(["SOURCED", "ASSUMPTION"]);
export const PersonaSchema = z.enum(["EXPERT", "PERFORMANCE", "BUYER", "UNKNOWN"]);
export type Persona = z.infer<typeof PersonaSchema>;
export const ConditionSchema = z.enum(["NEW", "USED", "UNKNOWN"]);

export const CaseSummaryBlockSchema = z.object({
  type: z.literal("case_summary"),
  persona: PersonaSchema,
  facts: z.array(z.string()),
  cars: z.array(z.object({ key: z.string(), label: z.string(), condition: ConditionSchema, year: z.number().nullable() })),
});

export const CriteriaScoresBlockSchema = z.object({
  type: z.literal("criteria_scores"),
  title: z.string(),
  criteria_version: z.number(),
  criteria: z.array(z.object({ key: z.string(), label: z.string(), weight: z.number(), definition: z.string() })),
  cars: z.array(
    z.object({
      car_id: z.string(),
      label: z.string(),
      ranked: z.boolean(),
      total: z.number().nullable(),
      coverage: z.number(),
      parts: z.record(
        z.string(),
        z.object({ score: z.number().nullable(), insufficient: z.boolean(), inputs: z.array(z.string()) }),
      ),
    }),
  ),
  winner_car_id: z.string().nullable(),
  unmapped_wishes: z.array(z.string()),
});

export const TcoBlockSchema = z.object({
  type: z.literal("tco"),
  title: z.string(),
  annual_km: z.number(),
  cars: z.array(
    z.object({
      car_id: z.string(),
      label: z.string(),
      condition: z.enum(["NEW", "USED"]),
      age_years: z.number().nullable(),
      annual_total: z.number(),
      five_year_total: z.number(),
      items: z.array(
        z.object({
          kind: z.enum(["MAINTENANCE", "ENERGY", "TYRES", "ROAD_TAX", "BIG_TICKET", "BASE_RESERVE"]),
          label: z.string(),
          annual_eur: z.number().nullable(),
          five_year_eur: z.number().nullable(),
          basis: BasisSchema,
          inputs: z.array(z.string()),
          sources: z.array(SourceRefSchema),
        }),
      ),
    }),
  ),
});

export const ReliabilityBlockSchema = z.object({
  type: z.literal("reliability"),
  title: z.string(),
  cars: z.array(
    z.object({
      car_id: z.string(),
      label: z.string(),
      minimum_met: z.boolean(),
      issues: z.array(
        z.object({
          component: z.string(),
          description: z.string(),
          recurrence: z.enum(["RECURRING", "ISOLATED"]),
          severity: z.enum(["LOW", "MEDIUM", "HIGH"]),
          age_window: z.string().nullable(),
          sources: z.array(SourceRefSchema),
        }),
      ),
      stats: z.array(
        z.object({ source: z.string(), metric: z.string(), value: z.string(), year: z.number().nullable(), url: z.string() }),
      ),
      none_found: z.boolean(),
    }),
  ),
});

const ReviewPointSchema = z.object({
  tag: z.string(),
  text: z.string(),
  recurring: z.boolean(),
  sources: z.array(SourceRefSchema),
});

export const ReviewsBlockSchema = z.object({
  type: z.literal("reviews"),
  title: z.string(),
  cars: z.array(
    z.object({
      car_id: z.string(),
      label: z.string(),
      minimum_met: z.boolean(),
      review_count: z.number(),
      source_count: z.number(),
      pros: z.array(ReviewPointSchema),
      cons: z.array(ReviewPointSchema),
    }),
  ),
});

export const EngineeringBlockSchema = z.object({
  type: z.literal("engineering"),
  title: z.string(),
  cars: z.array(
    z.object({
      car_id: z.string(),
      label: z.string(),
      items: z.array(
        z.object({
          key: z.string(),
          label: z.string(),
          display: z.string(),
          confidence: ConfidenceSchema,
          sources: z.array(SourceRefSchema),
        }),
      ),
    }),
  ),
});

export const ManufacturerBlockSchema = z.object({
  type: z.literal("manufacturer"),
  title: z.string(),
  makes: z.array(
    z.object({
      make: z.string(),
      facts: z.array(
        z.object({
          kind: z.enum(["HISTORY", "KEY_MODEL", "MARKET_POSITION"]),
          text: z.string(),
          sources: z.array(SourceRefSchema),
        }),
      ),
    }),
  ),
});

export const BlockSchema = z.discriminatedUnion("type", [
  SpecTableBlockSchema,
  MetricBarsBlockSchema,
  RaceChartBlockSchema,
  ProfileScoresBlockSchema,
  MaintenanceBlockSchema,
  SourcesBlockSchema,
  NoticeBlockSchema,
  CaseSummaryBlockSchema,
  CriteriaScoresBlockSchema,
  TcoBlockSchema,
  ReliabilityBlockSchema,
  ReviewsBlockSchema,
  EngineeringBlockSchema,
  ManufacturerBlockSchema,
]);
export type Block = z.infer<typeof BlockSchema>;
export type BlockOf<T extends Block["type"]> = Extract<Block, { type: T }>;

const KNOWN_BLOCK_TYPES = new Set<string>(BlockSchema.options.map((o) => o.shape.type.value));

/**
 * Parse a raw block list. Unknown block types are silently dropped; known
 * types that fail validation are dropped with a console warning, so one bad
 * block never hides the rest of the answer.
 */
export function parseBlocks(raw: unknown): Block[] {
  if (!Array.isArray(raw)) return [];
  const out: Block[] = [];
  for (const item of raw) {
    const type = typeof item === "object" && item !== null ? (item as { type?: unknown }).type : undefined;
    if (typeof type !== "string" || !KNOWN_BLOCK_TYPES.has(type)) continue;
    const res = BlockSchema.safeParse(item);
    if (res.success) out.push(res.data);
    else console.warn(`[automind] dropped invalid ${type} block`, res.error.issues);
  }
  return out;
}

/** blocks are validated element-wise via parseBlocks, so they are `unknown` at envelope level */
const RawBlocks = z.array(z.unknown()).default([]).transform(parseBlocks);

export const StageSchema = z.enum([
  "understanding",
  "asking",
  "resolving",
  "cache",
  "researching",
  "searching",
  "reading",
  "relevance",
  "validating",
  "followup",
  "feasibility",
  "estimating",
  "computing",
  "analyzing",
  "composing",
  "done",
]);
export type Stage = z.infer<typeof StageSchema>;

/** v2 envelope: every server message carries a per-chat `seq` and its `turn_id` (both optional for v1). */
const Envelope = {
  seq: z.number().int().optional(),
  turn_id: z.string().nullish(),
};

export const StatusMsgSchema = z.object({
  ...Envelope,
  type: z.literal("status"),
  stage: StageSchema,
  text: z.string(),
  car: z.string().nullish(),
  area: z.string().nullish(),
});
export type StatusMsg = z.infer<typeof StatusMsgSchema>;

export const ActionSchema = z.enum([
  "ANSWER_GENERAL",
  "ASK",
  "CONFIRM_VARIANTS",
  "CONFIRM_COST",
  "RESEARCH",
  "ANSWER_FROM_CONTEXT",
  "REPORT",
]);

export const AssistantMsgSchema = z.object({
  ...Envelope,
  type: z.literal("assistant_message"),
  message_id: z.string(),
  created_at: z.string(),
  text: z.string(),
  blocks: RawBlocks,
  action: ActionSchema.nullish(),
});

export const UserAckSchema = z.object({
  ...Envelope,
  type: z.literal("user_message_ack"),
  message_id: z.string(),
  created_at: z.string(),
});

export const ErrorMsgSchema = z.object({ ...Envelope, type: z.literal("error"), text: z.string() });

/** The case file is rendered by the case panel; its inner shape is validated loosely (data-model §2). */
export const CaseCarSchema = z.object({
  key: z.string(),
  request_text: z.string().default(""),
  condition: ConditionSchema.default("UNKNOWN"),
  year: z.number().nullish(),
  age_years: z.number().nullish(),
  mileage_km: z.number().nullish(),
  variant_id: z.string().nullish(),
  label: z.string().nullish(),
  resolution: z.enum(["UNRESOLVED", "PROPOSED", "CONFIRMED", "AUTO_OK"]).default("UNRESOLVED"),
});
export const CaseSchema = z
  .object({
    persona: PersonaSchema.default("UNKNOWN"),
    usage: z.array(z.string()).default([]),
    budget: z.object({ max_eur: z.number().nullish(), note: z.string().nullish() }).partial().default({}),
    annual_km: z.number().default(15000),
    depth: z.enum(["QUICK", "STANDARD", "DEEP"]).default("STANDARD"),
    priorities: z
      .array(z.object({ criterion: z.string(), strength: z.enum(["LOW", "MEDIUM", "HIGH"]), source: z.string() }))
      .default([]),
    weights: z.record(z.string(), z.number()).default({}),
    weights_overridden: z.boolean().default(false),
    unmapped_wishes: z.array(z.string()).default([]),
    rates_override: z.record(z.string(), z.number().nullish()).default({}),
    cars: z.array(CaseCarSchema).default([]),
  })
  .passthrough();
export type CaseFile = z.infer<typeof CaseSchema>;

export const CaseFileMsgSchema = z.object({
  ...Envelope,
  type: z.literal("case_file"),
  version: z.number(),
  case: CaseSchema,
  changes: z.array(z.string()).default([]),
});

export const ConfirmRequestSchema = z.object({
  ...Envelope,
  type: z.literal("confirm_request"),
  request_id: z.string().optional(),
  kind: z.enum(["variants", "cost", "limit", "feasibility"]),
  text: z.string(),
  options: z.array(z.object({ id: z.string(), label: z.string(), detail: z.string().nullish() })).default([]),
  estimate: z
    .object({ eur: z.number(), cars: z.number(), areas: z.array(z.string()), depth: z.string() })
    .nullish(),
});
export type ConfirmRequest = z.infer<typeof ConfirmRequestSchema>;

export const UsageMsgSchema = z.object({
  ...Envelope,
  type: z.literal("usage"),
  llm_calls: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  search_calls: z.number(),
  cost_eur: z.number(),
});
export type Usage = z.infer<typeof UsageMsgSchema>;

export const TurnCancelledSchema = z.object({ ...Envelope, type: z.literal("turn_cancelled") });

export const ServerMsgSchema = z.discriminatedUnion("type", [
  StatusMsgSchema,
  AssistantMsgSchema,
  UserAckSchema,
  ErrorMsgSchema,
  CaseFileMsgSchema,
  ConfirmRequestSchema,
  UsageMsgSchema,
  TurnCancelledSchema,
]);
export type ServerMsg = z.infer<typeof ServerMsgSchema>;

const KNOWN_MSG_TYPES = new Set<string>(ServerMsgSchema.options.map((o) => o.shape.type.value));

/** Validate one incoming server message. Returns null for unknown or invalid messages. */
export function parseServerMsg(raw: unknown): ServerMsg | null {
  const res = ServerMsgSchema.safeParse(raw);
  if (res.success) return res.data;
  const type = typeof raw === "object" && raw !== null ? (raw as { type?: unknown }).type : undefined;
  if (typeof type === "string" && KNOWN_MSG_TYPES.has(type)) {
    console.warn(`[automind] invalid ${type} message`, res.error.issues);
  }
  return null;
}

export const ChatMessageSchema = z.object({
  turn_id: z.string().nullish(),
  role: z.enum(["user", "assistant"]),
  message_id: z.string(),
  created_at: z.string(),
  text: z.string(),
  blocks: RawBlocks,
});
export type ChatMessage = z.infer<typeof ChatMessageSchema>;

export const HistorySchema = z.object({
  messages: z.array(z.unknown()).transform((items) =>
    items.flatMap((m) => {
      const r = ChatMessageSchema.safeParse(m);
      return r.success ? [r.data] : [];
    }),
  ),
});

export type UserMessageOut = { type: "user_message"; message_id: string; text: string };
export type HelloOut = { type: "hello"; last_seq: number };
export type ConfirmOut = { type: "confirm"; request_id?: string; choice: string; text?: string | null };
export type CancelOut = { type: "cancel"; turn_id?: string | null };
export type ClientMsg = UserMessageOut | HelloOut | ConfirmOut | CancelOut;
