import { useContext } from "react";
import { useT } from "../../i18n";
import type { BlockOf } from "../../lib/protocol";
import { useChat } from "../../store/chat";
import { DataPanelPresent } from "./Verdict";

/**
 * One-click next steps after a report (spec 004 FR-020), as a labelled "Next:" row so they do not look like answers
 * to a question (audit F11). A "find" step is left out when the report has a data panel: its per-car "Find it" is the
 * one find action of the report.
 */
export function Suggestions({ b }: { b: BlockOf<"suggestions"> }) {
  const t = useT();
  const send = useChat((s) => s.send);
  const find = useChat((s) => s.find);
  const busy = useChat((s) => Boolean(s.pending));
  const hasPanel = useContext(DataPanelPresent);
  const items = b.items.filter((it) => !(hasPanel && it.request.kind === "find"));
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("next.aria")} data-testid="next-steps">
      <span className="text-xs font-semibold text-muted">{t("next.label")}</span>
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          disabled={busy}
          onClick={() =>
            it.request.kind === "find"
              ? find(it.request.focus_cars ?? [], it.request.areas ?? [], it.request.text)
              : send(it.request.text)
          }
          className="min-h-11 rounded-lg border border-dashed border-line px-3 py-2 text-sm hover:border-accent/60 disabled:opacity-50"
        >
          {it.label} <span aria-hidden>→</span>
        </button>
      ))}
    </div>
  );
}
