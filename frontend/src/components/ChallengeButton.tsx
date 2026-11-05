import { useT } from "../i18n";
import { useCallback, useId, useState, type ReactNode } from "react";
import { challengeKey, useChat, type ChallengeState } from "../store/chat";
import { useEscape } from "../lib/util";
import type { Key } from "../i18n/en";

export const CHALLENGE_REASONS = ["version", "outdated", "value"] as const;
export type ChallengeReason = (typeof CHALLENGE_REASONS)[number];

/** The text sent with "wrong?" (stored in the feedback, spec 010 US2): the reason, then the user's note. */
export function challengeText(reason: string, note: string): string {
  return [reason, note.trim()].filter(Boolean).join(": ");
}

/**
 * "wrong?" on a value (spec 004 FR-022, spec 010 FR-041): a small menu asks why — wrong for this version, outdated,
 * wrong value — with an optional note; the value is then re-checked against its sources and the result is shown in
 * the cell (see `ChallengedValue`).
 */
export function ChallengeButton({
  carId,
  attribute,
  label,
}: {
  carId: string;
  attribute: string;
  /** the row's label, as the user reads it */
  label?: string;
}) {
  const challenge = useChat((s) => s.challenge);
  const state = useChat((s) => s.challenges[challengeKey(carId, attribute)]);
  return (
    <ChallengeControl
      state={state}
      label={label ?? attribute.replace(/_/g, " ")}
      onSend={(text) => challenge(carId, attribute, text)}
    />
  );
}

/** The control by state (no store): "wrong?" with its menu, "checking…", or nothing once the cell has the result. */
export function ChallengeControl({
  state,
  label: name,
  onSend,
}: {
  state?: ChallengeState;
  label: string;
  onSend: (text: string) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const id = useId();
  const close = useCallback(() => setOpen(false), []);
  useEscape(open, close);
  if (state === "checking")
    return (
      <span className="px-1 text-[11px] text-muted" aria-live="polite">
        {t("challenge.checking")}
      </span>
    );
  if (state) return null; // the result is in the cell
  const send = (reason: string) => {
    onSend(challengeText(reason, note));
    setOpen(false);
    setNote("");
  };
  return (
    <span className="inline-flex flex-col items-start">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={t("challenge.aria", { attr: name })}
        onClick={() => setOpen((o) => !o)}
        className="rounded border border-transparent px-1 text-[11px] text-muted hover:border-warn/40 hover:text-warn"
      >
        {t("challenge.button")}
      </button>
      {open && (
        <span
          id={id}
          role="group"
          aria-label={t("challenge.menu", { attr: name })}
          className="mt-1 flex w-52 max-w-full flex-col gap-1 rounded-lg border border-line/70 bg-panel p-2 text-xs shadow-sm"
        >
          <span className="font-medium">{t("challenge.menu", { attr: name })}</span>
          {CHALLENGE_REASONS.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => send(t(`challenge.reason.${r}` as Key))}
              className="min-h-8 rounded border border-line/70 px-2 text-left hover:border-accent/60"
            >
              {t(`challenge.reason.${r}` as Key)}
            </button>
          ))}
          <label className="mt-1 flex flex-col gap-1">
            <span className="text-muted">{t("challenge.note")}</span>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value.slice(0, 200))}
              className="rounded border border-line/70 bg-panel2 px-1.5 py-1"
            />
          </label>
          <button
            type="button"
            disabled={!note.trim()}
            onClick={() => send("")}
            className="min-h-8 rounded bg-accent/15 px-2 font-medium disabled:opacity-40"
          >
            {t("challenge.send")}
          </button>
        </span>
      )}
    </span>
  );
}

/** The value of a cell after "wrong?" (FR-041): the old value struck, the new one, and "re-checked". */
export function ChallengedValue({
  carId,
  attribute,
  children,
}: {
  carId: string;
  attribute: string;
  children: ReactNode;
}) {
  const r = useChat((s) => s.challenges[challengeKey(carId, attribute)]);
  return <ChallengedCell result={r}>{children}</ChallengedCell>;
}

/** The cell by result (no store). */
export function ChallengedCell({ result: r, children }: { result?: ChallengeState; children: ReactNode }) {
  const t = useT();
  if (!r || r === "checking") return <>{children}</>;
  const badge = (
    <span className="rounded border border-accent2/50 px-1 text-[10px] uppercase text-accent2" data-testid="rechecked">
      {t("challenge.rechecked")}
    </span>
  );
  if (r.outcome === "CORRECTED")
    return (
      <>
        <s className="text-muted">{r.before ?? children}</s>
        <span className="tabular font-semibold text-fg">{r.after ?? "—"}</span>
        {badge}
      </>
    );
  if (r.outcome === "REMOVED")
    return (
      <>
        <s className="text-muted">{children}</s>
        <span className="text-xs text-muted">{t("challenge.cell.REMOVED")}</span>
        {badge}
      </>
    );
  return (
    <>
      {children}
      <span className="text-xs text-muted">
        {t(r.outcome === "CONFIRMED" ? "challenge.cell.CONFIRMED" : "challenge.cell.UNRESOLVED")}
      </span>
      {badge}
    </>
  );
}
