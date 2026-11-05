import { translate, useT } from "../i18n";
import { useState } from "react";
import { useChat } from "../store/chat";
import { cx } from "../lib/util";

/** The three complaint classes of spec 010 (wrong car, doubtful data, not understood), offered on low ratings. */
export const RATING_REASONS = ["rating.reason.car", "rating.reason.numbers", "rating.reason.understood"] as const;
export type RatingReason = (typeof RATING_REASONS)[number];

/** Reasons are asked for ratings of 2 and below. */
export const asksReasons = (rating: number | null) => rating !== null && rating <= 2;

/** The note sent with a rating: the chosen reasons (low ratings only), then the user's own words. */
export function ratingNote(rating: number, reasons: string[], note: string): string {
  const parts = asksReasons(rating) ? [...reasons] : [];
  if (note.trim()) parts.push(note.trim());
  return parts.join("; ");
}

/** The DOM id of a report's rating, so the verdict's "Rate this answer" can jump to it (audit F12). */
export const ratingDomId = (messageId: string) => `rate-${messageId}`;

const RATED_KEY = "automind.rated";

/** Reports rated in this browser: the history has no rating, so a reload would ask again (audit F12). */
export function wasRated(messageId: string): boolean {
  try {
    return (JSON.parse(localStorage.getItem(RATED_KEY) ?? "[]") as string[]).includes(messageId);
  } catch {
    return false;
  }
}

export function markRated(messageId: string): void {
  try {
    const ids = (JSON.parse(localStorage.getItem(RATED_KEY) ?? "[]") as string[]).filter((x) => x !== messageId);
    localStorage.setItem(RATED_KEY, JSON.stringify([...ids, messageId].slice(-200)));
  } catch {
    /* storage unavailable: the "thanks" lasts for this page only */
  }
}

/** Rate a report 1–5 and say what was missing (spec 004 FR-026). Stored with the report for evaluation. */
export function RatingControl({ messageId }: { messageId: string }) {
  const t = useT();
  const rate = useChat((s) => s.rate);
  const [value, setValue] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [reasons, setReasons] = useState<RatingReason[]>([]);
  const [sent, setSent] = useState(() => wasRated(messageId));
  if (sent)
    return (
      <p id={ratingDomId(messageId)} className="text-xs text-muted">
        {t("rating.thanks")}
      </p>
    );
  const toggle = (r: RatingReason) =>
    setReasons((rs) => (rs.includes(r) ? rs.filter((x) => x !== r) : [...rs, r]));
  return (
    <div id={ratingDomId(messageId)} className="space-y-2 border-t border-line/40 pt-3 text-xs text-muted">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("rating.aria")}>
        <span>{t("rating.useful")}</span>
        <span aria-hidden>{t("rating.low")}</span>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={value === n}
            aria-label={n === 1 ? `1 — ${t("rating.low")}` : n === 5 ? `5 — ${t("rating.high")}` : String(n)}
            onClick={() => setValue(n)}
            className={
              "h-9 w-9 rounded-full border text-sm " +
              (value !== null && n <= value ? "border-accent bg-accent/15 text-fg" : "border-line/70")
            }
          >
            {n}
          </button>
        ))}
        <span aria-hidden>{t("rating.high")}</span>
      </div>
      {asksReasons(value) && (
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t("rating.reasons")}>
          <span>{t("rating.reasons")}</span>
          {RATING_REASONS.map((r) => {
            const on = reasons.includes(r);
            return (
              <button
                key={r}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(r)}
                className={cx(
                  "min-h-9 rounded-full border px-3 py-1",
                  on ? "border-accent bg-accent/15 text-fg" : "border-line/70 hover:border-accent/60",
                )}
              >
                {t(r)}
              </button>
            );
          })}
        </div>
      )}
      {value !== null && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("rating.note")}
            aria-label={t("rating.note")}
            className="min-h-9 min-w-0 flex-1 rounded-lg border border-line/70 bg-transparent px-2"
          />
          <button
            type="button"
            onClick={() => {
              rate(messageId, value, ratingNote(value, reasons.map((r) => translate("en", r)), note));
              markRated(messageId);
              setSent(true);
            }}
            className="min-h-9 rounded-full border border-accent/50 px-3 hover:bg-accent/10"
          >
            {t("rating.send")}
          </button>
        </div>
      )}
    </div>
  );
}
