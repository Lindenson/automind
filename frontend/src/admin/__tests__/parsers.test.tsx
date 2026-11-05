/** Spec 011 T120: the Parsers screen — schemas, the fetch layer (rollback, freeze) and the static render. */
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chartData, ParserDetailView, rollbackTargets } from "../ParserCard";
import { ParserTable } from "../Parsers";
import { ParserDetailSchema, ParserListSchema } from "../schemas";
import { useAdmin } from "../store";
import { json, memoryStorage } from "./helpers";

/** Built from `admin_api._parsers` (contracts/admin-api.md "GET /parsers"). */
const ITEM = {
  reader: "km77",
  domains: ["km77.com"],
  page_type: "spec_table",
  frozen: false,
  active: "km77@v5",
  active_status: "active",
  versions: [
    { key: "km77@v6", version: 6, status: "rejected", author: "agent:parser_doctor", activated_at: null },
    { key: "km77@v5", version: 5, status: "active", author: "agent:parser_doctor", activated_at: "2026-11-03T10:00:00Z", change_id: "ch5" },
    { key: "km77@v4", version: 4, status: "superseded", author: "seed", activated_at: "2026-09-01T00:00:00Z", degraded_reason: "structure changed" },
  ],
  last_7d: { pages: 63, fields_per_page: 8.0, pass_rate: 0.95, zero_pages: 0 },
  spark_30d: [
    { day: "2026-11-01", fields_per_page: 11, pass_rate: 0.96 },
    { day: "2026-11-02", fields_per_page: 2, pass_rate: 0.5 },
    { day: "2026-11-03", fields_per_page: null, pass_rate: null },
    { day: "2026-11-04", fields_per_page: 8, pass_rate: 0.95 },
  ],
  baseline_30d: { pages: 300, fields_per_page: 11.3, pass_rate: 0.96 },
  drift: { day: "2026-11-02", kind: "yield_drop", version: "km77@v5", detail: "km77 parser v5 degraded: fields per page fell" },
  canary: { change_id: "ch5", phase: "watch", ends_at: "2026-11-10T00:00:00Z", day: 2, of: 7 },
  future_field: 1,
};

const DETAIL = {
  ...ITEM,
  daily: [
    { version_key: "km77@v4", day: "2026-11-01", pages: 10, fields_per_page: 11, pass_rate: 0.96, zero_pages: 0, structure_hash: "a", structure_sim: 1 },
    { version_key: "km77@v4", day: "2026-11-02", pages: 10, fields_per_page: 2, pass_rate: 0.5, zero_pages: 3, structure_hash: "b", structure_sim: 0.3 },
    { version_key: "km77@v5", day: "2026-11-03", pages: 9, fields_per_page: 11, pass_rate: 0.98, zero_pages: 0, structure_hash: "b", structure_sim: 0.97 },
  ],
  drift_signals: [
    { day: "2026-11-02", at: "2026-11-02T12:00:00Z", kind: "structure", version: "km77@v4", detail: "km77 parser v4 degraded: structure changed" },
  ],
  specs: { "km77@v5": { reader: "km77", version: 5, fields: [{ attribute: "max_power", label: "Potencia" }] } },
};

describe("parser schemas", () => {
  it("GET /parsers keeps unknown fields and defaults missing windows", () => {
    const [p] = ParserListSchema.parse([ITEM, { reader: "x", versions: [] }]);
    expect(p).toMatchObject({ reader: "km77", active: "km77@v5", future_field: 1 });
    expect(p!.canary).toMatchObject({ phase: "watch", day: 2, of: 7 });
    const bare = ParserListSchema.parse([{ reader: "x", versions: [] }])[0]!;
    expect(bare.last_7d).toEqual({ pages: 0, fields_per_page: null, pass_rate: null });
    expect(bare.drift).toBeNull();
  });

  it("GET /parsers/{reader}", () => {
    const d = ParserDetailSchema.parse(DETAIL);
    expect(d.daily).toHaveLength(3);
    expect(d.drift_signals[0]!.kind).toBe("structure");
    expect(Object.keys(d.specs)).toEqual(["km77@v5"]);
  });

  it("rollback targets: once active, not the running one, never a rejected version", () => {
    expect(rollbackTargets(ParserDetailSchema.parse(DETAIL))).toEqual(["km77@v4"]);
  });

  it("chart data: one series per version, drift and version-switch markers", () => {
    const c = chartData(ParserDetailSchema.parse(DETAIL), "fields_per_page");
    expect(c.days).toEqual(["2026-11-01", "2026-11-02", "2026-11-03"]);
    expect(c.series.map((s) => s.label)).toEqual(["km77@v4", "km77@v5"]);
    expect(c.series[0]!.values).toEqual([11, 2, null]);
    expect(c.markers).toEqual([
      { at: 1, label: "drift structure (km77@v4)", tone: "bad" },
      { at: 2, label: "km77@v5 activated", tone: "accent" },
    ]);
  });
});

