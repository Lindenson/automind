/** Tier 2 engineering details per car with confidence and sources (expert persona). */
import type { BlockOf } from "../../lib/protocol";
import { BlockCard, ConfidenceDot, SourcesButton } from "../badges";
import { useCarColor } from "../carColors";
import { WrenchIcon } from "../icons";

export function Engineering({ b }: { b: BlockOf<"engineering"> }) {
  const color = useCarColor();
  return (
    <BlockCard title={b.title} icon={<WrenchIcon />}>
      <div className="grid gap-3 sm:grid-cols-2">
        {b.cars.map((car) => (
          <div
            key={car.car_id}
            className="rounded-xl border border-line/50 p-3"
          >
            <div
              className="mb-2 font-display text-sm font-semibold"
              style={{ color: color(car.car_id) }}
            >
              {car.label}
            </div>
            {car.items.length === 0 ? (
              <p className="text-xs text-muted">
                No engineering details documented.
              </p>
            ) : (
              <dl className="space-y-1 text-xs">
                {car.items.map((it) => (
                  <div
                    key={it.key}
                    className="flex items-center justify-between gap-2"
                  >
                    <dt className="text-muted">{it.label}</dt>
                    <dd className="flex items-center gap-1.5 text-right">
                      {it.display}
                      <ConfidenceDot c={it.confidence} />
                      {it.sources.length > 0 && (
                        <SourcesButton sources={it.sources} />
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        ))}
      </div>
    </BlockCard>
  );
}
