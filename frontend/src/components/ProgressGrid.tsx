import { useT } from "../i18n";
import type { ProgressMsg } from "../lib/protocol";
import { cx, sentence } from "../lib/util";
import type { PendingTurn } from "../store/chat";
import { Reveal } from "./badges";

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

/**
 * Research progress as a car × area grid (spec 004 FR-023), shown inside the status timeline under the stage rail
 * (audit F7). The grid scrolls sideways inside its own box with the car column pinned, so it fits 390 px.
 */
export function ProgressGrid({ pending }: { pending: PendingTurn }) {
  const t = useT();
  const cells = Object.values(pending.grid ?? {});
  if (!cells.length) return null;
  const cars = [...new Map(cells.map((c) => [c.car_key, c.car])).entries()];
  const areas = [...new Set(cells.map((c) => c.area))];
  return (
    <div className="space-y-1.5" data-testid="progress-grid">
      <div
        className="scroll-thin overflow-x-auto rounded-lg border border-line/40"
        tabIndex={0}
        role="region"
        aria-label={t("progress.aria")}
      >
        <table className="min-w-full border-separate border-spacing-0 text-xs">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-panel" />
              {areas.map((a) => (
                <th key={a} className="whitespace-nowrap px-1.5 py-1 text-left font-normal text-muted">
                  {sentence(a)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cars.map(([key, label]) => (
              <tr key={key}>
                <th
                  scope="row"
                  className="sticky left-0 z-10 max-w-[8rem] truncate bg-panel px-2 py-1 text-left font-medium"
                  title={label}
                >
                  {label}
                </th>
                {areas.map((a) => {
                  const c = pending.grid?.[`${key}|${a}`];
                  if (!c) return <td key={a} />;
                  const st = STATE[c.state];
                  const what = `${t(`progress.${c.state}` as "progress.done")}${c.accepted ? ` · ${c.accepted}` : ""}`;
                  return (
                    <td key={a} className="px-1.5 py-1">
                      <Reveal
                        reason={what}
                        what={`${label}, ${sentence(a)}`}
                        plain
                        className={cx("flex h-7 min-w-7 items-center justify-center rounded-md border", st.cls)}
                      >
                        {st.icon}
                        {c.accepted ? <span className="ml-0.5 tabular">{c.accepted}</span> : null}
                      </Reveal>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {areas.length > 2 && <p className="text-[11px] text-muted sm:hidden">{t("progress.scroll")} →</p>}
      <p className="text-[11px] text-muted" data-testid="progress-legend">
        {LEGEND.map((s) => `${STATE[s].icon} ${t(`progress.${s}` as "progress.done")}`).join(" · ")}
      </p>
    </div>
  );
}
