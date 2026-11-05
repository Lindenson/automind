import type { Block, SourceRef } from "../lib/protocol";
import { simulate, timeToSpeed, type MockCarPhysics } from "./race";

export const GTI = "vw-golf-gti-mk8";
export const I30N = "hyundai-i30-n-2021";
const GTI_LABEL = "VW Golf GTI Mk8 (2020–)";
const I30N_LABEL = "Hyundai i30 N (2021–)";

const S = {
  vw: {
    name: "Volkswagen UK — Golf GTI technical data",
    url: "https://www.volkswagen.co.uk/en/new/golf-gti.html",
    type: "MANUFACTURER",
    retrieved_at: "2026-10-31T09:12:00Z",
    excerpt: "2.0 TSI 245 PS 7-speed DSG … 0–62 mph 6.2 s, top speed 155 mph (limited).",
  },
  hyundai: {
    name: "Hyundai Newsroom — New i30 N specifications",
    url: "https://www.hyundai.news/eu/articles/press-releases/new-i30-n.html",
    type: "MANUFACTURER",
    retrieved_at: "2026-10-31T09:13:30Z",
    excerpt: "2.0 T-GDi 280 PS, 392 Nm, 8-speed wet DCT … 0-100 km/h in 5.4 seconds.",
  },
  caranddriver: {
    name: "Car and Driver — 2022 VW GTI instrumented test",
    url: "https://www.caranddriver.com/volkswagen/gti-2022",
    type: "INSTRUMENTED_TEST",
    retrieved_at: "2026-10-31T09:14:10Z",
    excerpt: "Zero to 60 mph: 5.1 sec … 1/4-mile: 13.7 sec @ 102 mph. Curb weight: 3,170 lb (DCT).",
  },
  autoexpress: {
    name: "Auto Express — Hyundai i30 N review",
    url: "https://www.autoexpress.co.uk/hyundai/i30/i30-n",
    type: "PUBLICATION",
    retrieved_at: "2026-10-31T09:15:02Z",
    excerpt: "Kerb weight is 1,509 kg for the DCT car … servicing every 10,000 miles or annually.",
  },
  wiki_gti: {
    name: "Wikipedia — Volkswagen Golf Mk8",
    url: "https://en.wikipedia.org/wiki/Volkswagen_Golf_Mk8",
    type: "ENCYCLOPEDIA",
    retrieved_at: "2026-10-31T09:12:40Z",
    excerpt: "GTI: 2.0 L EA888 evo4 turbocharged I4, 180 kW (245 PS), 370 N⋅m.",
  },
  ultimatespecs: {
    name: "Ultimate Specs — Hyundai i30 N 2.0 T-GDi DCT",
    url: "https://www.ultimatespecs.com/car-specs/Hyundai/i30-N",
    type: "SPEC_DATABASE",
    retrieved_at: "2026-10-31T09:15:40Z",
    excerpt: "Displacement 1998 cm3 · Top speed 250 km/h · Drag coefficient 0.32",
  },
} satisfies Record<string, SourceRef>;

const PHYS: MockCarPhysics[] = [
  {
    car_id: GTI,
    label: GTI_LABEL,
    power_kw: 180,
    mass_kg: 1463 + 75,
    cd_a: 0.3 * 2.2,
    crr: 0.012,
    drive_eff: 0.86,
    traction_g: 0.62,
    shift_loss_s: 0.12,
    shift_speeds_kmh: [58, 98, 140],
  },
  {
    car_id: I30N,
    label: I30N_LABEL,
    power_kw: 206,
    mass_kg: 1509 + 75,
    cd_a: 0.32 * 2.23,
    crr: 0.012,
    drive_eff: 0.86,
    traction_g: 0.64,
    shift_loss_s: 0.1,
    shift_speeds_kmh: [55, 92, 132],
  },
];

const series = PHYS.map((p) => simulate(p));
const claimed: Record<string, number> = { [GTI]: 6.3, [I30N]: 5.4 };

