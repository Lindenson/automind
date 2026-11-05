import { useBlockTitle, useT } from "../../i18n";
import { useState } from "react";
import type { BlockOf, SourceRef } from "../../lib/protocol";
import { BlockCard, SourceItem } from "../badges";
import { BookIcon } from "../icons";

function Marks({ s }: { s: SourceRef }) {
  const t = useT();
  if (!s.favourite && s.extracted_by !== "READER") return null;
  return (
    <span className="mt-1 flex flex-wrap gap-1 text-[10px]">
      {s.favourite && (
        <span className="rounded bg-accent/15 px-1.5 py-0.5 font-medium text-accent">
          {t("sources.favourite")}
        </span>
      )}
      {s.extracted_by === "READER" && (
        <span className="rounded bg-good/15 px-1.5 py-0.5 font-medium text-good">
          {t("sources.reader")}
        </span>
      )}
    </span>
  );
}

export function Sources({ b }: { b: BlockOf<"sources"> }) {
  const accepted = b.items.filter((s) => !s.rejected);
  const rejected = b.items.filter((s) => s.rejected);
  const [open, setOpen] = useState(false);
  const t = useT();
  return (
    <BlockCard
      title={useBlockTitle(b.type, b.title)}
      icon={<BookIcon />}
      right={
        <span className="text-[11px] text-muted">
          {t("sources.references", { n: accepted.length })}
        </span>
      }
    >
      <ol className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
        {accepted.map((s, i) => (
          <li
            key={i}
            className="flex min-w-0 gap-3 rounded-lg border border-line/40 bg-panel2/30 p-2.5"
          >
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-panel2 text-[10px] font-bold text-muted">
              {i + 1}
            </span>
            <div className="min-w-0">
              <SourceItem s={s} compact />
              <Marks s={s} />
            </div>
          </li>
        ))}
      </ol>
      {rejected.length > 0 && (
        <div className="mt-3 text-sm">
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="text-xs font-medium text-muted hover:text-fg"
          >
            {open ? "▾" : "▸"} {t("sources.rejected", { n: rejected.length })}
          </button>
          {open && (
            <ul className="mt-2 space-y-1.5">
              {rejected.map((s, i) => (
                <li key={i} className="min-w-0 text-xs text-muted">
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="break-all underline decoration-line hover:text-fg"
                  >
                    {s.name}
                  </a>
                  <span> — {s.rejected?.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </BlockCard>
  );
}
