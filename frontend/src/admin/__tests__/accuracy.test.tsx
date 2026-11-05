/** Spec 011 T120 (SC-010): the accuracy drill-down reaches the page quote in three clicks — the Accuracy tab, a
 * blamed component, a wrong value — and the engine status strip. */
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DrillView, locate, type DrillState } from "../Accuracy";
import { EngineStrip, age } from "../AdminApp";
import { EngineStatusSchema } from "../schemas";
import { useAdmin } from "../store";
import { json, memoryStorage, plain } from "./helpers";

const QUOTE = "Potencia máxima 140 kW (190 CV) a 4.000 rpm";
const COMPONENT = "parser:km77@v4";

const ACCURACY = {
  days: 30,
  kpi: { wrong_share: 0.06, gold_wrong_share: 0.08, accepted: 400, wrong: 24, baseline: 0.04, baseline_name: "pre-autonomy" },
  by_component: [
    { component: COMPONENT, kind: "parser", key: "km77@v4", wrong: 7, right: 120, acc_lb: 0.9, last_at: "2026-11-04T10:00:00Z" },
    { component: "source:motor.es", kind: "source", key: "motor.es", wrong: 3, right: 50, acc_lb: 0.85 },
  ],
  by_area: [{ area: "specs", accepted: 400, wrong: 24, wrong_share: 0.06, gold_checked: 100, gold_wrong: 8, gold_wrong_share: 0.08, baseline: 0.04 }],
};
const VALUES = [
  {
    signal_id: "sig1",
    variant_id: "v1",
    variant: "SEAT León 1.5 TSI",
    attribute: "max_power",
    ours: 190,
    unit: "kW",
    truth: 140,
    truth_origin: "gold:exact",
    blame_vector: { parser: 1 },
    claim_id: "cl1",
    snapshot_id: "sn1",
    created_at: "2026-11-04T10:00:00Z",
  },
];
const VALUE = {
  claim: { id: "cl1", variant: "SEAT León 1.5 TSI", attribute: "max_power", raw_value: "190", raw_unit: "kW", status: "ACCEPTED" },
  evidence: { url: "https://www.km77.com/coches/seat/leon", domain: "km77.com", source_type: "SPEC_DATABASE" },
  quote: QUOTE,
  snapshot: { id: "sn1", fetched_at: "2026-11-04T09:00:00Z", url: "https://www.km77.com/coches/seat/leon" },
  producer: "reader",
  producer_version: "km77@v4",
  model: null,
  signals: [{ id: "sig1", at: "2026-11-04T10:00:00Z", kind: "gold", verdict: "wrong", component: COMPONENT, weight: 1 }],
};
const PAGE = `Ficha técnica del SEAT León. Motor 1.5 TSI. ${QUOTE}. Par máximo 250 Nm.`;

const drill = (): DrillState => {
  const s = useAdmin.getState();
  return { accuracy: s.accuracy, component: s.component, wrongValues: s.wrongValues, claimId: s.claimId, valueDetail: s.valueDetail, pageText: s.pageText };
};
const view = () =>
  renderToStaticMarkup(
    <DrillView s={drill()} onComponent={() => undefined} onValue={() => undefined} onBack={() => undefined} onTop={() => undefined} />,
  );

