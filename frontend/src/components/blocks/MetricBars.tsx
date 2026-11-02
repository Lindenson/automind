import type { BlockOf } from "../../lib/protocol";
import { fmtNum } from "../../lib/util";
import { BlockCard } from "../badges";
import { useCarColor } from "../carColors";
import { GaugeIcon } from "../icons";

export function MetricBars({ b }: { b: BlockOf<"metric_bars"> }) {
  const color = useCarColor();
  return (
    <BlockCard title={b.title} icon={<GaugeIcon />}>
      <div className="grid gap-5 sm:grid-cols-2">
        {b.metrics.map((m) => {
          const nums = m.values
            .map((v) => v.value)
            .filter((x): x is number => x !== null);
          const max = Math.max(...nums, 0) || 1;
          const best =
            nums.length > 1
              ? m.better === "higher"
                ? Math.max(...nums)
                : Math.min(...nums)
              : null;
          return (
            <div key={m.key} className="min-w-0">
              <div className="mb-2 flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{m.label}</span>
                <span className="shrink-0 text-[11px] text-muted">
                  {m.unit} ·{" "}
                  {m.better === "higher"
                    ? "higher is better ↑"
                    : "lower is better ↓"}
                </span>
              </div>
              <div className="space-y-2">
                {m.values.map((v) => {
                  const isBest = best !== null && v.value === best;
                  return (
                    <div key={v.car_id} className="min-w-0">
                      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                        <span className="truncate text-muted">{v.label}</span>
                        {v.value === null ? (
                          <span className="shrink-0 italic text-muted/70">
                            unavailable
                          </span>
                        ) : (
                          <span
                            className={
                              isBest
                                ? "shrink-0 font-semibold text-fg tabular"
                                : "shrink-0 text-fg/80 tabular"
                            }
                          >
                            {fmtNum(v.value, 2)} {m.unit}
                            {isBest && (
                              <span className="ml-1 text-good">★</span>
                            )}
                          </span>
                        )}
                      </div>
                      <div className="h-2.5 overflow-hidden rounded-full bg-panel2">
                        {v.value !== null && (
                          <div
                            className="h-full rounded-full transition-[width] duration-700 ease-out"
                            style={{
                              width: `${Math.max(3, (v.value / max) * 100)}%`,
                              background: color(v.car_id),
                              opacity: isBest || best === null ? 1 : 0.55,
                            }}
                          />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </BlockCard>
  );
}
