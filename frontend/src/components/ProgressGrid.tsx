import type { ProgressMsg } from "../lib/protocol";
import { cx } from "../lib/util";
import type { PendingTurn } from "../store/chat";

const STATE: Record<ProgressMsg["state"], { icon: string; label: string; cls: string }> = {
  queued: { icon: "·", label: "queued", cls: "text-muted border-line/60" },
  searching: { icon: "⌕", label: "searching", cls: "text-accent border-accent/40 animate-pulse" },
  reading: { icon: "≡", label: "reading", cls: "text-accent border-accent/40 animate-pulse" },
  done: { icon: "✓", label: "found", cls: "text-good border-good/40 bg-good/10" },
  partial: { icon: "◐", label: "partial", cls: "text-warn border-warn/40 bg-warn/10" },
  failed: { icon: "✕", label: "not found", cls: "text-bad/90 border-bad/30" },
  paused: { icon: "Ⅱ", label: "paused", cls: "text-warn border-warn/40" },
};

/** Research progress as a car × area grid (spec 004 FR-023). */
export function ProgressGrid({ pending }: { pending: PendingTurn }) {
  const cells = Object.values(pending.grid ?? {});
  if (!cells.length) return null;
  const cars = [...new Map(cells.map((c) => [c.car_key, c.car])).entries()];
  const areas = [...new Set(cells.map((c) => c.area))];
  const last = pending.statuses[pending.statuses.length - 1];
  return (
    <div className="card space-y-2 p-3" aria-label="Research progress">
      <div className="-mx-1 overflow-x-auto scroll-thin">
        <table className="w-full border-separate border-spacing-1 text-xs">
          <thead>
            <tr>
              <th className="text-left font-normal text-muted" />
              {areas.map((a) => (
                <th key={a} className="px-1 text-left font-normal capitalize text-muted">
                  {a.replace("_", " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cars.map(([key, label]) => (
              <tr key={key}>
                <th className="max-w-[9rem] truncate pr-2 text-left font-medium">{label}</th>
                {areas.map((a) => {
                  const c = pending.grid?.[`${key}|${a}`];
                  if (!c) return <td key={a} />;
                  const st = STATE[c.state];
                  return (
                    <td key={a}>
                      <span
                        title={`${st.label}${c.accepted ? ` · ${c.accepted} values` : ""}`}
                        className={cx("flex h-7 min-w-7 items-center justify-center rounded-md border", st.cls)}
                      >
                        {st.icon}
                        {c.accepted ? <span className="ml-0.5 tabular">{c.accepted}</span> : null}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {last && <p className="truncate text-xs text-muted">{last.text}</p>}
    </div>
  );
}
