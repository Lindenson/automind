import type { Block } from "../../lib/protocol";
import { useChat } from "../../store/chat";

type B = Extract<Block, { type: "quick_replies" }>;

/** One-tap answers under a question: each sends its text as the user's message (spec 004 FR-031). */
export function QuickReplies({ b }: { b: B }) {
  const send = useChat((s) => s.send);
  const busy = useChat((s) => Boolean(s.pending));
  if (!b.items.length) return null;
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Quick answers">
      {b.items.map((it) => (
        <button
          key={it.label}
          type="button"
          disabled={busy}
          onClick={() => send(it.text)}
          className="min-h-11 rounded-full border border-line/70 px-4 py-2 text-sm hover:border-accent/60 disabled:opacity-50"
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}
