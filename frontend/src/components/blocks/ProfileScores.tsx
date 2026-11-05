import { useBlockTitle } from "../../i18n";
import type { BlockOf } from "../../lib/protocol";
import { cx, fmtNum } from "../../lib/util";
import { BlockCard } from "../badges";
import { useCarColor } from "../carColors";
import { TrophyIcon } from "../icons";

const PROFILE_LABEL = {
  performance: "Performance / race enthusiast",
  smart_buyer: "Smart buyer",
  tech: "Tech enthusiast",
} as const;

export function ProfileScores({ b }: { b: BlockOf<"profile_scores"> }) {
  const color = useCarColor();
  const sorted = [...b.scores].sort((x, y) => y.total - x.total);
  const totalWeight = b.criteria.reduce((a, c) => a + c.weight, 0) || 1;
  const fmtWeight = (w: number) =>
    totalWeight <= 1.0001
      ? `${Math.round(w * 100)}%`
      : `${Math.round((w / totalWeight) * 100)}%`;

  return (
    <BlockCard
      title={useBlockTitle(b.type, b.title)}
      icon={<TrophyIcon />}
      right={<span className="chip">{PROFILE_LABEL[b.profile]}</span>}
    >
      <div className="space-y-4">
        {sorted.map((s) => {
          const win = s.car_id === b.winner_car_id;
          const c = color(s.car_id);
          return (
            <div
              key={s.car_id}
              className={cx(
                "rounded-xl border p-3 transition",
                win
                  ? "border-accent/60 bg-accent/5 shadow-[0_0_0_1px_rgb(var(--accent)/0.15)]"
                  : "border-line/50",
              )}
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate font-display text-sm font-semibold">
                    {s.label}
                  </span>
                  {win && (
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent-solid px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-on-accent">
                      🏆 Winner
                    </span>
                  )}
                </div>
                <span
                  className="shrink-0 font-display text-2xl font-bold tabular"
                  style={{ color: c }}
                >
                  {fmtNum(s.total, 0)}
                  <span className="text-xs font-medium text-muted">/100</span>
                </span>
              </div>
              <div className="h-3 overflow-hidden rounded-full bg-panel2">
                <div
                  className="h-full rounded-full transition-[width] duration-700 ease-out"
                  style={{
                    width: `${Math.max(0, Math.min(100, s.total))}%`,
                    background: `linear-gradient(90deg, ${c}99, ${c})`,
                  }}
                />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-4">
                {b.criteria.map((cr) => {
                  const v = s.parts[cr.key];
                  return (
                    <div key={cr.key} className="min-w-0">
                      <div className="flex items-baseline justify-between gap-1 text-[11px]">
                        <span className="truncate text-muted">{cr.label}</span>
                        <span className="tabular">
                          {v === null || v === undefined ? (
                            <i className="text-muted">n/a</i>
                          ) : (
                            fmtNum(v, 0)
                          )}
                        </span>
                      </div>
                      <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-panel2">
                        {v !== null && v !== undefined && (
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.max(0, Math.min(100, v))}%`,
                              background: c,
                              opacity: 0.7,
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
      <div className="mt-4 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
        <span className="mr-1 font-semibold uppercase tracking-wider">
          Weights
        </span>
        {b.criteria.map((cr) => (
          <span key={cr.key} className="chip">
            {cr.label} <b className="text-fg">{fmtWeight(cr.weight)}</b>
          </span>
        ))}
      </div>
    </BlockCard>
  );
}
