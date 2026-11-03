import { useBlockTitle, useT } from "../../i18n";
import type { BlockOf } from "../../lib/protocol";
import { cx } from "../../lib/util";
import { BlockCard } from "../badges";
import { useCarColor } from "../carColors";

const pct = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)}%`);
const eur = (x: number | null) => (x == null ? "" : `≈ €${x.toLocaleString("es-ES")}`);

/** Value left after 3 and 5 years (spec 004 FR-005): sourced points with market, or the labelled curve. */
export function ValueRetention({ b }: { b: BlockOf<"value_retention"> }) {
  const t = useT();
  const color = useCarColor();
  return (
    <BlockCard title={useBlockTitle(b.type, b.title)}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {b.cars.map((car) => (
          <div key={car.car_id} className="rounded-xl border border-line/50 p-3 text-sm">
            <div className="mb-2 font-semibold" style={{ color: color(car.car_id) }}>
              {car.label}
            </div>
            <ul className="space-y-1.5">
              {car.points.map((p) => (
                <li key={p.years} className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-muted">{t("retention.after", { n: p.years })}</span>
                  <span className="tabular">
                    <b>{pct(p.share)}</b>{" "}
                    {p.low != null && p.high != null && p.low !== p.high && (
                      <span className="text-muted">
                        ({pct(p.low)}–{pct(p.high)}){" "}
                      </span>
                    )}
                    <span className="text-muted">{eur(p.eur)}</span>
                  </span>
                  <span
                    className={cx(
                      "w-full text-[11px]",
                      p.basis === "SOURCED" ? "text-good" : "text-warn",
                    )}
                  >
                    {p.basis === "SOURCED"
                      ? `${t("retention.sourced", { market: p.market })} · ${p.sources.map((s) => s.name).filter(Boolean).join(", ")}`
                      : t("retention.assumed")}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </BlockCard>
  );
}
