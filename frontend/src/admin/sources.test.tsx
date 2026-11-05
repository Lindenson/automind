/** Spec 010 T069: Sources schemas, fetch calls and static render of the table, change list and source card. */
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { changeLabel } from "./badges";
import { SourceDetailView } from "./SourceCard";
import { AutonomyBanner, ChangeList, SourceTable, StatusCounts } from "./Sources";
import { ChangeListSchema, SourceDetailSchema, SourceListSchema } from "./schemas";
import { useAdmin } from "./store";

/** Built from `_cap_out` in backend/src/automind/api/admin.py. */
const cap = (over: Record<string, unknown>) => ({
  capability_id: "c1",
  domain: "auto-data.net",
  market: "EU",
  status: "active",
  rank: 1,
  score: 0.8123,
  acc_mean: 0.93,
  acc_lb: 0.87,
  yield: 0.6,
  attempts: 120.0,
  accepted: 72.0,
  wrong_w: 1.5,
  right_w: 40.0,
  cost_per_value: 0.0021,
  frozen: false,
  access: "ok",
  source_type: "PUBLICATION",
  last_used: "2026-11-04T10:00:00Z",
  ...over,
});

const LIST = {
  area: "specs",
  sources: [
    cap({}),
    cap({ capability_id: "c2", domain: "newsite.de", market: "DE", status: "candidate", rank: 2, frozen: true, cost_per_value: null }),
    cap({ capability_id: "c3", domain: "mobile.de", status: "blocked", rank: null, access: "classifieds" }),
    cap({ capability_id: "c4", domain: "old.example", status: "retired", rank: null, access: "dead" }),
  ],
  counts: { active: 1, candidate: 1, blocked: 1, retired: 1 },
  autonomy: false,
};

/** Built from `_change_out`. */
const change = (over: Record<string, unknown>) => ({
  id: "ch1",
  at: "2026-11-03T08:30:00Z",
  author: "system",
  domain: "newsite.de",
  area: "specs",
  market: "DE",
  change: "promoted",
  before: { status: "candidate" },
  after: { status: "active", area: "specs", market: "DE" },
  reason: "accuracy lower bound 0.87 passed the 0.8 threshold on 40 checks",
  evidence: { acc_lb: 0.87 },
  held: false,
  reverted: false,
  revertible: true,
  capability_id: "c2",
  ...over,
});

const CHANGES = [
  change({}),
  change({ id: "ch2", change: "demoted", held: true, revertible: false, reason: "yield fell to 0.1" }),
  change({ id: "ch3", change: "added", revertible: false, area: null, market: null, reason: "met in discovery" }),
];

const DETAIL = {
  source: {
    domain: "newsite.de",
    source_type: "PUBLICATION",
    family: "newsite",
    markets: ["DE"],
    languages: ["de"],
    access: "ok",
    access_evidence: { robots: "Allow: /", clause: "<b>Automated</b> access is **permitted**", sample_url: "https://newsite.de/x" },
    checked_at: "2026-10-01T00:00:00Z",
    next_check_at: null,
    reader: null,
    frozen: true,
    note: null,
    created_at: "2026-09-01T00:00:00Z",
  },
  capabilities: [cap({ capability_id: "c2", domain: "newsite.de", rank: null })],
  changes: [change({ change: "frozen", author: "owner", after: { frozen: true, statuses: {} }, capability_id: null })],
  signals: [
    { at: "2026-11-02T00:00:00Z", kind: "challenge", verdict: "wrong", weight: 1.0, blame: "source", attribute: "power_hp", variant_id: 7 },
  ],
};

function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, String(v)),
  };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("sources schemas parse the backend payloads", () => {
  it("GET /sources", () => {
    const l = SourceListSchema.parse({ ...LIST, extra: 1 });
    expect(l.sources).toHaveLength(4);
    expect(l.sources[1]).toMatchObject({ frozen: true, cost_per_value: null, rank: 2 });
    expect(l.counts.active).toBe(1);
    expect(l.autonomy).toBe(false);
  });

  it("lenient on missing optional numbers and extra fields", () => {
    const l = SourceListSchema.parse({ area: "price", sources: [{ capability_id: "x", domain: "a.b", status: "candidate", new_field: true }] });
    expect(l.sources[0]).toMatchObject({ score: 0, acc_lb: 0, rank: null, access: "unknown", frozen: false });
    expect(l.counts).toEqual({});
  });

  it("GET /sources/changes", () => {
    const c = ChangeListSchema.parse(CHANGES);
    expect(c[0]).toMatchObject({ revertible: true, held: false, area: "specs" });
    expect(c[2]!.area).toBeNull();
  });

  it("GET /sources/{domain}", () => {
    const d = SourceDetailSchema.parse(DETAIL);
    expect(d.source.access_evidence.robots).toBe("Allow: /");
    expect(d.signals[0]).toMatchObject({ kind: "challenge", blame: "source" });
  });

  it("change labels: held reads held: frozen, an unfreeze reads unfrozen", () => {
    const [a, b] = ChangeListSchema.parse(CHANGES);
    expect(changeLabel(a!)).toBe("promoted");
    expect(changeLabel(b!)).toBe("held: frozen");
    expect(changeLabel({ change: "frozen", held: false, after: { frozen: false } })).toBe("unfrozen");
  });
});

