/**
 * Known technical issues (FR-036): recurring (≥2 independent sources) vs isolated, severity from
 * fixed rules, sources per issue. "No documented issues found" never means "has no issues".
 */
import type { BlockOf } from "../../lib/protocol";
import { cx } from "../../lib/util";
import { BlockCard, SourcesButton } from "../badges";
import { useCarColor } from "../carColors";
import { WarnIcon } from "../icons";

const SEV: Record<string, string> = {
  HIGH: "border-bad/50 bg-bad/10 text-bad",
  MEDIUM: "border-warn/50 bg-warn/10 text-warn",
  LOW: "border-line text-muted",
};

export function Reliability({ b }: { b: BlockOf<"reliability"> }) {
  const color = useCarColor();
  return (
    <BlockCard title={b.title} icon={<WarnIcon />}>
      <div className="grid gap-3 lg:grid-cols-2">
        {b.cars.map((car) => (
          <div
            key={car.car_id}
            className="rounded-xl border border-line/50 p-3"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span
                className="truncate font-display text-sm font-semibold"
                style={{ color: color(car.car_id) }}
              >
                {car.label}
              </span>
              {!car.minimum_met && (
                <span className="chip shrink-0 text-warn">
                  insufficient data
                </span>
              )}
            </div>
            {car.none_found ? (
              <p className="text-sm text-muted">
                No documented issues found
                {car.minimum_met ? "" : " (few sources)"} — this does not prove
                there are none.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {car.issues.map((i) => (
                  <li key={i.component} className="text-sm">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-medium">{i.component}</span>
                      <span
                        className={cx(
                          "rounded border px-1 text-[10px] uppercase",
                          SEV[i.severity],
                        )}
                      >
                        {i.severity.toLowerCase()}
                      </span>
                      <span
                        className={cx(
                          "rounded border px-1 text-[10px] uppercase",
                          i.recurrence === "RECURRING"
                            ? "border-accent/50 text-accent"
                            : "border-line text-muted",
                        )}
                      >
                        {i.recurrence === "RECURRING"
                          ? "recurring"
                          : "isolated"}
                      </span>
                      {i.age_window && (
                        <span className="text-[11px] text-muted">
                          {i.age_window}
                        </span>
                      )}
                      {i.sources.length > 0 && (
                        <SourcesButton sources={i.sources} />
                      )}
                    </div>
                    <p className="text-xs text-muted">{i.description}</p>
                  </li>
                ))}
              </ul>
            )}
            {car.stats.length > 0 && (
              <ul className="mt-2 border-t border-line/30 pt-2 text-xs text-muted">
                {car.stats.map((s, n) => (
                  <li key={n}>
                    {s.source}: {s.metric} —{" "}
                    <b className="text-fg">{s.value}</b>
                    {s.year ? ` (${s.year})` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </BlockCard>
  );
}
