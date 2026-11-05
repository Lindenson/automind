import { translate, useT } from "../../i18n";
import { en, type Key } from "../../i18n/en";
import type { BlockOf } from "../../lib/protocol";
import { cx } from "../../lib/util";
import { useChat } from "../../store/chat";
import { useCarColor } from "../carColors";
import { Reveal } from "../badges";

const STATUS: Record<string, { cls: string }> = {
  COMPLETE: { cls: "border-good/40 bg-good/10 text-good" },
  PARTIAL: { cls: "border-warn/40 bg-warn/10 text-warn" },
  MISSING: { cls: "border-line text-muted" },
  UNAVAILABLE: { cls: "border-bad/30 text-bad/90" },
};

type Tried = { domain: string; outcome: string; reason?: string | null };
type T = (key: Key, vars?: Record<string, string | number>) => string;
const english: T = (key, vars) => translate("en", key, vars);

/** "km77.com (no value), motor.es (robots), coches.com (rejected: other variant)" (spec 011 FR-022, 010 T067). */
export function triedText(tried: Tried[], t: T = english): string {
  return tried
    .map((x) => {
      const key = `panel.tried.${x.outcome}` as Key;
      const what = key in en ? t(key) : x.outcome.replace(/_/g, " ");
      return `${x.domain} (${what}${x.reason ? `: ${x.reason.replace(/_/g, " ")}` : ""})`;
    })
    .join(", ");
}

/** "What we know": one compact panel per report instead of a warning per section (spec 004 FR-014/015). */
export function DataPanel({ b }: { b: BlockOf<"data_panel"> }) {
  const t = useT();
  const color = useCarColor();
  const find = useChat((s) => s.find);
  const busy = useChat((s) => Boolean(s.pending));
  return (
    <section aria-label={t("panel.title")} className="card space-y-3 p-3 sm:p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{t("panel.title")}</h3>
        {b.changed && <span className="text-xs text-good">{b.changed}</span>}
      </div>
      {b.cars.map((car) => {
        const gaps = car.areas.filter((a) => a.findable && a.status !== "COMPLETE");
        return (
          <div key={car.car_id} className="space-y-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="flex items-center gap-2 font-medium">
                <span
                  aria-hidden
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: color(car.car_id) }}
                />
                {car.label}
                <span className="text-xs font-normal text-muted">{t("panel.values", { n: car.values })}</span>
              </span>
              {gaps.length > 0 && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    find(
                      [car.car_key],
                      gaps.map((g) => g.area),
                      t("panel.find.text", { car: car.label, areas: gaps.map((g) => g.area).join(", ") }),
                    )
                  }
                  className="min-h-9 rounded-full border border-accent/50 bg-accent/10 px-3 py-1 text-xs hover:bg-accent/20 disabled:opacity-50"
                >
                  {t("panel.find")}
                </button>
              )}
            </div>
            <ul className="flex flex-wrap gap-1.5">
              {car.areas.map((a) => {
                const st = STATUS[a.status] ?? STATUS.MISSING!;
                const label = t(`panel.${a.status}` as "panel.MISSING");
                // the reason on tap or Enter, not in a hover-only tooltip (spec 010 FR-040)
                return (
                  <Reveal
                    as="li"
                    key={a.area}
                    reason={a.reason}
                    what={`${car.label}, ${a.area.replace("_", " ")}`}
                    className={cx("rounded-full border px-2 py-0.5 text-[11px]", st.cls)}
                  >
                    {a.area.replace("_", " ")}: {label}
                  </Reveal>
                );
              })}
            </ul>
            {car.areas
              .filter((a) => a.tried && a.tried.length > 0)
              .map((a) => (
                <p key={`tried-${a.area}`} className="text-[11px] leading-snug text-muted">
                  <span className="font-medium">{a.area.replace("_", " ")}</span>{" "}
                  {t("panel.tried", { list: triedText(a.tried ?? [], t) })}
                </p>
              ))}
          </div>
        );
      })}
    </section>
  );
}
