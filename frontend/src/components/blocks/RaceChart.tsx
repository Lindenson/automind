import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { BlockOf } from "../../lib/protocol";
import { cx, fmtNum } from "../../lib/util";
import { usePrefersDark } from "../../lib/useScheme";
import { BlockCard, CarSwatch, ProvenanceBadge } from "../badges";
import { useCarColor } from "../carColors";
import { FlagIcon } from "../icons";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

type TooltipParam = {
  seriesName: string;
  color: string;
  value: [number, number, number];
};

export function RaceChart({ b }: { b: BlockOf<"race_chart"> }) {
  const color = useCarColor();
  const dark = usePrefersDark();

  const option = useMemo(() => {
    const fg = dark ? "#e6eaf2" : "#111827";
    const muted = dark ? "#8b96aa" : "#5c687c";
    const grid = dark ? "rgba(139,150,170,0.14)" : "rgba(92,104,124,0.16)";
    return {
      animationDuration: 1200,
      textStyle: { fontFamily: "Inter, system-ui, sans-serif" },
      grid: { left: 44, right: 16, top: 40, bottom: 36 },
      legend: {
        top: 0,
        left: 0,
        textStyle: { color: fg, fontSize: 12 },
        icon: "roundRect",
        itemWidth: 14,
        itemHeight: 4,
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: dark ? "#161d2a" : "#ffffff",
        borderColor: dark ? "#283244" : "#dae0ea",
        textStyle: { color: fg, fontSize: 12 },
        axisPointer: {
          type: "line",
          lineStyle: { color: muted, type: "dashed" },
        },
        formatter: (params: TooltipParam[]) => {
          const list = Array.isArray(params) ? params : [params];
          const t = list[0]?.value[0] ?? 0;
          const rows = list
            .map(
              (p) =>
                `<div style="display:flex;gap:8px;align-items:center;justify-content:space-between"><span><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color};margin-right:6px"></span>${escapeHtml(p.seriesName)}</span><b style="font-variant-numeric:tabular-nums">${p.value[1].toFixed(1)} km/h · ${Math.round(p.value[2])} m</b></div>`,
            )
            .join("");
          return `<div style="font-size:11px;color:${muted};margin-bottom:4px">t = ${t.toFixed(2)} s</div>${rows}`;
        },
      },
      xAxis: {
        type: "value",
        name: "time (s)",
        nameLocation: "middle",
        nameGap: 24,
        nameTextStyle: { color: muted, fontSize: 11 },
        min: 0,
        axisLine: { lineStyle: { color: grid } },
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: grid } },
      },
      yAxis: {
        type: "value",
        name: "km/h",
        nameTextStyle: { color: muted, fontSize: 11, align: "right" },
        min: 0,
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: grid } },
      },
      series: b.series.map((s, i) => ({
        name: s.label,
        type: "line",
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 2.5, color: color(s.car_id) },
        itemStyle: { color: color(s.car_id) },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: hexA(color(s.car_id), 0.22) },
            { offset: 1, color: hexA(color(s.car_id), 0) },
          ]),
        },
        data: s.t.map((t, k) => [t, s.v_kmh[k] ?? null, s.s_m[k] ?? null]),
        ...(i === 0
          ? {
              markLine: {
                silent: true,
                symbol: "none",
                lineStyle: { color: muted, type: "dotted", width: 1 },
                label: {
                  color: muted,
                  fontSize: 10,
                  formatter: "100 km/h",
                  position: "insideEndTop",
                },
                data: [{ yAxis: 100 }],
              },
            }
          : {}),
      })),
    };
  }, [b.series, color, dark]);

  const results = [...b.results].sort((a, c) => a.rank - c.rank);

  return (
    <BlockCard
      title={b.title}
      icon={<FlagIcon />}
      right={
        <span className="flex items-center gap-1.5 text-[11px] text-muted">
          <ProvenanceBadge p="SIMULATED_ESTIMATE" />
          Simulated estimate · {b.model_version}
        </span>
      }
    >
      <div className="mb-3 flex flex-wrap gap-1.5">
        <span className="chip">
          {b.settings.surface === "DRY" ? "☀ Dry" : "☂ Wet"} surface
        </span>
        <span className="chip">+{b.settings.extra_load_kg} kg load</span>
        <span className="chip">{b.settings.temperature_c} °C</span>
        <span className="chip">{b.settings.altitude_m} m altitude</span>
        {b.prediction && (
          <span className={b.prediction_correct ? "chip border-good/50 text-good" : "chip border-bad/50 text-bad"}>
            Your pick: {b.results.find((r) => r.car_id === b.prediction)?.label ?? "—"} ·{" "}
            {b.prediction_correct ? "right!" : "not this time"}
          </span>
        )}
      </div>

      {b.series.length > 0 && (
        <div className="-mx-1 h-[260px] sm:h-[320px]">
          <ReactEChartsCore
            echarts={echarts}
            option={option}
            notMerge
            style={{ height: "100%", width: "100%" }}
            opts={{ renderer: "canvas" }}
          />
        </div>
      )}

      {results.length > 0 && (
        <div className="mt-4 overflow-x-auto scroll-thin">
          <table className="w-full min-w-[460px] text-sm">
            <thead>
              <tr className="border-b border-line/60 text-left text-[11px] uppercase tracking-wider text-muted">
                <th className="py-2 pr-2 font-semibold">#</th>
                <th className="py-2 pr-2 font-semibold">Car</th>
                <th className="py-2 pr-2 text-right font-semibold">0–100</th>
                <th className="py-2 pr-2 text-right font-semibold">0–200</th>
                <th className="py-2 pr-2 text-right font-semibold">400 m</th>
                <th className="py-2 text-right font-semibold">v @ 400 m</th>
              </tr>
            </thead>
            <tbody className="tabular">
              {results.map((r) => (
                <tr
                  key={r.car_id}
                  className={cx(
                    "border-b border-line/40 last:border-0",
                    r.rank === 1 && "bg-accent/5",
                  )}
                >
                  <td className="py-2 pr-2">
                    <span
                      className={cx(
                        "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold",
                        r.rank === 1
                          ? "bg-accent text-white"
                          : "bg-panel2 text-muted",
                      )}
                    >
                      {r.rank}
                    </span>
                  </td>
                  <td className="py-2 pr-2">
                    <span className="flex items-center gap-2">
                      <CarSwatch color={color(r.car_id)} />
                      <span className="font-medium">{r.label}</span>
                    </span>
                  </td>
                  <td className="py-2 pr-2 text-right">
                    <div className="font-semibold">
                      {fmtNum(r.t_0_100, 2)} s
                    </div>
                    {r.claimed_0_100 !== null && (
                      <div className="text-[11px] text-muted">
                        claimed {fmtNum(r.claimed_0_100, 1)} s
                      </div>
                    )}
                  </td>
                  <td className="py-2 pr-2 text-right">
                    {r.t_0_200 === null ? (
                      <span className="text-muted/70">—</span>
                    ) : (
                      `${fmtNum(r.t_0_200, 2)} s`
                    )}
                  </td>
                  <td className="py-2 pr-2 text-right font-semibold">
                    {fmtNum(r.t_400m, 2)} s
                  </td>
                  <td className="py-2 text-right">
                    {fmtNum(r.v_400m, 0)} km/h
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {b.excluded.length > 0 && (
        <div className="mt-3 space-y-1 rounded-lg border border-warn/30 bg-warn/5 p-3 text-xs">
          <div className="font-semibold text-warn">Not simulated</div>
          {b.excluded.map((e) => (
            <div key={e.car_id} className="text-muted">
              <span className="font-medium text-fg">{e.label}</span> —{" "}
              {e.reason}
            </div>
          ))}
        </div>
      )}

      {b.assumptions.length > 0 && (
        <details className="group mt-3 rounded-lg border border-line/60 bg-panel2/40">
          <summary className="cursor-pointer select-none list-none px-3 py-2 text-xs font-semibold text-muted hover:text-fg">
            <span className="mr-1 inline-block transition group-open:rotate-90">
              ▸
            </span>
            Model assumptions
          </summary>
          <div className="grid gap-3 px-3 pb-3 sm:grid-cols-2">
            {b.assumptions.map((a) => {
              const label =
                b.series.find((s) => s.car_id === a.car_id)?.label ??
                b.results.find((r) => r.car_id === a.car_id)?.label ??
                a.car_id;
              return (
                <div key={a.car_id} className="min-w-0">
                  <div className="mb-1 flex items-center gap-2 text-xs font-semibold">
                    <CarSwatch color={color(a.car_id)} /> {label}
                  </div>
                  <dl className="space-y-0.5 text-xs">
                    {a.items.map((it) => (
                      <div key={it.name} className="flex justify-between gap-2">
                        <dt className="text-muted">{it.name}</dt>
                        <dd className="tabular text-right">
                          {typeof it.value === "number"
                            ? fmtNum(it.value, 3)
                            : it.value}
                          {it.unit ? ` ${it.unit}` : ""}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              );
            })}
          </div>
        </details>
      )}
    </BlockCard>
  );
}

function hexA(hex: string, a: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1]!, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function escapeHtml(s: string) {
  return s.replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
}
