import { useT } from "../i18n";
import { useState } from "react";
import { useChat } from "../store/chat";

/** "This is wrong" on a value: re-checks it against its sources (spec 004 FR-022). */
export function ChallengeButton({ carId, attribute }: { carId: string; attribute: string }) {
  const t = useT();
  const challenge = useChat((s) => s.challenge);
  const [sent, setSent] = useState(false);
  return (
    <button
      type="button"
      disabled={sent}
      title={t("challenge.title")}
      aria-label={t("challenge.aria", { attr: attribute.replace(/_/g, " ") })}
      onClick={() => {
        challenge(carId, attribute);
        setSent(true);
      }}
      className="rounded px-1 text-[11px] text-muted hover:text-warn disabled:opacity-40"
    >
      {sent ? t("challenge.checking") : t("challenge.button")}
    </button>
  );
}
