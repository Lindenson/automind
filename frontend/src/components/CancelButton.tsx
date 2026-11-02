/** Stops the running turn (FR-043). Validated data collected so far stays cached. */
import { useChat } from "../store/chat";

export function CancelButton() {
  const cancel = useChat((s) => s.cancel);
  const running = useChat((s) => s.pending !== null);
  if (!running) return null;
  return (
    <button
      type="button"
      onClick={cancel}
      className="rounded-full border border-line/70 px-3 py-1 text-xs text-muted transition hover:border-bad/60 hover:text-bad"
    >
      Stop
    </button>
  );
}
