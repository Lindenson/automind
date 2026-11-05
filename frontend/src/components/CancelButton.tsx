/** Stops the running turn (FR-043). Validated data collected so far stays cached.
 *  Shown in the header of the status timeline, which only exists while a turn runs (audit F7). */
import { useT } from "../i18n";
import { useChat } from "../store/chat";

export function CancelButton() {
  const t = useT();
  return (
    <button
      type="button"
      onClick={() => useChat.getState().cancel()}
      aria-label={t("timeline.stop.aria")}
      title={t("timeline.stop.aria")}
      className="min-h-8 rounded-full border border-line/70 px-3 py-1 text-xs text-muted transition hover:border-bad/60 hover:text-bad"
    >
      {t("cancel.stop")}
    </button>
  );
}
