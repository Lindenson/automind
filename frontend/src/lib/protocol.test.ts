import { describe, expect, it } from "vitest";
import { mockBlocks } from "../mock/data";
import { HistorySchema, parseBlocks, parseServerMsg } from "./protocol";

describe("parseBlocks", () => {
  it("accepts every mock block type and drops unknown ones", () => {
    const raw = JSON.parse(JSON.stringify(mockBlocks("performance", false))) as unknown[];
    const blocks = parseBlocks(raw);
    expect(blocks.length).toBe(raw.length - 1);
    expect(new Set(blocks.map((b) => b.type))).toEqual(
      new Set(["spec_table", "metric_bars", "race_chart", "profile_scores", "maintenance", "sources", "notice"]),
    );
  });

  it("drops an invalid known block but keeps the others", () => {
    const blocks = parseBlocks([
      { type: "notice", level: "info", text: "ok" },
      { type: "notice", level: "loud", text: "bad level" },
      { type: "metric_bars" },
      "garbage",
      null,
    ]);
    expect(blocks).toEqual([{ type: "notice", level: "info", text: "ok" }]);
  });

  it("returns [] for non-arrays", () => {
    expect(parseBlocks(undefined)).toEqual([]);
  });
});

describe("parseServerMsg", () => {
  it("parses status with optional car", () => {
    expect(parseServerMsg({ type: "status", stage: "researching", text: "x", car: "Hyundai i30 N" })).toMatchObject({ stage: "researching" });
    expect(parseServerMsg({ type: "status", stage: "cache", text: "x" })).not.toBeNull();
  });
  it("ignores unknown message types and invalid stages", () => {
    expect(parseServerMsg({ type: "telemetry", foo: 1 })).toBeNull();
    expect(parseServerMsg({ type: "status", stage: "sleeping", text: "x" })).toBeNull();
  });
  it("filters blocks inside assistant_message", () => {
    const m = parseServerMsg({
      type: "assistant_message",
      message_id: "m1",
      created_at: "2026-01-01T00:00:00Z",
      text: "hi",
      blocks: [{ type: "future" }, { type: "notice", level: "warning", text: "w" }],
    });
    expect(m?.type === "assistant_message" && m.blocks.length).toBe(1);
  });
});

describe("history", () => {
  it("skips malformed history entries", () => {
    const h = HistorySchema.parse({
      messages: [
        { role: "user", message_id: "1", created_at: "t", text: "q", blocks: [] },
        { role: "system", message_id: "2" },
      ],
    });
    expect(h.messages).toHaveLength(1);
  });
});

describe("mock race data", () => {
  it("is physically plausible", () => {
    const race = mockBlocks("performance", false).find((b) => b.type === "race_chart");
    if (!race || race.type !== "race_chart") throw new Error("no race");
    for (const r of race.results) {
      expect(r.t_0_100).toBeGreaterThan(4.5);
      expect(r.t_0_100).toBeLessThan(7.5);
      expect(r.t_400m).toBeGreaterThan(12.5);
      expect(r.t_400m).toBeLessThan(15.5);
    }
    console.log(race.results.map((r) => `${r.label}: 0-100 ${r.t_0_100}s, 400m ${r.t_400m}s @ ${r.v_400m}`).join("\n"));
  });
});

describe("protocol v2", () => {
  it("accepts the seq/turn_id envelope on v1 messages", () => {
    expect(parseServerMsg({ type: "status", stage: "followup", text: "x", seq: 7, turn_id: "t1", area: "reliability" })).toMatchObject({
      seq: 7,
      area: "reliability",
    });
  });

  it("parses case_file with defaults for missing fields", () => {
    const m = parseServerMsg({
      type: "case_file",
      seq: 3,
      turn_id: "t",
      version: 2,
      case: { persona: "BUYER", cars: [{ key: "car#1", condition: "USED", age_years: 10 }] },
      changes: ["persona: UNKNOWN → BUYER"],
    });
    expect(m?.type).toBe("case_file");
    if (m?.type === "case_file") {
      expect(m.case.annual_km).toBe(15000);
      expect(m.case.cars[0]?.resolution).toBe("UNRESOLVED");
    }
  });

  it("parses confirm_request (variants and cost) and usage", () => {
    expect(
      parseServerMsg({
        type: "confirm_request",
        request_id: "r",
        kind: "variants",
        text: "Which Prado?",
        options: [{ id: "a1", label: "Toyota Land Cruiser Prado 150 (2009–2017)", detail: "used, ~2015" }],
      }),
    ).not.toBeNull();
    expect(
      parseServerMsg({
        type: "confirm_request",
        kind: "cost",
        text: "Run?",
        estimate: { eur: 0.42, cars: 2, areas: ["specs"], depth: "STANDARD" },
      }),
    ).not.toBeNull();
    expect(
      parseServerMsg({ type: "usage", llm_calls: 2, input_tokens: 10, output_tokens: 5, search_calls: 0, cost_eur: 0.003 }),
    ).not.toBeNull();
    expect(parseServerMsg({ type: "turn_cancelled", seq: 9 })).not.toBeNull();
  });

  it("accepts the new block types", () => {
    const blocks = parseBlocks([
      {
        type: "criteria_scores",
        title: "Criteria",
        criteria_version: 1,
        criteria: [{ key: "reliability", label: "Reliability", weight: 30, definition: "d" }],
        cars: [
          {
            car_id: "a",
            label: "A",
            ranked: true,
            total: 71.5,
            coverage: 0.9,
            parts: { reliability: { score: 80, insufficient: false, inputs: ["2 recurring issues"] } },
          },
        ],
        winner_car_id: "a",
        unmapped_wishes: ["nice colour"],
      },
      {
        type: "tco",
        title: "Ownership cost",
        annual_km: 15000,
        cars: [
          {
            car_id: "a",
            label: "A",
            condition: "USED",
            age_years: 10,
            annual_total: 2500,
            five_year_total: 12500,
            items: [
              { kind: "BASE_RESERVE", label: "Base reserve", annual_eur: 850, five_year_eur: 4250, basis: "ASSUMPTION", inputs: ["10–14 y × mid_large"], sources: [] },
            ],
          },
        ],
      },
      { type: "case_summary", persona: "BUYER", facts: ["budget ≤ €40,000"], cars: [{ key: "car#1", label: "A", condition: "NEW", year: null }] },
    ]);
    expect(blocks.map((b) => b.type)).toEqual(["criteria_scores", "tco", "case_summary"]);
  });
});

describe("sources block (spec 003)", () => {
  it("accepts favourite, reader and rejected marks and stays compatible", () => {
    const blocks = parseBlocks([
      {
        type: "sources",
        title: "Sources (1)",
        items: [
          { name: "km77", url: "https://www.km77.com/x", type: "SPEC_DATABASE", retrieved_at: "2026-11-02",
            favourite: true, extracted_by: "READER" },
          { name: "G60 test", url: "https://x/g60", type: "PUBLICATION", retrieved_at: "2026-11-02",
            rejected: { reason: "other generation: G60 (2023–)", other: "G60 (2023–)" } },
          { name: "old", url: "https://y", type: "PUBLICATION", retrieved_at: "2026-11-01" },
        ],
      },
    ]);
    expect(blocks).toHaveLength(1);
    const b = blocks[0] as { items: { rejected?: { reason: string } | null }[] };
    expect(b.items[1]?.rejected?.reason).toContain("G60");
  });
});
