import type { BlockOf } from "../../lib/protocol";
import { cx } from "../../lib/util";
import { useChat } from "../../store/chat";
import { useCarColor } from "../carColors";

const CONF: Record<string, { label: string; cls: string }> = {
  HIGH: { label: "High confidence", cls: "border-good/40 text-good" },
  MEDIUM: { label: "Medium confidence", cls: "border-warn/40 text-warn" },
  LOW: { label: "Low confidence", cls: "border-bad/40 text-bad" },
};

/** The verdict card: first block of every report (spec 004 FR-001). Built by code; every number is sourced. */
export function Verdict({ b }: { b: BlockOf<"verdict"> }) {
  const color = useCarColor();
  const conf = CONF[b.confidence] ?? CONF.MEDIUM!;
  return (
    <section
      aria-label="Verdict"
      className="card animate-fadeUp space-y-3 border-accent/50 p-3 sm:p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="flex min-w-0 items-center gap-2 text-base font-semibold sm:text-lg">
          {b.pick_car_id && (
            <span
              aria-hidden
              className="inline-block h-3 w-3 shrink-0 rounded-full"
              style={{ background: color(b.pick_car_id) }}
            />
          )}
          <span className="min-w-0">{b.headline}</span>
        </h2>
        <span
          className={cx("shrink-0 rounded-full border px-2 py-0.5 text-xs", conf.cls)}
          title={b.confidence_reason}
        >
          {conf.label}
        </span>
      </div>
      {b.reasons.length > 0 && (
        <ul className="space-y-1 text-sm">
          {b.reasons.map((r) => (
            <li key={r.insight_id} className="flex gap-2">
              <span aria-hidden className="text-accent">
                •
              </span>
              <span className="min-w-0">{r.text}</span>
            </li>
          ))}
        </ul>
      )}
      {b.trade_off && (
        <p className="rounded-lg bg-accent/10 px-3 py-2 text-sm">
          <span className="font-medium">Trade-off: </span>
          {b.trade_off.text}
        </p>
      )}
      <p className="text-xs text-muted">{b.confidence_reason}</p>
      {b.would_change && <p className="text-sm text-fg/80">{b.would_change}</p>}
      {b.gaps.length > 0 && <FindIt />}
    </section>
  );
}

/** "Find it": research the missing key data and rebuild the report (spec 004 US1 scenario 4, US4). */
function FindIt() {
  const send = useChat((s) => s.send);
  const busy = useChat((s) => Boolean(s.pending));
  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => send("Find the missing data and update the report")}
      className="min-h-11 rounded-full border border-accent/50 bg-accent/10 px-4 py-2 text-sm hover:bg-accent/20 disabled:opacity-50"
    >
      Find the missing data
    </button>
  );
}
