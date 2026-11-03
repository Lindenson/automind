import { useState } from "react";
import { useChat } from "../store/chat";

/** Rate a report 1–5 and say what was missing (spec 004 FR-026). Stored with the report for evaluation. */
export function RatingControl({ messageId }: { messageId: string }) {
  const rate = useChat((s) => s.rate);
  const [value, setValue] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);
  if (sent) return <p className="text-xs text-muted">Thanks — your rating is saved.</p>;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted" aria-label="Rate this report">
      <span>Useful?</span>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          aria-pressed={value === n}
          onClick={() => setValue(n)}
          className={
            "h-9 w-9 rounded-full border text-sm " +
            (value !== null && n <= value ? "border-accent bg-accent/15 text-fg" : "border-line/70")
          }
        >
          {n}
        </button>
      ))}
      {value !== null && (
        <>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What was missing? (optional)"
            className="min-h-9 min-w-0 flex-1 rounded-lg border border-line/70 bg-transparent px-2"
          />
          <button
            type="button"
            onClick={() => {
              rate(messageId, value, note);
              setSent(true);
            }}
            className="min-h-9 rounded-full border border-accent/50 px-3 hover:bg-accent/10"
          >
            Send
          </button>
        </>
      )}
    </div>
  );
}
