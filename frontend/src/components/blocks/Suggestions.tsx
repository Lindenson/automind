import type { BlockOf } from "../../lib/protocol";
import { useChat } from "../../store/chat";

/** One-click next steps after a report (spec 004 FR-020). */
export function Suggestions({ b }: { b: BlockOf<"suggestions"> }) {
  const send = useChat((s) => s.send);
  const find = useChat((s) => s.find);
  const busy = useChat((s) => Boolean(s.pending));
  if (!b.items.length) return null;
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Next steps">
      {b.items.map((it) => (
        <button
          key={it.id}
          type="button"
          disabled={busy}
          onClick={() =>
            it.request.kind === "find"
              ? find(it.request.focus_cars ?? [], it.request.areas ?? [], it.request.text)
              : send(it.request.text)
          }
          className="min-h-11 rounded-full border border-line/70 px-4 py-2 text-sm hover:border-accent/60 disabled:opacity-50"
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}
