/** Spec 010 T045: small badges of the admin page (status, proposed fix). */
import { cx } from "../lib/util";
import type { Fix } from "./schemas";

const STATUS_CLS: Record<string, string> = {
  open: "border-warn/50 text-warn",
  regression: "border-bad/50 text-bad",
  acknowledged: "border-accent2/50 text-accent2",
  fixed: "border-good/50 text-good",
  wontfix: "border-line text-muted",
};

export const STATUS_LABEL: Record<string, string> = {
  open: "open",
  regression: "regression",
  acknowledged: "acknowledged",
  fixed: "fixed",
  wontfix: "won't fix",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        STATUS_CLS[status] ?? "border-line text-muted",
      )}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** "9 in 7 days · 4 chats" */
export function frequency(turns: number, chats: number): string {
  return `${turns} in 7 days · ${chats} ${chats === 1 ? "chat" : "chats"}`;
}

/** Where the fix goes: the first file for code, `file: key` for config. */
export function fixTarget(fix: Fix): string {
  if (fix.kind === "code") {
    const [first] = fix.files;
    if (!first) return fix.direction ?? "";
    return fix.files.length > 1 ? `${first} +${fix.files.length - 1}` : first;
  }
  return [fix.config_file, fix.config_key].filter(Boolean).join(": ");
}

export function FixBadge({ fix }: { fix: Fix | null }) {
  if (!fix) {
    return (
      <span className="inline-flex items-center rounded-full border border-dashed border-line px-2 py-0.5 text-[11px] text-muted">
        not diagnosed
      </span>
    );
  }
  const target = fixTarget(fix);
  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 text-[11px]">
      <span
        className={cx(
          "shrink-0 rounded-full px-2 py-0.5 font-semibold uppercase tracking-wide",
          fix.kind === "code" ? "bg-accent2/15 text-accent2" : "bg-accent/15 text-accent",
        )}
      >
        {fix.kind}
      </span>
      {target && (
        <span className="truncate font-mono text-muted" title={target}>
          {target}
        </span>
      )}
    </span>
  );
}
