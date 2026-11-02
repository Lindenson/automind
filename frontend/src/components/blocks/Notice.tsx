import type { BlockOf } from "../../lib/protocol";
import { cx } from "../../lib/util";
import { InfoIcon, WarnIcon } from "../icons";

export function Notice({ b }: { b: BlockOf<"notice"> }) {
  const warn = b.level === "warning";
  return (
    <div
      role={warn ? "alert" : "note"}
      className={cx(
        "flex animate-fadeUp items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-sm",
        warn
          ? "border-warn/40 bg-warn/10 text-fg"
          : "border-accent2/30 bg-accent2/10 text-fg",
      )}
    >
      <span
        className={cx("mt-0.5 shrink-0", warn ? "text-warn" : "text-accent2")}
      >
        {warn ? <WarnIcon /> : <InfoIcon />}
      </span>
      <span className="min-w-0">{b.text}</span>
    </div>
  );
}
