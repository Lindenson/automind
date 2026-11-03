import type { BlockOf } from "../../lib/protocol";
import { cx } from "../../lib/util";
import { useChat } from "../../store/chat";
import { useCarColor } from "../carColors";

const STATUS: Record<string, { label: string; cls: string }> = {
  COMPLETE: { label: "complete", cls: "border-good/40 bg-good/10 text-good" },
  PARTIAL: { label: "partial", cls: "border-warn/40 bg-warn/10 text-warn" },
  MISSING: { label: "missing", cls: "border-line text-muted" },
  UNAVAILABLE: { label: "not found", cls: "border-bad/30 text-bad/90" },
};

/** "What we know": one compact panel per report instead of a warning per section (spec 004 FR-014/015). */
export function DataPanel({ b }: { b: BlockOf<"data_panel"> }) {
  const color = useCarColor();
  const find = useChat((s) => s.find);
  const busy = useChat((s) => Boolean(s.pending));
  return (
    <section aria-label="What we know" className="card space-y-3 p-3 sm:p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">What we know</h3>
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
                <span className="text-xs font-normal text-muted">{car.values} values</span>
              </span>
              {gaps.length > 0 && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    find(
                      [car.car_key],
                      gaps.map((g) => g.area),
                      `Find the missing data for ${car.label}: ${gaps.map((g) => g.area).join(", ")}`,
                    )
                  }
                  className="min-h-9 rounded-full border border-accent/50 bg-accent/10 px-3 py-1 text-xs hover:bg-accent/20 disabled:opacity-50"
                >
                  Find it
                </button>
              )}
            </div>
            <ul className="flex flex-wrap gap-1.5">
              {car.areas.map((a) => {
                const st = STATUS[a.status] ?? STATUS.MISSING!;
                return (
                  <li
                    key={a.area}
                    title={a.reason ?? st.label}
                    className={cx("rounded-full border px-2 py-0.5 text-[11px]", st.cls)}
                  >
                    {a.area.replace("_", " ")}: {st.label}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