const results = series
  .map((sr) => ({
    car_id: sr.car_id,
    label: sr.label,
    rank: 0,
    t_0_100: timeToSpeed(sr, 100) ?? 0,
    t_0_200: timeToSpeed(sr, 200),
    t_400m: sr.t[sr.t.length - 1]!,
    v_400m: sr.v_kmh[sr.v_kmh.length - 1]!,
    claimed_0_100: claimed[sr.car_id] ?? null,
  }))
  .sort((a, b) => a.t_400m - b.t_400m)
  .map((r, i) => ({ ...r, rank: i + 1 }));

const cars = (fromCache: boolean) => [
  { id: GTI, label: GTI_LABEL, powertrain: "ICE" as const, from_cache: fromCache, researched_at: "2026-10-31T09:14:10Z" },
  { id: I30N, label: I30N_LABEL, powertrain: "ICE" as const, from_cache: fromCache, researched_at: "2026-10-31T09:15:40Z" },
];

function specTable(fromCache: boolean): Block {
  return {
    type: "spec_table",
    title: "Key specifications",
    cars: cars(fromCache),
    rows: [
      {
        key: "power",
        label: "Max power",
        unit: "kW",
        values: [
          { car_id: GTI, available: true, display: "180 kW (245 PS)", value: 180, provenance: "MANUFACTURER_CLAIM", confidence: "HIGH", sources: [S.vw, S.wiki_gti] },
          { car_id: I30N, available: true, display: "206 kW (280 PS)", value: 206, provenance: "MANUFACTURER_CLAIM", confidence: "HIGH", sources: [S.hyundai] },
        ],
      },
      {
        key: "torque",
        label: "Max torque",
        unit: "Nm",
        values: [
          { car_id: GTI, available: true, display: "370 Nm", value: 370, provenance: "MANUFACTURER_CLAIM", confidence: "HIGH", sources: [S.wiki_gti] },
          { car_id: I30N, available: true, display: "392 Nm", value: 392, provenance: "MANUFACTURER_CLAIM", confidence: "HIGH", sources: [S.hyundai] },
        ],
      },
      {
        key: "engine",
        label: "Engine",
        unit: null,
        values: [
          { car_id: GTI, available: true, display: "2.0 L turbo I4 (EA888 evo4)", value: "2.0 TSI", provenance: "SOURCED_FACT", confidence: "HIGH", sources: [S.wiki_gti] },
          { car_id: I30N, available: true, display: "2.0 L turbo I4 (Theta II T-GDi)", value: "2.0 T-GDi", provenance: "SOURCED_FACT", confidence: "HIGH", sources: [S.ultimatespecs] },
        ],
      },
      {
        key: "transmission",
        label: "Gearbox / drive",
        unit: null,
        values: [
          { car_id: GTI, available: true, display: "7-speed DSG · FWD", value: "DSG7", provenance: "MANUFACTURER_CLAIM", confidence: "HIGH", sources: [S.vw] },
          { car_id: I30N, available: true, display: "8-speed wet DCT · FWD", value: "DCT8", provenance: "MANUFACTURER_CLAIM", confidence: "HIGH", sources: [S.hyundai] },
        ],
      },
      {
        key: "kerb_weight",
        label: "Kerb weight",
        unit: "kg",
        values: [
          { car_id: GTI, available: true, display: "1,463 kg", value: 1463, provenance: "MEASURED", confidence: "MEDIUM", sources: [S.caranddriver] },
          { car_id: I30N, available: true, display: "1,509 kg", value: 1509, provenance: "SOURCED_FACT", confidence: "MEDIUM", sources: [S.autoexpress] },
        ],
      },
      {
        key: "acc_0_100",
        label: "0–100 km/h (claimed)",
        unit: "s",
        values: [
          { car_id: GTI, available: true, display: "6.3 s", value: 6.3, provenance: "MANUFACTURER_CLAIM", confidence: "HIGH", sources: [S.vw] },
          { car_id: I30N, available: true, display: "5.4 s", value: 5.4, provenance: "MANUFACTURER_CLAIM", confidence: "HIGH", sources: [S.hyundai] },
        ],
      },
      {
        key: "top_speed",
        label: "Top speed",
        unit: "km/h",
        values: [
          { car_id: GTI, available: true, display: "250 km/h (limited)", value: 250, provenance: "MANUFACTURER_CLAIM", confidence: "HIGH", sources: [S.vw] },
          { car_id: I30N, available: true, display: "250 km/h", value: 250, provenance: "SOURCED_FACT", confidence: "MEDIUM", sources: [S.ultimatespecs] },
        ],
      },
      {
        key: "power_to_weight",
        label: "Power-to-weight",
        unit: "kW/t",
        values: [
          { car_id: GTI, available: true, display: "123 kW/t", value: 123.0, provenance: "DERIVED", confidence: "MEDIUM", sources: [] },
          { car_id: I30N, available: true, display: "136.5 kW/t", value: 136.5, provenance: "DERIVED", confidence: "MEDIUM", sources: [] },
        ],
      },
      {
        key: "price_es",
        label: "Official price (ES)",
        unit: "EUR",
        values: [
          { car_id: GTI, available: true, display: "≈ €44,900", value: 44900, provenance: "SOURCED_FACT", confidence: "LOW", sources: [S.wiki_gti] },
          { car_id: I30N, available: false, display: null, value: null, provenance: null, confidence: null, sources: [] },
        ],
      },
    ],
  };
}

