/** Spec 011 T120: the Changes screen — engine and registry rows in one list, the card (diff, gates, metrics) and the
 * owner's revert / reject / forbid similar. */
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChangeDetailView, diffRows, watchSeries } from "../ChangeCard";
import { JournalList, fromTo } from "../Changes";
import { JournalChangeDetailSchema, JournalChangeListSchema } from "../schemas";
import { useAdmin } from "../store";
import { json, memoryStorage } from "./helpers";

/** Built from `admin_api._engine_out` / `_registry_out`. */
const ENGINE = {
  id: "ch5",
  origin: "engine",
  created_at: "2026-11-03T10:00:00Z",
  author: "agent:parser_doctor",
  object_kind: "parser",
  object_key: "km77",
  from_version: "km77@v4",
  to_version: "km77@v5",
  status: "watch",
  explanation: "km77 parser v4→v5: table labels changed on 03.11; v5 reproduces 48/50 gold values; shadow yield 0.91 vs 0.42",
  reason: "drift:structure",
  gates: { replay: { verdict: "pass" }, shadow: { verdict: "pass" }, watch: { day: 2, of: 7 } },
  revertible: true,
  rejectable: false,
  closed_at: null,
};
const REGISTRY = {
  id: "rc1",
  origin: "registry",
  created_at: "2026-11-02T08:00:00Z",
  author: "system",
  object_kind: "source",
  object_key: "motor.es",
  from_version: "candidate",
  to_version: "active",
  status: "accepted",
  explanation: "accuracy lower bound 0.87 passed 0.8",
  reason: "promoted",
  gates: null,
  revertible: true,
  rejectable: false,
  closed_at: null,
};
const RULE = {
  ...ENGINE,
  id: "ch7",
  author: "agent:rule_auditor",
  object_kind: "rule",
  object_key: "plausibility.by_powertrain.HEV.max_torque.max",
  from_version: "300",
  to_version: "330",
  status: "shadow",
  explanation: "max raised 300→330: 12 right values were rejected",
  revertible: false,
  rejectable: true,
};

const DETAIL = {
  ...ENGINE,
  diff: [{ op: "replace", path: "/fields/0/label", from: "Potencia", value: "Potencia máxima" }],
  evidence: { snapshots: [{ id: "s1", url: "https://www.km77.com/x" }, "s2"], gold: ["g1"], counts: { pages: 30 } },
  gates: {
    replay: { verdict: "pass", metrics_old: { yield: 0.42, accuracy_lb: 0.9 }, metrics_new: { yield: 0.91, accuracy_lb: 0.93 } },
    shadow: { verdict: "pass", pages: 25 },
    watch: { day: 2, of: 7 },
  },
  metrics_before: { fields_per_page: 2.0 },
  metrics_after: { fields_per_page: 11.0 },
  cost_eur: 0.03,
  reverted_by: null,
  experiment: { phase: "watch", daily: [{ day: "2026-11-04", yield: 0.9 }, { day: "2026-11-05", yield: 0.92 }] },
};

describe("changes schemas and helpers", () => {
  it("engine and registry rows parse into one shape", () => {
    const rows = JournalChangeListSchema.parse([ENGINE, REGISTRY, { ...RULE, new_column: "x", status: "brand_new" }]);
    expect(rows.map((r) => r.origin)).toEqual(["engine", "registry", "engine"]);
    expect(rows[1]!.gates).toBeNull();
    expect(rows[2]).toMatchObject({ status: "brand_new", new_column: "x" });
  });

  it("from → to", () => {
    expect(fromTo(ENGINE)).toBe("km77@v4 → km77@v5");
    expect(fromTo({ from_version: "km77@v1", to_version: "km77@v1" })).toBe("km77@v1");
    expect(fromTo({ from_version: null, to_version: null })).toBe("");
  });

  it("diff rows: JSON patch, {before, after}, {key: [old, new]}", () => {
    expect(diffRows(DETAIL.diff)).toEqual([["replace /fields/0/label", "Potencia", "Potencia máxima"]]);
    expect(diffRows({ before: { status: "candidate", a: 1 }, after: { status: "active", a: 1 } })).toEqual([
      ["status", "candidate", "active"],
    ]);
    expect(diffRows({ status: ["active", "degraded"] })).toEqual([["status", "active", "degraded"]]);
  });

  it("watch series from the experiment's days", () => {
    expect(watchSeries(DETAIL.experiment)).toEqual({ days: ["2026-11-04", "2026-11-05"], series: [{ label: "yield", values: [0.9, 0.92] }] });
    expect(watchSeries(null)).toBeNull();
  });
});

