import type { BlockOf } from "../../lib/protocol";
import { fmtNum } from "../../lib/util";
import { AssumptionBadge, BlockCard, CarSwatch } from "../badges";
import { useCarColor } from "../carColors";
import { WrenchIcon } from "../icons";

export function Maintenance({ b }: { b: BlockOf<"maintenance"> }) {
  const color = useCarColor();
  return (
    <BlockCard title={b.title} icon={<WrenchIcon />}>
      <div className="grid gap-3 sm:grid-cols-2">
        {b.items.map((it) => {
          const interval = [
            it.interval_km !== null ? `${fmtNum(it.interval_km, 0)} km` : null,
            it.interval_months !== null ? `${it.interval_months} months` : null,
          ]
            .filter(Boolean)
            .join(" / ");
          return (
            <div
              key={it.car_id}
              className="min-w-0 rounded-xl border border-line/50 bg-panel2/40 p-3"
            >
              <div className="mb-2 flex items-start justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2 text-sm font-semibold">
                  <CarSwatch color={color(it.car_id)} />
                  <span className="truncate">{it.label}</span>
                </span>
                {it.basis === "ASSUMPTION" ? (
                  <AssumptionBadge />
                ) : (
                  <span className="shrink-0 rounded border border-good/30 bg-good/10 px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-good">
                    Sourced
                  </span>
                )}
              </div>
              <dl className="grid grid-cols-2 gap-2">
                <div>
                  <dt className="text-[11px] uppercase tracking-wider text-muted">
                    Service interval
                  </dt>
                  <dd className="tabular text-sm font-medium">
                    {interval || <i className="text-muted/70">unavailable</i>}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] uppercase tracking-wider text-muted">
                    Est. per year
                  </dt>
                  <dd className="tabular font-display text-lg font-semibold">
                    {it.annual_cost_eur !== null ? (
                      `€${fmtNum(it.annual_cost_eur, 0)}`
                    ) : (
                      <i className="text-sm font-normal text-muted/70">
                        unavailable
                      </i>
                    )}
                  </dd>
                </div>
              </dl>
              {it.notes.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-xs text-muted">
                  {it.notes.map((n, i) => (
                    <li key={i} className="flex gap-1.5">
                      <span className="text-accent">•</span>
                      <span>{n}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </BlockCard>
  );
}
