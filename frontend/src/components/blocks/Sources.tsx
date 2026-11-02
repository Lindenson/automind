import type { BlockOf } from "../../lib/protocol";
import { BlockCard, SourceItem } from "../badges";
import { BookIcon } from "../icons";

export function Sources({ b }: { b: BlockOf<"sources"> }) {
  return (
    <BlockCard
      title={b.title}
      icon={<BookIcon />}
      right={
        <span className="text-[11px] text-muted">
          {b.items.length} references
        </span>
      }
    >
      <ol className="grid gap-3 text-sm md:grid-cols-2">
        {b.items.map((s, i) => (
          <li
            key={i}
            className="flex min-w-0 gap-3 rounded-lg border border-line/40 bg-panel2/30 p-2.5"
          >
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-panel2 text-[10px] font-bold text-muted">
              {i + 1}
            </span>
            <SourceItem s={s} compact />
          </li>
        ))}
      </ol>
    </BlockCard>
  );
}
