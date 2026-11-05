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

// --- Sources (spec 010 US7) ---------------------------------------------------------------------------------------

const SOURCE_STATUS_CLS: Record<string, string> = {
  active: "border-good/50 text-good",
  candidate: "border-accent2/50 text-accent2",
  degraded: "border-warn/50 text-warn",
  retired: "border-line text-muted",
  blocked: "border-bad/50 text-bad",
};

export function SourceStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        SOURCE_STATUS_CLS[status] ?? "border-line text-muted",
      )}
    >
      {status}
    </span>
  );
}

const CHANGE_CLS: Record<string, string> = {
  promoted: "bg-good/15 text-good",
  added: "bg-accent2/15 text-accent2",
  reordered: "bg-accent2/15 text-accent2",
  demoted: "bg-warn/15 text-warn",
  retired: "bg-panel2 text-muted",
  blocked: "bg-bad/15 text-bad",
  frozen: "bg-accent/15 text-accent",
  unfrozen: "bg-accent/15 text-accent",
  reverted: "bg-panel2 text-fg",
  held: "bg-panel2 text-muted",
};

/** The label of a journal entry: a held change reads "held: frozen"; an unfreeze is journalled as "frozen". */
export function changeLabel(c: { change: string; held: boolean; after: Record<string, unknown> | null }): string {
  if (c.held) return "held: frozen";
  if (c.change === "frozen" && c.after && c.after.frozen === false) return "unfrozen";
  return c.change;
}

export function ChangeBadge({ c }: { c: { change: string; held: boolean; after: Record<string, unknown> | null } }) {
  const label = changeLabel(c);
  return (
    <span
      className={cx(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-semibold",
        CHANGE_CLS[c.held ? "held" : label] ?? "bg-panel2 text-muted",
      )}
    >
      {label}
    </span>
  );
}

/** Access verdicts that are not plain "ok" deserve a mark next to the domain. */
export function accessMark(access: string): string | null {
  return access === "ok" ? null : access.replace(/_/g, " ");
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