describe("sources fetch layer", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubGlobal("sessionStorage", memoryStorage());
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    useAdmin.setState({
      needToken: false,
      area: "specs",
      sources: null,
      changes: null,
      sourcesError: null,
      changesError: null,
      revertErrors: {},
      openDomain: null,
      sourceDetail: null,
      sourceError: null,
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("loads the list and the 30-day changes of the area", async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(url.includes("/changes") ? json(200, CHANGES) : json(200, { ...LIST, area: "used_price" })),
    );
    await useAdmin.getState().setArea("used_price");
    const urls = fetchMock.mock.calls.map((c) => c[0] as string).sort();
    expect(urls).toEqual([
      "/api/v1/admin/sources/changes?days=30&area=used_price",
      "/api/v1/admin/sources?area=used_price",
    ]);
    expect(useAdmin.getState().sources?.sources).toHaveLength(4);
    expect(useAdmin.getState().changes).toHaveLength(3);
  });

  it("opens a source card", async () => {
    fetchMock.mockResolvedValue(json(200, DETAIL));
    await useAdmin.getState().openSource("newsite.de");
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/v1/admin/sources/newsite.de");
    expect(useAdmin.getState().sourceDetail?.source.frozen).toBe(true);
  });

  it.each(["freeze", "unfreeze", "block"] as const)("%s is a POST to the source", async (action) => {
    fetchMock.mockImplementation(() => Promise.resolve(json(200, { domain: "newsite.de", change: action })));
    useAdmin.setState({ openDomain: "newsite.de" });
    expect(await useAdmin.getState().sourceAction("newsite.de", action)).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/v1/admin/sources/newsite.de/${action}`);
    expect(init.method).toBe("POST");
  });

  it("revert is a POST; a 409 shows the server's reason on that change", async () => {
    fetchMock.mockResolvedValueOnce(json(409, { detail: "revert the later change of this source first" }));
    expect(await useAdmin.getState().revertChange("ch1")).toBe(false);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/admin/sources/changes/ch1/revert");
    expect(init.method).toBe("POST");
    expect(useAdmin.getState().revertErrors).toEqual({ ch1: "revert the later change of this source first" });

    const c = ChangeListSchema.parse(CHANGES);
    const html = renderToStaticMarkup(
      <ChangeList changes={c} errors={useAdmin.getState().revertErrors} onRevert={() => undefined} />,
    );
    expect(html).toContain("revert the later change of this source first");
  });

  it("a successful revert clears the earlier refusal", async () => {
    useAdmin.setState({ revertErrors: { ch1: "old" } });
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/revert")
          ? json(200, { reverted: "ch1", by: "ch9" })
          : url.includes("/changes")
            ? json(200, CHANGES)
            : json(200, LIST),
      ),
    );
    expect(await useAdmin.getState().revertChange("ch1")).toBe(true);
    expect(useAdmin.getState().revertErrors).toEqual({});
  });
});

describe("sources render", () => {
  const list = SourceListSchema.parse(LIST);

  it("the autonomy banner", () => {
    expect(renderToStaticMarkup(<AutonomyBanner on={false} />)).toContain(
      "the registry records and scores, the configured order is used",
    );
    expect(renderToStaticMarkup(<AutonomyBanner on />)).toContain("Autonomy on");
  });

  it("counts by status", () => {
    const html = renderToStaticMarkup(<StatusCounts counts={list.counts} />);
    expect(html).toContain(">active<");
    expect(html).toContain(">blocked<");
  });

  it("the table: usable rows in rank order, blocked and retired under Not used", () => {
    const html = renderToStaticMarkup(<SourceTable list={list} onOpen={() => undefined} />);
    const [used, unused] = html.split("Not used (2)");
    expect(used).toContain("auto-data.net");
    expect(used).toContain("newsite.de");
    expect(used!.indexOf("auto-data.net")).toBeLessThan(used!.indexOf("newsite.de"));
    expect(used).toContain("87%"); // acc_lb
    expect(used).toContain('title="mean 93%"');
    expect(used).toContain("0.812"); // score
    expect(used).toContain("60%"); // yield
    expect(used).toContain("€0.0021");
    expect(used).toContain("frozen");
    expect(used).not.toContain("mobile.de");
    expect(unused).toContain("mobile.de");
    expect(unused).toContain("classifieds");
    expect(unused).toContain("old.example");
  });

  it("the change list: badge, domain, area/market, reason, revert only when revertible", () => {
    const html = renderToStaticMarkup(<ChangeList changes={ChangeListSchema.parse(CHANGES)} onRevert={() => undefined} />);
    expect(html).toContain(">promoted<");
    expect(html).toContain(">held: frozen<");
    expect(html).toContain("specs / DE");
    expect(html).toContain("accuracy lower bound 0.87 passed the 0.8 threshold on 40 checks");
    expect(html.match(/>Revert</g)).toHaveLength(1);
  });

  it("the source card: evidence as plain text, capabilities, history, signals, actions", () => {
    const html = renderToStaticMarkup(<SourceDetailView detail={SourceDetailSchema.parse(DETAIL)} />);
    expect(html).toContain("&lt;b&gt;Automated&lt;/b&gt; access is **permitted**");
    expect(html).not.toContain("<b>Automated</b>");
    expect(html).toContain("Allow: /");
    expect(html).toContain("Capabilities (1)");
    expect(html).toContain("History (1)");
    expect(html).toContain(">frozen<");
    expect(html).toContain("blame: source");
    expect(html).toContain("Unfreeze");
    expect(html).toContain("Block…");
  });
});
