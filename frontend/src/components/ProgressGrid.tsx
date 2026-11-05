import { useEffect, useState } from "react";
import { useT } from "../i18n";
import type { ProgressMsg } from "../lib/protocol";
import { cx, sentence } from "../lib/util";
import type { PendingTurn } from "../store/chat";

const STATE: Record<ProgressMsg["state"], { icon: string; cls: string }> = {
  queued: { icon: "·", cls: "text-muted border-line/60" },
  searching: { icon: "⌕", cls: "text-accent border-accent/40 animate-pulse" },
  reading: { icon: "≡", cls: "text-accent border-accent/40 animate-pulse" },
  done: { icon: "✓", cls: "text-good border-good/40 bg-good/10" },
  partial: { icon: "◐", cls: "text-warn border-warn/40 bg-warn/10" },
  failed: { icon: "✕", cls: "text-bad/90 border-bad/30" },
  paused: { icon: "Ⅱ", cls: "text-warn border-warn/40" },
};

/** The glyphs explained in one line (audit F7), in reading order of a research. */
const LEGEND: ProgressMsg["state"][] = ["searching", "reading", "done", "partial", "failed"];

/** Research progress as a car × area grid (spec 004 FR-023), with a legend and the elapsed time. */
export function ProgressGrid({ pending }: { pending: PendingTurn }) {
  const t = useT();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const cells = Object.values(pending.grid ?? {});
  if (!cells.length) return null;
  const cars = [...new Map(cells.map((c) => [c.car_key, c.car])).entries()];
  const areas = [...new Set(cells.map((c) => c.area))];
  const last = pending.statuses[pending.statuses.length - 1];
  const elapsed = Math.max(0, Math.round((now - pending.startedAt) / 1000));
  return (
    <div className="card space-y-2 p-3" aria-label={t("progress.aria")}>
      <div className="flex items-center justify-between gap-2 text-sm font-medium">
        <span>{t("progress.title")}</span>
        <span className="tabular text-xs font-normal text-muted" data-testid="progress-elapsed">
          {t("progress.seconds", { s: elapsed })}
        </span>
      </div>
      <div className="-mx-1 overflow-x-auto scroll-thin">
        <table className="w-full border-separate border-spacing-1 text-xs">
          <thead>
            <tr>
              <th className="text-left font-normal text-muted" />
              {areas.map((a) => (
                <th key={a} className="px-1 text-left font-normal text-muted">
                  {sentence(a)}
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
                  const what = `${t(`progress.${c.state}` as "progress.done")}${c.accepted ? ` · ${c.accepted}` : ""}`;
                  return (
                    <td key={a}>
                      <span
                        title={what}
                        role="img"
                        aria-label={`${label}, ${sentence(a)}: ${what}`}
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
      <p className="text-[11px] text-muted" data-testid="progress-legend">
        {LEGEND.map((s) => `${STATE[s].icon} ${t(`progress.${s}` as "progress.done")}`).join(" · ")}
      </p>
      {last && <p className="truncate text-xs text-muted">{last.text}</p>}
    </div>
  );
}