describe("parsers fetch layer", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubGlobal("sessionStorage", memoryStorage());
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    useAdmin.setState({ needToken: false, parsers: null, openReader: null, parserDetail: null, parserError: null });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("loads the list and opens a card", async () => {
    fetchMock.mockImplementation((url: string) => Promise.resolve(json(200, url.endsWith("/parsers") ? [ITEM] : DETAIL)));
    await useAdmin.getState().loadParsers();
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/v1/admin/parsers");
    expect(useAdmin.getState().parsers).toHaveLength(1);
    await useAdmin.getState().openParser("km77");
    expect(fetchMock.mock.calls[1]![0]).toBe("/api/v1/admin/parsers/km77");
    expect(useAdmin.getState().parserDetail?.daily).toHaveLength(3);
  });

  it("rollback is a POST with the chosen version; a 409 shows the server's reason", async () => {
    useAdmin.setState({ openReader: "km77" });
    fetchMock.mockResolvedValueOnce(json(409, { detail: "km77@v6 was never active: only a previous version can be restored" }));
    expect(await useAdmin.getState().rollbackParser("km77", "km77@v6")).toBe(false);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/admin/parsers/km77/rollback");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ to: "km77@v6" });
    expect(useAdmin.getState().parserError).toContain("never active");

    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(json(200, url.endsWith("/rollback") ? { active: "km77@v4" } : url.endsWith("/parsers") ? [ITEM] : DETAIL)),
    );
    expect(await useAdmin.getState().rollbackParser("km77", "km77@v4")).toBe(true);
    expect(useAdmin.getState().parserError).toBeNull();
  });

  it.each(["freeze", "unfreeze"] as const)("%s is a POST to the parser", async (action) => {
    fetchMock.mockImplementation(() => Promise.resolve(json(200, DETAIL)));
    expect(await useAdmin.getState().parserAction("km77", action)).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/v1/admin/parsers/km77/${action}`);
    expect(init.method).toBe("POST");
  });

  it("a 403 asks for the token", async () => {
    fetchMock.mockResolvedValue(json(403, { detail: "forbidden" }));
    await useAdmin.getState().loadParsers();
    expect(useAdmin.getState().needToken).toBe(true);
  });
});

describe("parsers render", () => {
  it("the table: active version, status, 7d vs 30d with the drop in red, drift, canary", () => {
    const html = renderToStaticMarkup(<ParserTable rows={ParserListSchema.parse([ITEM])} onOpen={() => undefined} />);
    expect(html).toContain(">km77<");
    expect(html).toContain("km77@v5");
    expect(html).toContain(">active<");
    expect(html).toMatch(/text-bad">8</); // 8.0 fields per page vs 11.3: a drop
    expect(html).toContain(" / 11.3");
    expect(html).toContain("95%");
    expect(html).toContain("drift: yield drop");
    expect(html).toContain('aria-label="km77: fields per page, 30 days"');
    expect(html.match(/<path d="M[^"]*"/)![0]).toMatch(/^<path d="M[\d.,]+L[\d.,]+M[\d.,]+"$/); // a gap breaks the line
    expect(html).toContain("watch 2/7");
  });

  it("the card: charts with markers, versions, drift signals, specs, rollback to a previous version", () => {
    const d = ParserDetailSchema.parse({ ...DETAIL, frozen: true });
    const html = renderToStaticMarkup(<ParserDetailView detail={d} />);
    expect(html).toContain('aria-label="Fields per page by version"');
    expect(html).toContain('data-marker="drift structure (km77@v4)"');
    expect(html).toContain('data-marker="km77@v5 activated"');
    expect(html).toContain("km77 parser v4 degraded: structure changed");
    expect(html).toContain("&quot;label&quot;: &quot;Potencia&quot;");
    expect(html).toContain('<option value="km77@v4"');
    expect(html).not.toContain('<option value="km77@v6"');
    expect(html).toContain("Roll back");
    expect(html).toContain("Unfreeze");
  });
});
