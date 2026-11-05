/** Spec 011 T117/T118: small inline SVG charts of the admin page (no chart library): a sparkline and a daily line
 * chart with several series and vertical markers (drift, version switches). Colours come from the theme tokens. */
import { CAR_COLORS } from "../lib/util";

export interface Series {
  label: string;
  /** One value per x position (null: no data that day, the line breaks). */
  values: (number | null)[];
}

export interface Marker {
  /** Index on the x axis. */
  at: number;
  label: string;
  tone: "bad" | "accent";
}

/** Polyline segments of the non-null runs, as SVG path data. */
export function pathOf(values: (number | null)[], x: (i: number) => number, y: (v: number) => number): string {
  let d = "";
  let pen = false;
  values.forEach((v, i) => {
    if (v === null || Number.isNaN(v)) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  });
  return d;
}

function bounds(series: Series[], min0: boolean): [number, number] {
  const all = series.flatMap((s) => s.values).filter((v): v is number => v !== null && !Number.isNaN(v));
  if (all.length === 0) return [0, 1];
  let lo = min0 ? Math.min(0, ...all) : Math.min(...all);
  let hi = Math.max(...all);
  if (hi === lo) {
    hi += 1;
    lo = Math.max(min0 ? 0 : lo - 1, lo - 1);
  }
  return [lo, hi];
}

/** A one-line trend: the last value is dotted. */
export function Sparkline({
  values,
  label,
  width = 96,
  height = 24,
}: {
  values: (number | null)[];
  label: string;
  width?: number;
  height?: number;
}) {
  const [lo, hi] = bounds([{ label, values }], false);
  const n = Math.max(1, values.length - 1);
  const x = (i: number) => 1 + (i / n) * (width - 2);
  const y = (v: number) => height - 2 - ((v - lo) / (hi - lo)) * (height - 4);
  const lastIdx = values.map((v, i) => (v === null ? -1 : i)).reduce((a, b) => Math.max(a, b), -1);
  const last = lastIdx >= 0 ? values[lastIdx] : null;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="text-accent2">
      <title>{label}</title>
      <path d={pathOf(values, x, y)} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
      {last != null && <circle cx={x(lastIdx)} cy={y(last)} r={2} fill="currentColor" />}
    </svg>
  );
}

/** Daily lines of several series on one axis, with dashed vertical markers and a legend. */
export function LineChart({
  days,
  series,
  markers = [],
  label,
  format = (v) => String(v),
  height = 120,
  min0 = true,
}: {
  days: string[];
  series: Series[];
  markers?: Marker[];
  label: string;
  format?: (v: number) => string;
  height?: number;
  min0?: boolean;
}) {
  const width = 600;
  const pad = { l: 40, r: 8, t: 8, b: 18 };
  const [lo, hi] = bounds(series, min0);
  const n = Math.max(1, days.length - 1);
  const x = (i: number) => pad.l + (i / n) * (width - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - lo) / (hi - lo)) * (height - pad.t - pad.b);
  if (days.length === 0) return <p className="text-sm text-muted">No daily metrics.</p>;
  return (
    <figure className="space-y-1">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label={label}
        preserveAspectRatio="none"
      >
        <title>{label}</title>
        <g className="text-muted" fontSize={10} fill="currentColor">
          <text x={pad.l - 4} y={y(hi) + 4} textAnchor="end">
            {format(hi)}
          </text>
          <text x={pad.l - 4} y={y(lo)} textAnchor="end">
            {format(lo)}
          </text>
          <text x={pad.l} y={height - 4}>
            {days[0]}
          </text>
          <text x={width - pad.r} y={height - 4} textAnchor="end">
            {days[days.length - 1]}
          </text>
        </g>
        <line x1={pad.l} x2={width - pad.r} y1={y(lo)} y2={y(lo)} className="stroke-line" strokeWidth={1} />
        {markers.map((m, i) => (
          <line
            key={`m${i}`}
            x1={x(m.at)}
            x2={x(m.at)}
            y1={pad.t}
            y2={height - pad.b}
            className={m.tone === "bad" ? "stroke-bad" : "stroke-accent"}
            strokeDasharray="3 3"
            strokeWidth={1}
            data-marker={m.label}
          >
            <title>{m.label}</title>
          </line>
        ))}
        {series.map((s, i) => (
          <path
            key={s.label}
            d={pathOf(s.values, x, y)}
            fill="none"
            stroke={CAR_COLORS[i % CAR_COLORS.length]}
            strokeWidth={1.75}
            strokeLinejoin="round"
          >
            <title>{s.label}</title>
          </path>
        ))}
      </svg>
      <figcaption className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
        {series.map((s, i) => (
          <span key={s.label} className="inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-0.5 w-3" style={{ background: CAR_COLORS[i % CAR_COLORS.length] }} />
            {s.label}
          </span>
        ))}
        {markers.some((m) => m.tone === "bad") && (
          <span className="inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-3 border-l border-dashed border-bad" /> drift
          </span>
        )}
        {markers.some((m) => m.tone === "accent") && (
          <span className="inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-3 border-l border-dashed border-accent" /> version switch
          </span>
        )}
      </figcaption>
    </figure>
  );
}
