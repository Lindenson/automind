/**
 * Mock flows of the v2 protocol (audit F15, spec 010 T097): the intake card, the case file, the research grid, the
 * verdict report, the "Agreed" entry, a structured car edit, "wrong?" and the error / limit messages. Each flow is a
 * list of timed server messages; the content is invented but passes the zod schemas, so the screens are real UI.
 */
import { GTI, I30N, mockBlocks } from "./data";

export type Step = { delay: number; msg: Record<string, unknown> };

const st = (stage: string, text: string) => ({ type: "status", stage, text });
const now = () => new Date().toISOString();

const OPTIONS = {
  "car#1": { generation: ["Mk7.5"], engine: ["1.5 TSI 150 CV", "2.0 TDI 150 CV"], gearbox: ["manual"], trim: ["Clubsport"] },
  "car#2": { generation: [], engine: ["1.6 T-GDi 204 CV"], gearbox: ["manual"], trim: ["Performance"] },
};

type CarState = { engine: string; gearbox: string; trim: string };
const DEFAULT: Record<string, CarState> = {
  "car#1": { engine: "2.0 TSI 245 CV", gearbox: "dct", trim: "GTI", },
  "car#2": { engine: "2.0 T-GDi 280 CV", gearbox: "dct", trim: "N", },
};

/** The mock's own case: what the user agreed and changed in this tab. */
export class MockCase {
  version = 0;
  confirmed = false;
  cars: Record<string, CarState> = structuredClone(DEFAULT);
  removed = new Set<string>();

  variantLabel(key: string): string {
    const c = this.cars[key]!;
    return `${c.engine} · ${c.gearbox} · ${c.trim} · ${key === "car#1" ? "2020–" : "2021–"}`;
  }

  private car(key: string, id: string, label: string) {
    return {
      key,
      request_text: label,
      make: label.split(" ")[0],
      model: label.split(" ").slice(1, -1).join(" "),
      condition: "NEW",
      variant_id: id,
      label,
      resolution: this.confirmed ? "CONFIRMED" : "PROPOSED",
      variant_label: this.variantLabel(key),
      options: OPTIONS[key as keyof typeof OPTIONS],
    };
  }

  caseFile(changes: string[]): Record<string, unknown> {
    this.version += 1;
    const cars = [this.car("car#1", GTI, "VW Golf GTI Mk8"), this.car("car#2", I30N, "Hyundai i30 N")].filter(
      (c) => !this.removed.has(c.key),
    );
    return {
      type: "case_file",
      version: this.version,
      changes,
      case: {
        persona: "PERFORMANCE",
        usage: ["MOUNTAINS"],
        budget: { max_eur: 45000, intent: "NEW", currency: "EUR", kind: "TOTAL" },
        annual_km: 12000,
        basis: { persona: "INFERRED", annual_km: "ASSUMED" },
        cars,
        profile: { region: "Madrid", climate: "MILD", evidence: { persona: "I want something fun on mountain roads" } },
      },
    };
  }
}

export function intakeFlow(mc: MockCase): Step[] {
  return [
    { delay: 300, msg: st("understanding", "Understanding your message") },
    { delay: 500, msg: mc.caseFile(["car#1 added: Golf GTI", "car#2 added: i30 N", "budget €45 000", "usage: mountains (you said)", "12 000 km/yr (assumed)"]) },
    { delay: 500, msg: st("resolving", "Identifying the exact variants") },
    {
      delay: 600,
      msg: {
        type: "confirm_request",
        request_id: "mock-intake",
        kind: "intake",
        text: "Check what I understood. One tap starts the research (≈ €0.18).",
        options: [{ id: "yes", label: "Yes, research these" }, { id: "stop", label: "Not now" }],
        estimate: { eur: 0.18, cars: 2, areas: ["specs", "reliability", "value_retention"], depth: "STANDARD" },
        card: {
          cars: [
            {
              key: "car#1",
              display_name: "VW Golf GTI Mk8 2.0 TSI 245 CV DSG",
              items: [
                { field: "model", value: "Golf GTI", basis: "STATED" },
                { field: "generation", value: "Mk8", basis: "LOOKED_UP", source: { name: "list of versions", url: null } },
                { field: "engine", value: "2.0 · 245 CV (180 kW)", basis: "LOOKED_UP", options: ["1.5 TSI 150 CV"] },
                { field: "gearbox", value: "dct", basis: "ASSUMED", evidence: "chosen by me: the base version" },
                { field: "condition", value: "new", basis: "ASSUMED" },
              ],
            },
            {
              key: "car#2",
              display_name: "Hyundai i30 N 2.0 T-GDi 280 CV DCT",
              items: [
                { field: "model", value: "i30 N", basis: "STATED" },
                { field: "engine", value: "2.0 · 280 CV (206 kW)", basis: "LOOKED_UP" },
                { field: "year", value: "2021", basis: "STATED", evidence: "a 2021 i30 N" },
              ],
            },
          ],
          profile: [
            { field: "persona", value: "enthusiast: driving and performance", basis: "INFERRED", evidence: "something fun on mountain roads", options: ["family and practical buyer"] },
            { field: "annual_km", value: "12 000 km", basis: "ASSUMED" },
          ],
        },
      },
    },
  ];
}

