import { useBlockTitle, useT } from "../../i18n";
/**
 * Criteria scores (FR-025..FR-028): 0–100 indices per criterion with visible weights. Each car's total
 * bar is split into the weighted contribution of every criterion. Missing data is shown, never guessed.
 */
import type { BlockOf } from "../../lib/protocol";
import { cx, fmtNum } from "../../lib/util";
import { BlockCard } from "../badges";
import { useCarColor } from "../carColors";
import { TrophyIcon } from "../icons";

const SHADES = [1, 0.8, 0.62, 0.48, 0.36, 0.27, 0.2];

/** Change since the previous report (spec 007 FR-013): shown only when it moved. */
function Delta({ d, small }: { d?: number | null; small?: boolean }) {
  if (d == null || Math.abs(d) < 0.5) return null;
  return (
    <span
      className={cx(
        "ml-1 rounded px-1 align-middle font-semibold tabular",
        small ? "text-[10px]" : "text-xs",
        d > 0 ? "bg-good/15 text-good" : "bg-bad/15 text-bad",
      )}
      title="change since the previous report"
    >
      {d > 0 ? "▲" : "▼"}
      {fmtNum(Math.abs(d), 0)}
    </span>
  );
}

export function CriteriaScores({ b }: { b: BlockOf<"criteria_scores"> }) {
  const t = useT();
  const color = useCarColor();
  const cars = [...b.cars].sort((x, y) => (y.total ?? -1) - (x.total ?? -1));
  const weightSum = b.criteria.reduce((a, c) => a + c.weight, 0) || 1;
  return (
    <BlockCard
      title={useBlockTitle(b.type, b.title)}
      icon={<TrophyIcon />}
      right={<span className="chip">scores, not measurements</span>}
    >
      <div className="space-y-4">
        {cars.map((car) => {
          const c = color(car.car_id);
          const win = car.car_id === b.winner_car_id;
          return (
            <div
              key={car.car_id}
              className={cx(
                "rounded-xl border p-3",
                win ? "border-accent/60 bg-accent/5" : "border-line/50",
              )}
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate font-display text-sm font-semibold">
                    {car.label}
                  </span>
                  {win && (
                    <span className="shrink-0 rounded-full bg-accent px-2 py-0.5 text-[10px] font-bold uppercase text-white">
                      Best fit
                    </span>
                  )}
                  {!car.ranked && b.cars.length > 1 && (
                    <span
                      className="shrink-0 rounded-full border border-warn/50 px-2 py-0.5 text-[10px] text-warn"
                      title="Less than 60% of the weight has data"
                    >
                      not ranked · {Math.round(car.coverage * 100)}% data
                    </span>
                  )}
                </div>
                <span
                  className="shrink-0 font-display text-2xl font-bold tabular"
                  style={{ color: c }}
                >
                  {car.total === null ? "—" : fmtNum(car.total, 0)}
                  <span className="text-xs font-medium text-muted">/100</span>
                  <Delta d={car.delta} />
                </span>
              </div>
              <div
                className="flex h-3 overflow-hidden rounded-full bg-panel2"
                aria-label="contribution of each criterion"
              >
                {b.criteria.map((cr, i) => {
                  const part = car.parts[cr.key];
                  if (!part || part.score === null) return null;
                  const width = (part.score * cr.weight) / weightSum;
                  return (
                    <div
                      key={cr.key}
                      title={`${cr.label}: ${fmtNum(part.score, 0)} × ${fmtNum(cr.weight, 0)}%`}
                      style={{
                        width: `${width}%`,
                        background: c,
                        opacity: SHADES[i % SHADES.length],
                      }}
                    />
                  );
                })}
              </div>
              <div className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2">
                {b.criteria.map((cr) => {
                  const part = car.parts[cr.key];
                  const insufficient =
                    !part || part.insufficient || part.score === null;
                  return (
                    <div
                      key={cr.key}
                      className="min-w-0"
                      title={part?.inputs.join("; ") || cr.definition}
                    >
                      <div className="flex items-baseline justify-between gap-1 text-[11px]">
                        <span className="truncate text-muted">{cr.label}</span>
                        <span className="tabular">
                          {insufficient ? (
                            <i className="text-warn/90">insufficient data</i>
                          ) : (
                            <>
                              {fmtNum(part!.score, 0)}
                              <Delta d={part!.delta} small />
                              {b.relative?.[cr.key]?.[car.car_id] !==
                                undefined && (
                                <span
                                  className="ml-1 text-muted"
                                  title="relative to the best of the compared cars (= 100)"
                                >
                                  ({fmtNum(b.relative[cr.key]![car.car_id]!, 0)}
                                  % {t("scores.ofBest")})
                                </span>
                              )}
                            </>
                          )}
                        </span>
                      </div>
                      <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-panel2">
                        {!insufficient && (
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${part!.score}%`,
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
          <span key={cr.key} className="chip" title={cr.definition}>
            {cr.label} <b className="text-fg">{fmtNum(cr.weight, 0)}%</b>
          </span>
        ))}
      </div>
      {(b.tie ||
        (b.compared_on && b.compared_on.length < b.criteria.length)) && (
        <p className="mt-2 text-xs text-muted">
          {b.tie ? "Too close to call: no winner. " : ""}
          {b.compared_on && b.compared_on.length < b.criteria.length
            ? `Totals compare only what every car has data for: ${
                b.criteria
                  .filter((c) => b.compared_on?.includes(c.key))
                  .map((c) => c.label)
                  .join(", ") || "—"
              }.`
            : ""}
        </p>
      )}
      {b.not_compared && b.not_compared.length > 0 && (
        <p className="mt-2 text-xs text-muted" data-testid="not-compared">
          {t("scores.notCompared")}
          {b.criteria
            .filter((c) => b.not_compared?.includes(c.key))
            .map((c) => c.label)
            .join(", ")}
        </p>
      )}
      {b.single && (
        <p className="mt-2 text-xs text-muted">{t("scores.single")}</p>
      )}
      {b.unmapped_wishes.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          Not assessable with data: {b.unmapped_wishes.join(", ")}
        </p>
      )}
    </BlockCard>
  );
}