describe("accuracy drill-down", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.stubGlobal("sessionStorage", memoryStorage());
    fetchMock = vi.fn((url: string) => {
      if (url.startsWith("/api/v1/admin/accuracy?")) return Promise.resolve(json(200, ACCURACY));
      if (url.includes("/values?")) return Promise.resolve(json(200, VALUES));
      if (url.startsWith("/api/v1/admin/values/")) return Promise.resolve(json(200, VALUE));
      if (url.includes("/snapshots/")) return Promise.resolve(plain(200, PAGE));
      return Promise.resolve(json(404, { detail: "not found" }));
    });
    vi.stubGlobal("fetch", fetchMock);
    useAdmin.setState({ needToken: false, tab: "problems", accuracy: null, component: null, wrongValues: null, claimId: null, valueDetail: null, pageText: null });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("tab → component → value reaches the page and the quote (three clicks)", async () => {
    // click 1: the Accuracy tab shows the KPI against the baseline and the components to blame
    useAdmin.getState().setTab("accuracy");
    await useAdmin.getState().loadAccuracy();
    let html = view();
    expect(html).toContain("6%");
    expect(html).toContain("4%");
    expect(html).toContain("pre-autonomy");
    expect(html).toContain(`>${COMPONENT}</button>`);
    expect(html.indexOf(COMPONENT)).toBeLessThan(html.indexOf("source:motor.es"));

    // click 2: a component lists its wrong values
    await useAdmin.getState().openComponent(COMPONENT);
    expect(fetchMock.mock.calls.at(-1)![0]).toBe("/api/v1/admin/accuracy/parser%3Akm77%40v4/values?days=30");
    html = view();
    expect(html).toContain("SEAT León 1.5 TSI · max_power</button>");
    expect(html).toContain(">190 kW<");
    expect(html).toContain(">140 kW<");

    // click 3: a value shows its source, producer, signals and the page text with the quote highlighted
    await useAdmin.getState().openValue("cl1");
    const urls = fetchMock.mock.calls.map((c) => c[0] as string);
    expect(urls).toContain("/api/v1/admin/values/cl1");
    const textUrl = urls.find((u) => u.includes("/snapshots/"))!;
    expect(textUrl.startsWith("/api/v1/admin/snapshots/sn1/text?around=")).toBe(true);
    expect(new URL(textUrl, "http://x").searchParams.get("around")).toBe(QUOTE);
    html = view();
    expect(html).toContain(`<mark class="rounded bg-warn/30 px-0.5 text-fg">${QUOTE}</mark>`);
    expect(html).toContain("km77.com");
    expect(html).toContain("reader km77@v4");
    expect(html).toContain(">wrong<");
  });

  it("back steps up one level at a time", async () => {
    await useAdmin.getState().openComponent(COMPONENT);
    await useAdmin.getState().openValue("cl1");
    useAdmin.getState().drillBack();
    expect(useAdmin.getState()).toMatchObject({ claimId: null, component: COMPONENT });
    useAdmin.getState().drillBack();
    expect(useAdmin.getState().component).toBeNull();
  });

  it("locate finds the quote whatever the case and spacing", () => {
    expect(locate("abc  POTENCIA   máxima 140 kW xyz", "potencia máxima 140 kW")).toBeNull();
    expect(locate("abc POTENCIA máxima 140 kW xyz", "potencia  máxima 140 kW")).toEqual([4, 26]);
    expect(locate("abc", "")).toBeNull();
  });
});

describe("engine status strip", () => {
  it("worker beat age, open changes, budgets, autonomy", () => {
    const e = EngineStatusSchema.parse({
      worker: { beat_at: "2026-11-05T10:00:00Z", age_s: 42, version: "abc", tasks_running: 1 },
      tasks: { rollup: { queued: 1, running: 0, failed_24h: 0, dead: 0 } },
      budgets_today: { scout: { spent: 0.05, limit: 0.1 }, prefetch: { spent: 0.2, limit: 1 } },
      baseline: null,
      autonomy: false,
      open_changes: 2,
    });
    const html = renderToStaticMarkup(<EngineStrip e={e} />);
    expect(html).toContain("worker beat 42 s ago");
    expect(html).toContain("2 open changes");
    expect(html).toContain("budgets €0.25 / €1.1 today");
    expect(html).toContain("autonomy off");
    const down = renderToStaticMarkup(<EngineStrip e={EngineStatusSchema.parse({ worker: null })} />);
    expect(down).toContain("no worker");
    expect(age(4000)).toBe("67 min");
    expect(age(7200)).toBe("2 h");
  });
});
