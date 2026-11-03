import { useBlockTitle, useT } from "../../i18n";
/** Tier 2 engineering details per car with confidence and sources (expert persona). */
import type { BlockOf } from "../../lib/protocol";
import { BlockCard, ConfidenceDot, SourcesButton } from "../badges";
import { useCarColor } from "../carColors";
import { WrenchIcon } from "../icons";

export function Engineering({ b }: { b: BlockOf<"engineering"> }) {
  const t = useT();
  const color = useCarColor();
  return (
    <BlockCard title={useBlockTitle(b.type, b.title)} icon={<WrenchIcon />}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
            {car.explainers.map((e) => (
              <details key={e.key} className="mt-2 rounded-lg bg-panel2/60 p-2 text-xs">
                <summary className="cursor-pointer font-medium">{e.title}</summary>
                <p className="mt-1 text-fg/80">{e.text}</p>
                <ul className="mt-1 space-y-0.5 text-muted">
                  {e.consumption && <li>{t("eng.consumption")}: {e.consumption}</li>}
                  {e.reliability && <li>{t("eng.reliability")}: {e.reliability}</li>}
                  {e.feel && <li>{t("eng.feel")}: {e.feel}</li>}
                </ul>
                {e.source === "editorial" && (
                  <p className="mt-1 text-[10px] uppercase tracking-wide text-muted">
                    {t("eng.editorial")}
                  </p>
                )}
              </details>
            ))}
          </div>
        ))}
      </div>
    </BlockCard>
  );
}
