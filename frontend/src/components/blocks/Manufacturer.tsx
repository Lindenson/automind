import { useBlockTitle, useT } from "../../i18n";
/** Sourced manufacturer background (history, key models, market position). */
import type { BlockOf } from "../../lib/protocol";
import { BlockCard, SourcesButton } from "../badges";
import { BookIcon } from "../icons";

const KIND: Record<string, string> = {
  HISTORY: "History",
  KEY_MODEL: "Key model",
  MARKET_POSITION: "Market position",
  MARKET_SHARE: "Market share",
  FINANCIAL: "Finances",
  RELIABILITY_REPUTATION: "Reliability reputation",
  NETWORK_ES: "Network in Spain",
  WARRANTY: "Warranty",
  BATTERY_WARRANTY: "Battery warranty",
};

export function Manufacturer({ b }: { b: BlockOf<"manufacturer"> }) {
  const t = useT();
  return (
    <BlockCard title={useBlockTitle(b.type, b.title)} icon={<BookIcon />}>
      <div className="space-y-3">
        {b.makes.map((m) => (
          <div key={m.make}>
            <div className="mb-1 font-display text-sm font-semibold">
              {m.make}
            </div>
            <ul className="space-y-1 text-sm">
              {m.facts.map((f, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="chip shrink-0 text-[10px]">
                    {KIND[f.kind] ? t(`maker.${f.kind}` as "maker.HISTORY") : f.kind}
                    {f.year ? ` ${f.year}` : ""}
                  </span>
                  <span className="min-w-0 flex-1">{f.text}</span>
                  {f.sources.length > 0 && (
                    <SourcesButton sources={f.sources} />
                  )}
                </li>
              ))}
            </ul>
            {m.insufficient && (
              <p className="mt-1 text-xs text-warn">
                {t("maker.insufficient")}
              </p>
            )}
          </div>
        ))}
      </div>
    </BlockCard>
  );
}