const metricBars: Block = {
  type: "metric_bars",
  title: "Performance metrics",
  metrics: [
    {
      key: "power_to_weight",
      label: "Power-to-weight",
      unit: "kW/t",
      better: "higher",
      values: [
        { car_id: GTI, label: GTI_LABEL, value: 123.0 },
        { car_id: I30N, label: I30N_LABEL, value: 136.5 },
      ],
    },
    {
      key: "torque_to_weight",
      label: "Torque-to-weight",
      unit: "Nm/t",
      better: "higher",
      values: [
        { car_id: GTI, label: GTI_LABEL, value: 252.9 },
        { car_id: I30N, label: I30N_LABEL, value: 259.8 },
      ],
    },
    {
      key: "kg_per_kw",
      label: "Weight per kW",
      unit: "kg/kW",
      better: "lower",
      values: [
        { car_id: GTI, label: GTI_LABEL, value: 8.13 },
        { car_id: I30N, label: I30N_LABEL, value: 7.33 },
      ],
    },
    {
      key: "measured_0_100",
      label: "0–100 km/h (measured)",
      unit: "s",
      better: "lower",
      values: [
        { car_id: GTI, label: GTI_LABEL, value: 5.6 },
        { car_id: I30N, label: I30N_LABEL, value: null },
      ],
    },
  ],
};

const raceChart: Block = {
  type: "race_chart",
  title: "Drag race · standing start to 400 m",
  model_version: "drag-sim v0.1",
  settings: { surface: "DRY", extra_load_kg: 75, temperature_c: 20, altitude_m: 0 },
  series,
  results,
  excluded: [],
  assumptions: PHYS.map((p) => ({
    car_id: p.car_id,
    items: [
      { name: "Test mass (kerb + driver)", value: p.mass_kg, unit: "kg" },
      { name: "Drag area Cd·A", value: Math.round(p.cd_a * 1000) / 1000, unit: "m²" },
      { name: "Drivetrain efficiency", value: p.drive_eff, unit: null },
      { name: "Launch grip (FWD)", value: p.traction_g, unit: "g" },
      { name: "Shift time", value: p.shift_loss_s, unit: "s" },
    ],
  })),
};

function profileScores(profile: "performance" | "smart_buyer"): Block {
  if (profile === "smart_buyer") {
    return {
      type: "profile_scores",
      title: "Smart buyer score",
      profile: "smart_buyer",
      criteria: [
        { key: "running_costs", label: "Running costs", weight: 0.3 },
        { key: "practicality", label: "Practicality", weight: 0.25 },
        { key: "price", label: "Price", weight: 0.25 },
        { key: "reliability", label: "Reliability", weight: 0.2 },
      ],
      scores: [
        { car_id: GTI, label: GTI_LABEL, total: 71, parts: { running_costs: 74, practicality: 78, price: 62, reliability: 70 } },
        { car_id: I30N, label: I30N_LABEL, total: 64, parts: { running_costs: 70, practicality: 72, price: null, reliability: 76 } },
      ],
      winner_car_id: GTI,
    };
  }
  return {
    type: "profile_scores",
    title: "Race enthusiast score",
    profile: "performance",
    criteria: [
      { key: "acceleration", label: "Acceleration", weight: 0.35 },
      { key: "power_to_weight", label: "Power-to-weight", weight: 0.25 },
      { key: "drag_race", label: "Drag race", weight: 0.25 },
      { key: "top_speed", label: "Top speed", weight: 0.15 },
    ],
    scores: [
      { car_id: GTI, label: GTI_LABEL, total: 72, parts: { acceleration: 68, power_to_weight: 70, drag_race: 74, top_speed: 82 } },
      { car_id: I30N, label: I30N_LABEL, total: 84, parts: { acceleration: 86, power_to_weight: 82, drag_race: 85, top_speed: 82 } },
    ],
    winner_car_id: I30N,
  };
}

