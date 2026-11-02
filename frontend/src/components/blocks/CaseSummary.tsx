/** What AutoMind understood (case file summary) at the top of a report. */
import type { BlockOf } from "../../lib/protocol";
import { BlockCard } from "../badges";
import { InfoIcon } from "../icons";

const PERSONA: Record<string, string> = {
  EXPERT: "Engineer / expert",
  PERFORMANCE: "Performance enthusiast",
  BUYER: "Everyday / family buyer",
  UNKNOWN: "Balanced view",
};

export function CaseSummary({ b }: { b: BlockOf<"case_summary"> }) {
  return (
    <BlockCard
      title="What I understood"
      icon={<InfoIcon />}
      right={<span className="chip">{PERSONA[b.persona]}</span>}
    >
      <ul className="flex flex-wrap gap-1.5 text-xs">
        {b.cars.map((c) => (
          <li
            key={c.key}
            className="rounded-full border border-line/60 px-2 py-0.5"
          >
            {c.label}{" "}
            <span className="text-muted">
              · {c.condition.toLowerCase()}
              {c.year ? ` ~${c.year}` : ""}
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