describe("changes fetch layer", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubGlobal("sessionStorage", memoryStorage());
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    useAdmin.setState({ needToken: false, journal: null, journalFilter: {}, openChangeId: null, changeDetail: null, changeError: null });
  });
  afterEach(() => vi.unstubAllGlobals());

  const route = (url: string) =>
    Promise.resolve(json(200, url.includes("/changes?") ? [ENGINE, REGISTRY] : url.endsWith("/engine") ? {} : url.match(/\/changes\/[^/]+$/) ? DETAIL : { ok: true }));

  it("the filters go into the query", async () => {
    fetchMock.mockImplementation(route);
    await useAdmin.getState().setJournalFilter({ origin: "engine", agent: "parser_doctor" });
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/v1/admin/changes?days=30&limit=200&origin=engine&agent=parser_doctor");
    expect(useAdmin.getState().journal).toHaveLength(2);
  });

  it("revert, reject and forbid similar are POSTs on the change", async () => {
    fetchMock.mockImplementation(route);
    useAdmin.setState({ openChangeId: "ch5" });
    expect(await useAdmin.getState().changeAction("ch5", "revert")).toBe(true);
    expect(await useAdmin.getState().changeAction("ch7", "reject")).toBe(true);
    expect(await useAdmin.getState().forbidSimilar("ch5", 30)).toBe(true);
    const posts = fetchMock.mock.calls.filter((c) => (c[1] as RequestInit | undefined)?.method === "POST");
    expect(posts.map((c) => c[0])).toEqual([
      "/api/v1/admin/changes/ch5/revert",
      "/api/v1/admin/changes/ch7/reject",
      "/api/v1/admin/changes/ch5/forbid-similar",
    ]);
    expect(JSON.parse(String((posts[2]![1] as RequestInit).body))).toEqual({ days: 30 });
    expect(useAdmin.getState().changeDetail?.id).toBe("ch5");
  });

  it("a refused revert shows the server's reason on the card", async () => {
    fetchMock.mockResolvedValueOnce(json(409, { detail: "revert the later change of this object first" }));
    expect(await useAdmin.getState().changeAction("ch5", "revert")).toBe(false);
    expect(useAdmin.getState().changeError).toBe("revert the later change of this object first");
  });
});

describe("changes render", () => {
  it("the list: time, origin, status, author, object, from → to, the one-sentence explanation", () => {
    const html = renderToStaticMarkup(<JournalList changes={JournalChangeListSchema.parse([ENGINE, REGISTRY])} onOpen={() => undefined} />);
    expect(html).toContain(">engine<");
    expect(html).toContain(">registry<");
    expect(html).toContain(">watch<");
    expect(html).toContain("by agent:parser_doctor");
    expect(html).toContain("parser: km77");
    expect(html).toContain("km77@v4 → km77@v5");
    expect(html).toContain("v5 reproduces 48/50 gold values");
    expect(html).toContain("candidate → active");
  });

  it("the card: diff, gates with old/new metrics, metrics before/after, evidence, watch chart, actions", () => {
    const html = renderToStaticMarkup(<ChangeDetailView c={JournalChangeDetailSchema.parse(DETAIL)} />);
    expect(html).toContain("replace /fields/0/label");
    expect(html).toContain("Potencia máxima");
    expect(html).toContain(">replay<");
    expect(html).toContain(">0.42<");
    expect(html).toContain(">0.91<");
    expect(html).toContain("pages: 25");
    expect(html).toContain("fields_per_page");
    expect(html).toContain("https://www.km77.com/x");
    expect(html).toContain('aria-label="Watch metrics by day"');
    expect(html).toContain(">Revert<");
    expect(html).not.toContain(">Reject<");
    expect(html).toContain("Forbid similar");
  });

  it("a prompt diff is shown as a unified diff; a change in its gates offers Reject, not Revert", () => {
    const c = JournalChangeDetailSchema.parse({ ...DETAIL, ...RULE, diff: "@@ -1 +1 @@\n-old line\n+new line" });
    const html = renderToStaticMarkup(<ChangeDetailView c={c} />);
    expect(html).toContain('aria-label="Unified diff"');
    expect(html).toMatch(/text-good">\+new line/);
    expect(html).toMatch(/text-bad">-old line/);
    expect(html).toContain(">Reject<");
    expect(html).not.toContain(">Revert<");
  });
});