const maintenance: Block = {
  type: "maintenance",
  title: "Maintenance estimate",
  items: [
    {
      car_id: GTI,
      label: GTI_LABEL,
      interval_km: 30000,
      interval_months: 24,
      annual_cost_eur: 520,
      basis: "ASSUMPTION",
      notes: ["Flexible (LongLife) service regime assumed", "Labour rate €85/h, ES dealer average (assumed)"],
    },
    {
      car_id: I30N,
      label: I30N_LABEL,
      interval_km: 15000,
      interval_months: 12,
      annual_cost_eur: 610,
      basis: "SOURCED",
      notes: ["Interval from Auto Express review (10,000 mi / 12 months)", "Annual cost assumes 15,000 km/year"],
    },
  ],
};

const sources: Block = {
  type: "sources",
  title: "Sources",
  items: Object.values(S),
};

export type MockProfile = "performance" | "smart_buyer";

export function mockBlocks(profile: MockProfile, fromCache: boolean): Block[] {
  return [
    {
      type: "notice",
      level: "info",
      text: fromCache
        ? "Both cars were served from the cache (researched 2026-10-31) — no new web search was needed."
        : "Resolved variants: VW Golf GTI Mk8 2.0 TSI DSG (2020–) and Hyundai i30 N 2.0 T-GDi DCT (2021 facelift).",
    },
    specTable(fromCache),
    metricBars,
    raceChart,
    profileScores(profile),
    maintenance,
    {
      type: "notice",
      level: "warning",
      text: "The official Spanish price of the i30 N could not be verified — Hyundai withdrew the N line from the ES configurator. Price-dependent scores exclude it.",
    },
    sources,
    // Forward-compatibility check: unknown block types must be ignored by the UI.
    { type: "future_widget", payload: 42 } as unknown as Block,
  ];
}

const gtiRes = results.find((r) => r.car_id === GTI)!;
const i30Res = results.find((r) => r.car_id === I30N)!;

export function mockText(profile: MockProfile): string {
  if (profile === "smart_buyer") {
    return `For a **smart buyer** the picture flips: the **Golf GTI Mk8** wins on overall value.

- **Running costs** — VW's flexible service interval (up to 30,000 km / 2 years) keeps the estimated yearly bill around **€520**, but note this figure is an *assumption*, not a sourced quote.
- **Practicality** — near-identical boots, but the Golf's cabin tech and resale network give it the edge.
- **Price** — the i30 N's official ES price is *unavailable*, so its price score is excluded.

> Both cars came straight from the cache — no new research was run.`;
  }
  return `For a **race enthusiast**, the **Hyundai i30 N** is the stronger pick.

1. **More power, more grip** — 206 kW vs 180 kW gives the i30 N roughly **11 % better power-to-weight** (136.5 vs 123 kW/t), despite being ~46 kg heavier.
2. **Drag race** — in our simulation the i30 N reaches 100 km/h in **${i30Res.t_0_100.toFixed(1)} s** and covers 400 m in **${i30Res.t_400m.toFixed(1)} s**, versus ${gtiRes.t_0_100.toFixed(1)} s / ${gtiRes.t_400m.toFixed(1)} s for the GTI.
3. **The GTI fights back** on refinement and everyday comfort, and its measured 0–100 (5.6 s, Car and Driver) beats VW's own conservative claim.

| | Golf GTI Mk8 | i30 N |
|---|---|---|
| Power | 180 kW | 206 kW |
| 400 m (sim) | ${gtiRes.t_400m.toFixed(2)} s | ${i30Res.t_400m.toFixed(2)} s |

*Simulated values are estimates from \`drag-sim v0.1\`, not measurements.*`;
}