export function reportFlow(mc: MockCase, firstTime: boolean): Step[] {
  const steps: Step[] = [];
  if (firstTime) {
    mc.confirmed = true;
    steps.push(
      { delay: 200, msg: mc.caseFile(["cars and research confirmed"]) },
      {
        delay: 150,
        msg: {
          type: "agreed",
          message_id: `agreed-${mc.version}`,
          created_at: now(),
          text: "Agreed: VW Golf GTI Mk8; Hyundai i30 N",
          blocks: [
            {
              type: "agreed",
              cars: ["car#1", "car#2"].map((k) => ({
                key: k,
                label: k === "car#1" ? "VW Golf GTI Mk8" : "Hyundai i30 N",
                variant_label: mc.variantLabel(k),
                basis: k === "car#1" ? "ASSUMED" : "STATED",
              })),
            },
          ],
        },
      },
    );
  }
  const cars = [["car#1", "VW Golf GTI Mk8"], ["car#2", "Hyundai i30 N"]].filter(([k]) => !mc.removed.has(k!));
  const areas = ["specs", "reliability", "value_retention"];
  for (const state of ["searching", "reading", "done"] as const)
    for (const [key, car] of cars)
      for (const area of areas)
        steps.push({
          delay: 90,
          msg: {
            type: "progress", car, car_key: key, area, round: 0,
            state: area === "reliability" && key === "car#2" && state === "done" ? "partial" : state,
            accepted: state === "done" ? 4 : null,
          },
        });
  steps.push(
    { delay: 300, msg: st("composing", "Writing the report") },
    { delay: 300, msg: { type: "assistant_message", message_id: `report-${mc.version}`, created_at: now(), text: "The **i30 N** is quicker; the **Golf GTI** is cheaper to keep.", blocks: reportBlocks(mc) } },
  );
  return steps;
}

function reportBlocks(mc: MockCase): Record<string, unknown>[] {
  const keys = ["car#1", "car#2"].filter((k) => !mc.removed.has(k));
  return [
    {
      type: "verdict",
      headline: "Hyundai i30 N for driving fun; Golf GTI if running costs matter more",
      pick_car_id: I30N,
      tie: false,
      reasons: [
        { text: "0–100 km/h in 5.4 s vs 6.3 s (manufacturer figures)", insight_id: "i1" },
        { text: "Golf GTI keeps ~6 % more of its value after 5 years", insight_id: "i2" },
      ],
      trade_off: { text: "the i30 N costs about €600 a year more to run", numbers: [] },
      confidence: "MEDIUM",
      confidence_reason: "reliability of the i30 N is based on one owner survey",
      gaps: ["reliability"],
    },
    {
      type: "case_summary",
      persona: "PERFORMANCE",
      facts: ["budget €45 000", "12 000 km/yr (assumed)"],
      cars: keys.map((k) => ({
        key: k,
        label: k === "car#1" ? "VW Golf GTI Mk8" : "Hyundai i30 N",
        condition: "NEW",
        year: null,
        variant_label: mc.variantLabel(k),
        variant_id: k === "car#1" ? GTI : I30N,
      })),
    },
    {
      type: "data_panel",
      changed: null,
      cars: keys.map((k) => ({
        car_id: k === "car#1" ? GTI : I30N,
        car_key: k,
        label: k === "car#1" ? "VW Golf GTI Mk8" : "Hyundai i30 N",
        values: 24,
        areas: [
          { area: "specs", status: "COMPLETE", reason: null, findable: false },
          { area: "reliability", status: k === "car#2" ? "PARTIAL" : "COMPLETE", reason: k === "car#2" ? "one owner survey, no breakdown statistics" : null, findable: k === "car#2" },
          { area: "value_retention", status: "MISSING", reason: "no used listings of this version yet", findable: true },
        ],
      })),
    },
    ...mockBlocks("performance", false).filter((b) => !["notice", "future_widget"].includes(b.type)),
    { type: "quick_replies", items: [{ id: "q1", label: "What about insurance?", text: "What about insurance?" }] },
  ];
}

export function carEditFlow(mc: MockCase, key: string, field: string, value?: string): Step[] {
  if (field === "remove") mc.removed.add(key);
  else if (field === "engine" || field === "gearbox" || field === "trim") mc.cars[key]![field] = value ?? "";
  const what = field === "remove" ? `${key} removed` : `${key}: ${field.replace("_", " ")} → ${value ?? ""}`;
  return [
    { delay: 200, msg: st("understanding", "Applying your change") },
    { delay: 300, msg: mc.caseFile([what]) },
    ...reportFlow(mc, false),
  ];
}

export function challengeFlow(carId: string, attribute: string): Step[] {
  return [
    {
      delay: 700,
      msg: { type: "challenge_result", outcome: "CORRECTED", attribute, car_id: carId, before: "6.3 s", after: "5.9 s", sources: ["vw.com"] },
    },
  ];
}

export function errorFlow(kind: "error" | "limit"): Step[] {
  return [
    { delay: 300, msg: st("understanding", "Understanding your message") },
    {
      delay: 400,
      msg:
        kind === "limit"
          ? { type: "error", code: "daily_cap", text: "Today's research budget is used up. Questions about cars already researched still work." }
          : { type: "error", text: "Something went wrong on my side. Please try again." },
    },
  ];
}
