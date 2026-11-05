/** What AutoMind understood (case file summary) at the top of a report. */
import { useT } from "../../i18n";
import type { BlockOf } from "../../lib/protocol";
import { useCasePanel } from "../../store/case";
import { BlockCard } from "../badges";
import { InfoIcon } from "../icons";

type Summary = BlockOf<"case_summary">;

/** A car of the summary with its full version line (spec 010 FR-036). */
export function carLine(c: Summary["cars"][number]): string {
  return c.variant_label ? `${c.label} (${c.variant_label})` : c.label;
}

export function CaseSummary({ b }: { b: Summary }) {
  const t = useT();
  const persona =
    b.persona === "UNKNOWN"
      ? t("summary.persona.UNKNOWN")
      : t(`persona.${b.persona}` as "persona.BUYER");
  return (
    <BlockCard
      title={t("summary.title")}
      icon={<InfoIcon />}
      right={<span className="chip">{persona}</span>}
    >
      <ul className="flex flex-wrap gap-1.5 text-xs">
        {b.cars.map((c) => (
          <li
            key={c.key}
            className="rounded-full border border-line/60 px-2 py-0.5"
          >
            {c.label}{" "}
            {c.variant_label && (
              <span className="text-fg/80" data-testid="summary-version">
                · {c.variant_label}{" "}
              </span>
            )}
            <span className="text-muted">
              · {c.condition.toLowerCase()}
              {c.year && !c.variant_label?.includes(String(c.year)) ? ` ~${c.year}` : ""}
            </span>
          </li>
        ))}
        {b.facts.map((f) => (
          <li key={f} className="rounded-full bg-panel2 px-2 py-0.5 text-muted">
            {f}
          </li>
        ))}
      </ul>
    </BlockCard>
  );
}

/** A slim "Based on: …" strip above the verdict with an Edit link to the case panel (spec 010 FR-039). */
export function BasedOn({ b }: { b: Summary }) {
  const t = useT();
  const openAt = useCasePanel((s) => s.openAt);
  const parts = [...b.cars.map(carLine), ...b.facts];
  return (
    <p
      className="flex flex-wrap items-baseline gap-x-1.5 rounded-lg border border-line/50 bg-panel2/50 px-3 py-1.5 text-xs"
      data-testid="based-on"
    >
      <span className="font-semibold text-muted">{t("basedOn")}</span>
      <span className="min-w-0 flex-1">{parts.join(" · ")}</span>
      <button
        type="button"
        onClick={() => openAt(null)}
        className="font-medium text-accent underline-offset-2 hover:underline"
      >
        {t("basedOn.edit")}
      </button>
    </p>
  );
}
